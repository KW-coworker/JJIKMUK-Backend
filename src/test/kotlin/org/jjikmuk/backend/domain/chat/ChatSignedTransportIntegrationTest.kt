package org.jjikmuk.backend.domain.chat

import com.sun.net.httpserver.HttpServer
import org.jjikmuk.backend.domain.auth.AuthSessionService
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import tools.jackson.databind.json.JsonMapper
import java.net.InetSocketAddress
import java.nio.file.Files
import java.nio.file.Path
import java.util.Base64
import java.util.UUID
import kotlin.test.*

/** Real JWT -> profile resolution + H2 policy -> exact signed HTTP bytes. Synthetic data only. */
@SpringBootTest(properties = ["spring.config.import=",
    "spring.datasource.url=jdbc:h2:mem:signed-chat;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ChatSignedTransportIntegrationTest @Autowired constructor(
    private val mvc: MockMvc, private val users: UserRepository,
    private val auth: AuthSessionService, private val products: ProductRepository
) {
    @Test fun `selected snapshots preserve decisions while proof binds JWT owner and explicit consent`() {
        val member = users.saveAndFlush(User(email="${UUID.randomUUID()}@example.invalid", nickname="owner", password="test-only"))
        val token = auth.issue(member, false, "test").token
        val product = products.saveAndFlush(Product(barcode="synthetic-${UUID.randomUUID()}", productName="합성 우유 과자",
            rawMaterials="우유, 쌀", allergyEvidenceLevel=AllergyEvidenceLevel.DECLARED_LABEL))
        for ((name, count, consent) in listOf(Triple("multi-on",2,true), Triple("single-off",1,false),
            Triple("none-omitted",0,null), Triple("max21-on",21,true), Triple("null-denied",2,null))) {
            val selected = (0 until count).map { index -> mapOf("id" to 777, "nickname" to "같은 이름",
                "allergies" to if (index == 0) "milk" else "soy") }
            val request = linkedMapOf<String, Any?>("message" to "이 제품 먹어도 돼?", "barcode" to product.barcode,
                "profiles" to selected)
            if (consent != null || name == "null-denied") request["externalAiConsent"] = consent
            val before = captures.size
            val response = mvc.perform(post("/api/chat").header("Authorization","Bearer $token")
                .header("X-Food-Chatbot-User-Id","999999").header("X-Food-Chatbot-External-AI-Consent","granted")
                .contentType("application/json").content(mapper.writeValueAsBytes(request))).andReturn().response
            assertEquals(200, response.status)
            assertEquals(before+1,captures.size)
            val captured = captures.last()
            val headers = captured["headers"] as Map<*, *>
            assertEquals(member.id.toString(), headers["X-food-chatbot-user-id"])
            assertEquals(if(consent == true) "granted" else "denied", headers["X-food-chatbot-external-ai-consent"])
            assertNull(headers["Authorization"])
            val payload = mapper.readTree(Base64.getDecoder().decode(captured["bodyBase64"] as String))
            assertFalse(payload.has("externalAiConsent"))
            assertEquals(count, payload.at("/analysisContext/profileAnalyses").size())
            if (count > 0) assertEquals("DANGER", payload.at("/analysisContext/profileAnalyses/0/analysis/status").asText())
            captured["case"] = name
            captured["ownerId"] = member.id!!
        }
        val before = captures.size
        val invalidBodies = listOf("""{"message":"질문","externalAiConsent":"true"}""",
            """{"message":"질문","externalAiConsent":1}""", """{"message":"질문","userId":999999}""")
        for (body in invalidBodies) {
            assertTrue(mvc.perform(post("/api/chat").header("Authorization","Bearer $token")
                .contentType("application/json").content(body)).andReturn().response.status in listOf(400,403))
        }
        assertEquals(401,mvc.perform(post("/api/chat").contentType("application/json")
            .content("""{"message":"질문","externalAiConsent":true}""")).andReturn().response.status)
        assertEquals(before,captures.size)
    }

    @Test fun `source evidence uses existing chat vocabulary without changing verdict confidence or proof bytes`() {
        val member = users.saveAndFlush(User(email="${UUID.randomUUID()}@example.invalid", nickname="source-owner", password="test-only"))
        val token = auth.issue(member, false, "test").token
        data class Case(val name: String, val materials: String, val allergies: String, val count: Int, val confidence: Double?, val expected: String)
        for (case in listOf(
            Case("source-null", "쌀", "milk", 1, null, "UNKNOWN"),
            Case("source-zero", "쌀", "milk", 1, 0.0, "UNKNOWN"),
            Case("source-one", "쌀", "milk", 1, 1.0, "UNKNOWN"),
            Case("source-danger", "쌀, 우유", "milk", 1, 0.42, "DANGER"),
            Case("source-pass", "쌀", "", 1, 0.42, "PASS"),
            Case("source-none", "쌀", "milk", 0, 0.42, "NOT_EVALUATED"),
            Case("source-multi", "쌀", "milk", 2, 0.42, "UNKNOWN"),
            Case("source-max21", "쌀", "milk", 21, 0.42, "UNKNOWN")
        )) {
            val product = products.saveAndFlush(Product(barcode="source-${UUID.randomUUID()}", productName="합성 원자료 상품",
                rawMaterials=case.materials, allergyEvidenceLevel=AllergyEvidenceLevel.SOURCE_INGREDIENTS,
                allergyDataConfidence=case.confidence))
            val request = mapOf("message" to "이 제품 정보를 확인해 줘", "barcode" to product.barcode,
                "profiles" to (0 until case.count).map { mapOf("nickname" to "합성 프로필 $it", "allergies" to case.allergies) },
                "externalAiConsent" to false)
            val response = mvc.perform(post("/api/chat").header("Authorization", "Bearer $token")
                .contentType("application/json").content(mapper.writeValueAsBytes(request))).andReturn().response
            assertEquals(200, response.status)
            val capture = captures.last()
            val payload = mapper.readTree(Base64.getDecoder().decode(capture["bodyBase64"] as String))
            val context = payload.get("analysisContext")
            assertEquals("UNKNOWN", context.at("/analysis/evidenceLevel").asText())
            assertEquals(case.expected, context.at("/analysis/status").asText())
            assertEquals("UNKNOWN", context.at("/dataEvidence/allergyEvidenceLevel").asText())
            if (case.confidence == null) assertTrue(context.at("/dataEvidence/allergyConfidence").isNull)
            else assertEquals(case.confidence, context.at("/dataEvidence/allergyConfidence").asDouble())
            assertEquals(case.count, context.get("profileAnalyses").size())
            for (profile in context.get("profileAnalyses")) {
                assertEquals("UNKNOWN", profile.at("/analysis/evidenceLevel").asText())
                assertEquals(case.expected, profile.at("/analysis/status").asText())
            }
            assertEquals(AllergyEvidenceLevel.SOURCE_INGREDIENTS, products.findById(product.barcode).orElseThrow().allergyEvidenceLevel)
            capture["case"] = case.name
            capture["ownerId"] = member.id!!
        }
    }

    companion object {
        private val mapper = JsonMapper.builder().findAndAddModules().build()
        private val captures = mutableListOf<MutableMap<String, Any>>()
        private val server = HttpServer.create(InetSocketAddress("127.0.0.1",0),0).apply {
            createContext("/chat") { exchange ->
                val bytes = exchange.requestBody.readAllBytes()
                val headers = exchange.requestHeaders.mapValues { it.value.single() }
                captures += linkedMapOf("bodyBase64" to Base64.getEncoder().encodeToString(bytes), "headers" to headers)
                for (header in listOf(AiChatClient.CONTRACT_HEADER,AiChatClient.CONTEXT_HEADER))
                    exchange.responseHeaders.set(header,exchange.requestHeaders.getFirst(header))
                exchange.responseHeaders.set("Content-Type","application/json")
                val body = """{"answer":"synthetic","per_profile_results":[{"preserved":true}]}""".toByteArray()
                exchange.sendResponseHeaders(200,body.size.toLong())
                exchange.responseBody.use { it.write(body) }; exchange.close()
            }; start()
        }
        @JvmStatic @DynamicPropertySource fun properties(registry: DynamicPropertyRegistry) {
            registry.add("chat.ai.url") { "http://127.0.0.1:${server.address.port}/chat" }
        }
        @JvmStatic @AfterAll fun close() {
            server.stop(0)
            val file=Path.of("build/integration/signed-chat-requests.json")
            Files.createDirectories(file.parent)
            Files.writeString(file,mapper.writerWithDefaultPrettyPrinter().writeValueAsString(captures))
        }
    }
}
