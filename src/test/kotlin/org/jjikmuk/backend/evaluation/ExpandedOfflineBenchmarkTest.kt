package org.jjikmuk.backend.evaluation

import org.jjikmuk.backend.domain.product.*
import org.jjikmuk.backend.domain.product.search.ProductSearchKeywordBuilder
import org.jjikmuk.backend.domain.recommendation.*
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable
import org.mockito.Mockito.mock
import org.springframework.context.ApplicationEventPublisher
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.datasource.SingleConnectionDataSource
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardOpenOption
import java.security.MessageDigest
import java.sql.DriverManager
import java.util.Optional
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Opt-in evaluation only. No Spring context, DB users, migrations, telemetry or DB writes.
 * Recommendation repositories replay frozen product data; search uses one READ ONLY MySQL session.
 */
@EnabledIfEnvironmentVariable(named = "JJIKMUK_BENCHMARK_DIR", matches = ".+")
class ExpandedOfflineBenchmarkTest {
    private val mapper = JsonMapper.builder().findAndAddModules().build()
    private val directory = Path.of(System.getenv("JJIKMUK_BENCHMARK_DIR") ?: ".")
    private fun read(name: String) = mapper.readTree(Files.readString(directory.resolve(name)))
    private fun save(name: String, value: Any) = Files.writeString(directory.resolve(name),
        mapper.writerWithDefaultPrettyPrinter().writeValueAsString(value), StandardOpenOption.CREATE_NEW)
    private fun JsonNode.text(key: String): String? = get(key)?.takeUnless { it.isNull }?.asText()
    private fun JsonNode.number(key: String): Double? = get(key)?.takeUnless { it.isNull }?.asDouble()
    private fun JsonNode.flag(key: String): Boolean = get(key)?.let { if (it.isBoolean) it.asBoolean() else it.asInt() == 1 } ?: false
    private fun JsonNode.strings(): Set<String> = iterator().asSequence().map { it.asText() }.toSet()

    private fun product(n: JsonNode) = Product(
        barcode = n.text("barcode")!!, productName = n.text("product_name"), cleanProductName = n.text("clean_product_name"),
        manufacturer = n.text("manufacturer"), rawMaterials = n.text("raw_materials"), allergy = n.text("allergy"),
        allergyWarning = n.text("allergy_warning"), foodType = n.text("food_type"), foodCategories = n.text("food_categories"),
        allergyClassification = n.text("allergy_classification"), totalWeight = n.text("total_weight"),
        imageUrl = n.text("image_url"), productGroupKey = n.text("product_group_key"),
        energyKcal = n.number("energy_kcal"), proteinG = n.number("protein_g"), fatG = n.number("fat_g"),
        sugarG = n.number("sugar_g"), sodiumMg = n.number("sodium_mg"), carbsG = n.number("carbs_g"),
        cholesterolMg = n.number("cholesterol_mg"), vegan = n.flag("is_vegan"),
        lactoVegetarian = n.flag("is_lacto_vegetarian"), ovoVegetarian = n.flag("is_ovo_vegetarian"),
        lactoOvoVegetarian = n.flag("is_lacto_ovo_vegetarian"), pescatarian = n.flag("is_pescatarian"), pollotarian = n.flag("is_pollotarian"),
        lowSugar = n.flag("is_low_sugar"), lowSodium = n.flag("is_low_sodium"), glutenFree = n.flag("is_gluten_free"),
        lowCalorie = n.flag("is_low_calorie"), lowFat = n.flag("is_low_fat"), highProtein = n.flag("is_high_protein"),
        allergyEvidenceLevel = AllergyEvidenceLevel.valueOf(n.text("allergy_evidence_level") ?: "UNKNOWN"),
        nutritionDataOrigin = ProductDataOrigin.valueOf(n.text("nutrition_data_origin") ?: "UNKNOWN"),
        nutritionDataConfidence = n.number("nutrition_data_confidence"),
        dietaryDataOrigin = ProductDataOrigin.valueOf(n.text("dietary_data_origin") ?: "UNKNOWN"),
        dietaryDataConfidence = n.number("dietary_data_confidence")
    )

