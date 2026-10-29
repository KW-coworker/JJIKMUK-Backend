package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.junit.jupiter.api.Test
import org.mockito.Mockito
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.datasource.DriverManagerDataSource
import java.util.UUID
import kotlin.test.*

class RecommendationEvaluationRunnerTest {
    @Test
    fun `migration preserves old cases and runner persists correct abstention metrics`() {
        val jdbc = database()
        jdbc.update("INSERT INTO product_recommendation_evaluation_cases " +
            "(case_id,user_id,reference_barcode,expected_relevant_barcodes,active) VALUES ('old',7,'REF','A',FALSE)")
        assertEquals("RECOMMENDATION", jdbc.queryForObject(
            "SELECT expected_outcome FROM product_recommendation_evaluation_cases WHERE case_id='old'", String::class.java))
        jdbc.update("INSERT INTO product_recommendation_evaluation_cases " +
            "(case_id,user_id,reference_barcode,expected_relevant_barcodes,expected_outcome,forbidden_barcodes) " +
            "VALUES ('abstain',7,'REF','','ABSTAIN','DANGER')")
        runner(jdbc).evaluateRecommendations().run()
        assertTrue(jdbc.queryForObject("SELECT passed FROM product_recommendation_evaluation_runs", Boolean::class.java)!!)
        assertEquals(1.0, jdbc.queryForObject("SELECT correct_abstention_rate FROM product_recommendation_evaluation_runs", Double::class.java))
        assertEquals(0.0, jdbc.queryForObject("SELECT unexpected_empty_response_rate FROM product_recommendation_evaluation_runs", Double::class.java))
        assertEquals(10, jdbc.queryForObject("SELECT evaluation_k FROM product_recommendation_evaluation_runs", Int::class.java))
        assertEquals("ABSTAIN", jdbc.queryForObject("SELECT expected_outcome FROM product_recommendation_evaluation_results", String::class.java))
        assertTrue(jdbc.queryForObject("SELECT outcome_matched FROM product_recommendation_evaluation_results", Boolean::class.java)!!)
    }

    @Test
    fun `unexpected abstention persists failed evaluation before failing the run`() {
        val jdbc = database()
        jdbc.update("INSERT INTO product_recommendation_evaluation_cases " +
            "(case_id,user_id,reference_barcode,expected_relevant_barcodes) VALUES ('positive',7,'REF','A')")
        assertFailsWith<IllegalArgumentException> { runner(jdbc).evaluateRecommendations().run() }
        assertFalse(jdbc.queryForObject("SELECT passed FROM product_recommendation_evaluation_runs", Boolean::class.java)!!)
        assertEquals(1.0, jdbc.queryForObject("SELECT unexpected_empty_response_rate FROM product_recommendation_evaluation_runs", Double::class.java))
    }

    private fun runner(jdbc: JdbcTemplate): RecommendationEvaluationRunner {
        val service = Mockito.mock(RecommendationService::class.java)
        val safety = SafetyDecision(SafetyStatus.UNKNOWN, emptyList(), emptyList(), AllergyEvidenceLevel.UNKNOWN, null, "근거 부족")
        val empty = ProductRecommendationResponse(
            requestId = "test", referenceProduct = Product(barcode = "REF"), referenceSafety = safety,
            userContext = UserRecommendationContext(7, emptyList(), emptyList(), emptyList(), 0, 0, 0.0, 0.0),
            policyVersion = RecommendationService.POLICY_VERSION, modelVersion = "test",
            precomputedCandidateCount = 0, eligibleCandidateCount = 0, requestedLimit = 10, minSimilarityScore = 0.2,
            items = emptyList(), excluded = RecommendationExclusionSummary(0,0,0,0,0,0,0),
            timing = RecommendationTiming(0,0,0,0,0), requiredActions = listOf("라벨 확인")
        )
        Mockito.`when`(service.recommendAlternatives("REF", 7, 10, 0.2)).thenReturn(empty)
        return RecommendationEvaluationRunner(service, jdbc, "test-v2", 10, 0.2, 0.3, 0.15, 1.0, 0.0, 60_000)
    }

    private fun database(): JdbcTemplate {
        val jdbc = JdbcTemplate(DriverManagerDataSource("jdbc:h2:mem:eval-${UUID.randomUUID()};MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", ""))
        jdbc.execute("CREATE TABLE products (barcode VARCHAR(32) PRIMARY KEY)")
        jdbc.execute("INSERT INTO products VALUES ('REF')")
        val v5 = resource("V5__add_recommendation_observability.sql")
        executeMysqlDdl(jdbc, "CREATE TABLE IF NOT EXISTS product_recommendation_evaluation_cases" +
            v5.substringAfter("CREATE TABLE IF NOT EXISTS product_recommendation_evaluation_cases"))
        val v6 = resource("V6__add_recommendation_fallback_observability.sql")
        executeMysqlDdl(jdbc, "ALTER TABLE product_recommendation_evaluation_runs" +
            v6.substringAfter("ALTER TABLE product_recommendation_evaluation_runs"))
        executeMysqlDdl(jdbc, resource("V13__add_recommendation_evaluation_outcomes.sql"))
        return jdbc
    }

    private fun resource(name: String): String = javaClass.getResource("/db/migration/$name")!!.readText()

    // H2 has no MySQL ALGORITHM option or multi-ADD syntax. Column definitions remain unmodified.
    private fun executeMysqlDdl(jdbc: JdbcTemplate, source: String) {
        source.replace(Regex("(?m)^--.*$"), "").replace(Regex(",\\s*ALGORITHM=INSTANT"), "")
            .split(';').map(String::trim).filter(String::isNotEmpty).forEach { sql ->
                val alter = Regex("(?s)ALTER TABLE (\\w+)\\s+(.*)").matchEntire(sql)
                if (alter == null) jdbc.execute(sql)
                else alter.groupValues[2].split(Regex(",\\s*(?=ADD COLUMN)")).forEach {
                    jdbc.execute("ALTER TABLE ${alter.groupValues[1]} $it")
                }
            }
    }
}
