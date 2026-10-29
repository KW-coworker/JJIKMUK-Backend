package org.jjikmuk.backend.integration

import com.sun.net.httpserver.HttpServer
import org.jjikmuk.backend.domain.auth.*
import org.jjikmuk.backend.domain.product.*
import org.jjikmuk.backend.domain.recommendation.*
import org.junit.jupiter.api.*
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.web.server.LocalServerPort
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.mail.javamail.JavaMailSender
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import org.springframework.test.context.bean.override.mockito.MockitoBean
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper
import java.net.InetSocketAddress
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import java.time.Duration
import java.util.UUID
import kotlin.test.*

/** Loopback HTTP + real security/services/JPA. Only SMTP and the external AI are substituted.
 * Never reads the application MySQL database or sends real mail/LLM requests.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = [
    "server.address=127.0.0.1",
    "spring.datasource.url=jdbc:h2:mem:core-http;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"
])
@ActiveProfiles("test")
@TestMethodOrder(MethodOrderer.OrderAnnotation::class)
class CoreUserFlowHttpIntegrationTest {
    @LocalServerPort private var port: Int = 0
    @Autowired private lateinit var products: ProductRepository
    @Autowired private lateinit var neighbors: ProductNeighborSetRepository
    @Autowired private lateinit var jdbc: JdbcTemplate
    @MockitoBean private lateinit var mail: JavaMailSender
    private val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()

    private fun request(method: String, path: String, body: Any? = null, token: String? = null,
                        expected: Int = 200): JsonNode {
        require(path.startsWith("/api/"))
        val builder = HttpRequest.newBuilder(URI("http://127.0.0.1:$port$path"))
            .timeout(Duration.ofSeconds(15)).header("Content-Type", "application/json")
        token?.let { builder.header("Authorization", "Bearer $it") }
        builder.method(method, body?.let { HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(it)) }
            ?: HttpRequest.BodyPublishers.noBody())
        val response = client.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        httpChecks += mapOf("method" to method, "path" to path.substringBefore('?'),
            "expectedStatus" to expected, "actualStatus" to response.statusCode())
        // Do not log bodies: authentication responses contain ephemeral credentials.
        assertEquals(expected, response.statusCode(), "$method ${path.substringBefore('?')}: HTTP status")
        return mapper.readTree(response.body())
    }
    private data class Session(val id: Long, val token: String, val refresh: String)
    private fun register(): Session {
        val key = UUID.randomUUID().toString().replace("-", "").take(12)
        val email = "$key@example.invalid"
        val send = request("POST", "/api/auth/email/send", mapOf("email" to email, "purpose" to "signup"))
        assertEquals(300, send.at("/data/expiresInSeconds").asInt())
        val otp = jdbc.queryForObject("SELECT code FROM email_verifications WHERE email=? AND purpose='SIGNUP'", String::class.java, email)!!
        assertEquals(4, otp.length)
        val proof = request("POST", "/api/auth/email/verify", mapOf("email" to email, "purpose" to "signup", "code" to otp))
        assertEquals(1800, proof.at("/data/expiresInSeconds").asInt())
        request("POST", "/api/auth/signup", mapOf("email" to email, "password" to "Example123!", "nickname" to "u$key",
            "allergies" to "milk", "verificationToken" to proof.at("/data/verificationToken").asText()), expected = 201)
        val login = request("POST", "/api/auth/login", mapOf("email" to email, "password" to "Example123!"))
        return Session(login["userId"].asLong(), login["token"].asText(), login["refreshToken"].asText())
    }
    @BeforeEach fun seed() {
        acknowledge = true
        fun item(code: String, name: String, raw: String?, weight: String = "100g", vegan: Boolean = true) {
            products.saveAndFlush(Product(barcode = code, productName = name, cleanProductName = name,
                manufacturer = "격리테스트제조사", totalWeight = weight, foodType = "과자", foodCategories = "snack",
                rawMaterials = raw, allergyEvidenceLevel = if (raw == null) AllergyEvidenceLevel.UNKNOWN else AllergyEvidenceLevel.DECLARED_LABEL,
                vegan = vegan, lowSugar = true, sugarG = 1.0, sodiumMg = 10.0,
                nutritionDataOrigin = ProductDataOrigin.SOURCE, dietaryDataConfidence = if (raw == null) null else 0.9))
            jdbc.update("MERGE INTO product_food_category_memberships (barcode, category_id) KEY(barcode, category_id) VALUES (?, ?)", code, "snack")
        }
        item("9900000000001", "테스트쌀칩", "쌀, 소금")
        item("9900000000002", "테스트쌀칩", "쌀, 소금", "200g")
        item("9900000000003", "테스트우유칩", "쌀, 우유")
        item("9900000000004", "테스트콩칩", "검정콩분말, 쌀")
        item("9900000000005", "테스트정보없음", null)
        item("9900000000006", "테스트새우칩", "쌀, 새우")
        item("9900000000007", "테스트감자칩", "감자, 소금")
        item("9900000000008", "테스트고구마칩", "고구마, 소금")
        neighbors.saveAndFlush(ProductNeighborSet("9900000000003", "isolated-http-fixture", 7,
            listOf(1, 2, 4, 5, 6, 7, 8).joinToString(",") { "990000000000$it|0.95" }))
    }

    @Test @Order(1) fun `signup profile family search capacity recommendation history chat refresh logout`() {
        val session = register(); val token = session.token
        request("GET", "/api/users/me", token = token)
        request("PATCH", "/api/users/me", mapOf("specialDiet" to "vegan", "allergies" to "milk"), token)
        val family = request("POST", "/api/users/me/family-profiles", mapOf("nickname" to "테스트가족", "allergies" to "soy"), token, 201)
        val selected = "?analysisMode=selected&includeSelf=true&familyProfileIds=${family.at("/data/id").asLong()}"
        val search = request("GET", "/api/products/search?keyword=${URLEncoder.encode("테스트쌀칩", "UTF-8")}", token = token)
        assertTrue(search["data"].isArray && search["data"].size() > 0)
        samples["search"] = search
        val variants = request("GET", "/api/products/9900000000001/variants$selected", token = token)
        assertEquals(2, variants.at("/data/optionCount").asInt())
        assertEquals(setOf("100g", "200g"), variants.at("/data/options").iterator().asSequence().map { it["label"].asText().replace(" ", "") }.toSet())
        samples["variants"] = variants
        val detail = request("GET", "/api/products/9900000000004$selected", token = token)
        assertEquals("DANGER", detail.at("/data/analysis/status").asText())
        samples["detail"] = detail
        val filtered = request("GET", "/api/products/filter?categories=snack&page=0&size=20", token = token)
        assertTrue(filtered.at("/data/items").size() > 0)
        val home = request("GET", "/api/products/safe-recommendations$selected&limit=1&seed=10&categories=snack", token = token)
        val first = home.at("/data/returnedBarcodes").iterator().asSequence().map { it.asText() }.toSet()
        assertEquals(1, first.size)
        val cursor = home.at("/data/nextCursor").asText()
        assertTrue(home.at("/data/hasNext").asBoolean())
        val next = request("GET", "/api/products/safe-recommendations$selected&limit=2&categories=snack&cursor=${URLEncoder.encode(cursor,"UTF-8")}&excludeBarcodes=${first.joinToString(",")}", token = token)
        assertTrue(next.at("/data/returnedBarcodes").none { it.asText() in first })
        for (page in listOf(home, next)) for (category in page.at("/data/categories")) for (item in category["items"]) {
            assertEquals("PASS", item.at("/safety/status").asText())
            assertEquals("PASS", item.at("/dietConstraints/status").asText())
        }
        samples["safeRecommendations"] = home
        request("GET", "/api/products/safe-recommendations?limit=1&cursor=${URLEncoder.encode(cursor,"UTF-8")}", token = token, expected = 400)
        val alternatives = request("GET", "/api/recommendations/products/9900000000003$selected", token = token)
        assertTrue(alternatives.at("/data/items").size() > 0)
        for (item in alternatives.at("/data/items")) {
            assertEquals("PASS", item.at("/safety/status").asText())
            assertEquals("PASS", item.at("/dietConstraints/status").asText())
        }
        samples["alternatives"] = alternatives
        request("POST", "/api/histories/events", mapOf("barcode" to "9900000000001", "actionType" to "FAVORITE"), token)
        assertTrue(request("GET", "/api/histories/user/${session.id}", token = token)["data"].size() > 0)
        val chat = request("POST", "/api/chat$selected", mapOf("message" to "표시 근거 설명", "barcode" to "9900000000004"), token)
        assertEquals("격리 HTTP 계약 테스트 응답", chat["answer"].asText())
        assertEquals(detail.at("/data/analysis"), lastAiRequest!!.at("/analysisContext/analysis"))
        samples["aiRequest"] = lastAiRequest!!
        val refreshed = request("POST", "/api/auth/refresh", mapOf("refreshToken" to session.refresh))
        assertNotEquals(session.refresh, refreshed["refreshToken"].asText())
        val newToken = refreshed["token"].asText()
        request("POST", "/api/auth/logout", token = newToken)
        request("GET", "/api/users/me", token = newToken, expected = 401)
    }

    @Test @Order(2) fun `unknown and contradictory vegan flags are not safe recommendations`() {
        val token = register().token
        request("PATCH", "/api/users/me", mapOf("specialDiet" to "vegan"), token)
        val unknown = request("GET", "/api/products/9900000000005", token = token)
        assertEquals("UNKNOWN", unknown.at("/data/analysis/status").asText())
        assertEquals("UNKNOWN", unknown.at("/data/analysis/dietConstraints/status").asText())
        val conflict = request("GET", "/api/products/9900000000006", token = token)
        assertEquals("MISMATCH", conflict.at("/data/analysis/dietConstraints/status").asText())
        val home = request("GET", "/api/products/safe-recommendations?limit=20&seed=10", token = token)
        assertTrue(home.at("/data/returnedBarcodes").none { it.asText() in setOf("9900000000003", "9900000000005", "9900000000006") })
        val none = request("GET", "/api/products/9900000000003?analysisMode=none", token = token)
        assertEquals("NOT_EVALUATED", none.at("/data/analysis/status").asText())
        samples["unknownDetail"] = unknown; samples["dietConflictDetail"] = conflict; samples["noneDetail"] = none
    }

    @Test @Order(3) fun `foreign family impersonation and stale AI contract fail closed`() {
        val owner = register(); val other = register()
        val family = request("POST", "/api/users/me/family-profiles", mapOf("nickname" to "보호가족"), owner.token, 201)
        request("GET", "/api/products/9900000000001?analysisMode=selected&familyProfileIds=${family.at("/data/id").asLong()}", token = other.token, expected = 404)
        request("POST", "/api/chat", mapOf("message" to "질문", "userId" to owner.id), other.token, 403)
        request("POST", "/api/chat", mapOf("message" to "질문"), expected = 401)
        acknowledge = false
        val failed = request("POST", "/api/chat", mapOf("message" to "질문", "barcode" to "9900000000001"), owner.token, 502)
        assertEquals("AI_ANALYSIS_CONTRACT_MISMATCH", failed["code"].asText())
    }

    @Test @Order(4) fun `legacy allergies query cannot substitute for owned family selection`() {
        val token = register().token // Owner has milk, not soy allergy.
        val legacy = request("GET", "/api/products/9900000000004?allergies=soy", token = token)
        assertEquals("PASS", legacy.at("/data/analysis/status").asText())
        val family = request("POST", "/api/users/me/family-profiles", mapOf("nickname" to "대두가족", "allergies" to "soy"), token, 201)
        val selected = request("GET", "/api/products/9900000000004?analysisMode=selected&familyProfileIds=${family.at("/data/id").asLong()}", token = token)
        assertEquals("DANGER", selected.at("/data/analysis/status").asText())
    }

    @Test @Order(5) fun `internal ID lookup shares analysis and maintenance endpoints reject non admins`() {
        val session = register()
        jdbc.update("UPDATE products SET product_id=90001 WHERE barcode='9900000000001'")
        val byId = request("GET", "/api/products/id/90001", token = session.token)
        assertEquals("9900000000001", byId.at("/data/product/barcode").asText())
        assertEquals(90001L, byId.at("/data/product/productId").asLong())
        request("GET", "/api/products/id/90001/variants", token = session.token)
        // Only fixture 0003 has a precomputed neighbor set; an ID does not invent one.
        request("GET", "/api/recommendations/products/id/90001", token = session.token, expected = 404)
        jdbc.update("UPDATE products SET product_id=90003 WHERE barcode='9900000000003'")
        val alternative = request("GET", "/api/recommendations/products/id/90003", token = session.token)
        assertEquals(90003L, alternative.at("/data/referenceProduct/productId").asLong())
        request("GET", "/api/products/id/0", expected = 400)
        request("GET", "/api/products/id/90002", expected = 404)
        request("POST", "/api/admin/catalog/ids/backfill", expected = 401)
        request("POST", "/api/admin/catalog/ids/backfill", token = session.token, expected = 403)
        request("POST", "/api/admin/catalog/attributes/capture", mapOf("datasetVersion" to "v1", "reason" to "test"), session.token, 403)
        request("GET", "/api/admin/catalog/products/90001/attribute-history", token = session.token, expected = 403)
        val event = request("POST", "/api/histories/events", mapOf("productId" to 90001, "actionType" to "FAVORITE"), session.token)
        assertEquals(90001L, event.at("/data/productId").asLong())
    }

    companion object {
        private val mapper = JsonMapper.builder().findAndAddModules().build()
        private val samples = linkedMapOf<String, JsonNode>()
        private val httpChecks = mutableListOf<Map<String, Any>>()
        @Volatile private var acknowledge = true
        @Volatile private var lastAiRequest: JsonNode? = null
        private val stub = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
            createContext("/chat") { exchange ->
                lastAiRequest = mapper.readTree(exchange.requestBody.readAllBytes())
                if (acknowledge) for (header in listOf("X-Jjikmuk-Analysis-Contract", "X-Jjikmuk-Analysis-Context")) {
                    exchange.responseHeaders.add(header, exchange.requestHeaders.getFirst(header))
                }
                exchange.responseHeaders.add("Content-Type", "application/json; charset=utf-8")
                val response = """{"answer":"격리 HTTP 계약 테스트 응답"}""".toByteArray(Charsets.UTF_8)
                exchange.sendResponseHeaders(200, response.size.toLong())
                exchange.responseBody.use { it.write(response) }
            }
            start()
        }
        @JvmStatic @DynamicPropertySource fun external(registry: DynamicPropertyRegistry) {
            registry.add("chat.ai.url") { "http://127.0.0.1:${stub.address.port}/chat" }
        }
        @JvmStatic @AfterAll fun close() {
            stub.stop(0)
            // Synthetic product/profile samples only. Never export OTPs, passwords or auth tokens.
            val file = Path.of("build", "integration", "core-flow-samples.json")
            Files.createDirectories(file.parent)
            Files.writeString(file, mapper.writerWithDefaultPrettyPrinter().writeValueAsString(samples))
            Files.writeString(file.resolveSibling("core-http-checks.json"), mapper.writerWithDefaultPrettyPrinter().writeValueAsString(httpChecks))
        }
    }
}