    @Test fun `frozen recommendation corpus and original regression are replayed without DB`() {
        val manifest = read("expanded-frozen-v2.json")
        val evidenceBytes = Files.readAllBytes(directory.resolve("expanded-evidence.json"))
        assertEquals(manifest.text("evidence_sha256"), MessageDigest.getInstance("SHA-256").digest(evidenceBytes).joinToString("") { "%02x".format(it) })
        val evidence = read("expanded-evidence.json")
        val old = mapper.readTree(Files.readString(Path.of(System.getenv("JJIKMUK_ORIGINAL_BENCHMARK"))))
        val oldEvidence = mapper.readTree(Files.readString(Path.of(System.getenv("JJIKMUK_ORIGINAL_EVIDENCE"))))
        val output = mutableListOf<Map<String, Any?>>()
        val oldEvaluations = mutableListOf<RecommendationEvaluationCase>()
        for ((data, definitions, oldRun) in listOf(Triple(oldEvidence, old, true), Triple(evidence, manifest, false))) {
            val catalog = data["candidates"].iterator().asSequence().map(::product).associateBy { it.barcode }.toMutableMap()
            val refs = data["references"].iterator().asSequence().associateBy { it.at("/product/barcode").asText() }
            refs.values.forEach { catalog[it.at("/product/barcode").asText()] = product(it["product"]) }
            var currentUser = User(id = 1, email = "benchmark@example.invalid", nickname = "benchmark", password = "DISABLED")
            var poolLimit = 100
            val productRepo = mock(ProductRepository::class.java) { call -> when (call.method.name) {
                "findById" -> Optional.ofNullable(catalog[call.arguments[0]])
                "findAllById" -> (call.arguments[0] as Iterable<*>).mapNotNull { catalog[it] }
                else -> error("Unexpected product repository operation: ${call.method.name}")
            } }
            val userRepo = mock(UserRepository::class.java) { call ->
                require(call.method.name == "findById"); Optional.of(currentUser)
            }
            val historyRepo = mock(HistoryRepository::class.java) { call ->
                require(call.method.name == "findTop200ByUserIdOrderByCreatedAtDesc"); emptyList<Any>()
            }
            val neighborRepo = mock(ProductNeighborSetRepository::class.java) { call ->
                require(call.method.name == "findById")
                val r = refs[call.arguments[0]]!!
                val neighbors = r["neighbors"].asText().split(',').take(poolLimit)
                Optional.of(ProductNeighborSet(call.arguments[0] as String, r.text("model") ?: "frozen", neighbors.size, neighbors.joinToString(",")))
            }
            val policy = RecommendationPolicy()
            val service = RecommendationService(neighborRepo, productRepo, userRepo, historyRepo, policy,
                ApplicationEventPublisher { }, 0.70, 0.25, 0.05, 0.85)
            val cases = definitions[if (oldRun) "cases" else "recommendation_cases"]
            for (case in cases) {
                val profile = definitions["profiles"][case["profile"].asText()]
                currentUser = User(id = 1, email = "benchmark@example.invalid", nickname = "benchmark", password = "DISABLED",
                    allergies = profile.text("allergies"), specialDiet = profile.text("specialDiet"), dislikedIngredients = profile.text("dislikedIngredients"))
                val reference = case["reference_barcode"].asText()
                val sizes = if (!oldRun && case["profile"].asText() in setOf("general", "milk", "soy", "vegan")) listOf(20,50,100) else listOf(100)
                for (size in sizes) {
                    poolLimit = size
                    val started = System.nanoTime()
                    val response = service.recommendAlternatives(reference, 1, 10, 0.2)
                    val elapsed = (System.nanoTime() - started) / 1000
                    val forbidden = case["forbidden_barcodes"].strings()
                    val allItems = response.items + response.fallbackItems
                    val candidates = refs[reference]!!["neighbors"].asText().split(',').take(size).mapNotNull { catalog[it.substringBefore('|')] }
                    val rawPositiveMisses = candidates.filter { it.barcode in forbidden &&
                        policy.evaluateSafety(it, policy.allergyProfileTerms(currentUser.allergies)).status != SafetyStatus.DANGER &&
                        policy.evaluateDietConstraints(it, policy.requiredFilters(currentUser)).status != DietConstraintStatus.MISMATCH &&
                        !policy.containsDislikedIngredient(it, policy.profileTerms(currentUser.dislikedIngredients)) }.map { it.barcode }
                    val row = linkedMapOf<String,Any?>("case_id" to case["case_id"].asText(), "old_regression" to oldRun,
                        "reference_barcode" to reference, "profile" to case["profile"].asText(), "pool_size" to size,
                        "result_mode" to response.resultMode, "excluded" to response.excluded, "latency_micros" to elapsed,
                        "raw_positive_not_blocked" to rawPositiveMisses, "forbidden_returned" to allItems.filter { it.product.barcode in forbidden }.map { it.product.barcode },
                        "items" to allItems.map { mapOf("barcode" to it.product.barcode, "name" to it.product.productName,
                            "categoryIds" to it.product.foodCategoryIds, "originalRank" to it.originalRank,
                            "safety" to it.safety.status, "diet" to it.dietConstraints.status, "tier" to it.recommendationTier,
                            "dietAttributes" to it.dietConstraints.attributes, "verificationRequired" to it.verificationRequired,
                            "warnings" to it.warnings, "requiredActions" to it.requiredActions) })
                    output += row
                    if (oldRun) oldEvaluations += RecommendationEvaluationCase(case["case_id"].asText(), case["expected_relevant_barcodes"].strings(),
                        response, elapsed, ExpectedRecommendationOutcome.valueOf(case["expected_outcome"].asText()), forbidden)
                }
            }
        }
        save("recommendation-results.json", output)
        save("original-regression-report.json", RecommendationOfflineEvaluator.evaluate(oldEvaluations, 1348425, 10))
        assertEquals(20, oldEvaluations.size)
    }

    @Test fun `current MySQL search repository is measured in a read only local session`() {
        val url = System.getenv("JJIKMUK_SEARCH_JDBC") ?: error("Guarded local connection required")
        require(url.matches(Regex("jdbc:mysql://127\\.0\\.0\\.1:[0-9]+/jjikmuk\\?.*")))
        val definition = read("expanded-frozen-v2.json")
        val output = mutableListOf<Map<String, Any?>>()
        DriverManager.getConnection(url, System.getenv("JJIKMUK_SEARCH_USER"), System.getenv("JJIKMUK_SEARCH_PASSWORD")).use { connection ->
            connection.createStatement().use { s -> s.executeQuery("SELECT @@server_uuid,@@hostname,DATABASE()").use { rows ->
                rows.next(); assertEquals(System.getenv("JJIKMUK_SEARCH_UUID"), rows.getString(1))
                assertEquals(System.getenv("COMPUTERNAME").lowercase(), rows.getString(2).lowercase()); assertEquals("jjikmuk", rows.getString(3))
            } }
            connection.isReadOnly = true
            connection.autoCommit = false
            connection.createStatement().use { it.execute("SET SESSION MAX_EXECUTION_TIME=12000"); it.execute("START TRANSACTION READ ONLY") }
            val jdbc = JdbcTemplate(SingleConnectionDataSource(connection, true)).apply { queryTimeout = 15 }
            val repo = mock(ProductRepository::class.java) { call ->
                require(call.method.name == "findAllById")
                val ids = (call.arguments[0] as Iterable<*>).toList()
                if (ids.isEmpty()) emptyList<Product>() else jdbc.query("SELECT barcode,product_name,clean_product_name,manufacturer,food_categories,total_weight FROM products WHERE barcode IN (${ids.joinToString(",") { "?" }})",
                    { row, _ -> Product(barcode = row.getString("barcode"), productName = row.getString("product_name"), cleanProductName = row.getString("clean_product_name"),
                        manufacturer = row.getString("manufacturer"), foodCategories = row.getString("food_categories"), totalWeight = row.getString("total_weight")) }, *ids.toTypedArray())
            }
            val search = DistinctProductSearchRepository(jdbc, repo, "locate", "key")
            val cache = mutableMapOf<String, Map<String, Any?>>()
            for (case in definition["search_cases"]) {
                val query = case["query"].asText()
                val normalized = ProductSearchKeywordBuilder.normalizeQuery(query)
                val reused = cache.containsKey(normalized)
                val observation = cache.getOrPut(normalized) {
                    val started = System.nanoTime()
                    try {
                        val found = search.searchByProductName(query, 10)
                        mapOf("products" to found, "latency_micros" to (System.nanoTime()-started)/1000, "error" to null)
                    } catch (e: Exception) {
                        // Error type only; never write URLs, credentials or raw SQL exceptions to the artifact.
                        mapOf("products" to emptyList<Product>(), "latency_micros" to (System.nanoTime()-started)/1000, "error" to e.javaClass.simpleName)
                    }
                }
                val row = linkedMapOf<String,Any?>("case_id" to case["case_id"].asText(), "query" to query, "normalized" to normalized,
                    "normalization_equivalent_reused" to reused, "kind" to case["kind"].asText(), "expected_outcome" to case["expected_outcome"].asText())
                row.putAll(observation)
                output += row
                Files.writeString(directory.resolve("search-progress.jsonl"), mapper.writeValueAsString(row)+"\n", StandardOpenOption.CREATE, StandardOpenOption.APPEND)
                println("Search benchmark ${output.size}/${definition["search_cases"].size()} ${case["case_id"].asText()} reused=$reused")
            }
            connection.rollback()
        }
        save("search-results.json", output)
        assertTrue(output.isNotEmpty())
    }
}
