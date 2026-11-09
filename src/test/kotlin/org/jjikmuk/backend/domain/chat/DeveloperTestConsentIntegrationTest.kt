package org.jjikmuk.backend.domain.chat

import com.sun.net.httpserver.HttpServer
import org.jjikmuk.backend.domain.auth.AuthSessionService
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
import java.security.MessageDigest
import java.util.HexFormat
import java.util.UUID
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.test.*

@SpringBootTest(properties = ["spring.config.import=", "chatbot.developer-test-auto-consent=true",
    "spring.datasource.url=jdbc:h2:mem:developer-consent;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@AutoConfigureMockMvc
@ActiveProfiles("test")
class DeveloperTestConsentIntegrationTest @Autowired constructor(
    private val mvc: MockMvc, private val users: UserRepository, private val auth: AuthSessionService
) {
    @Test fun `approved test flag grants omitted false and true requests for multiple authenticated owners`() {
        for (index in 1..2) {
            val owner = users.saveAndFlush(User(email="${UUID.randomUUID()}@example.invalid", nickname="test-${UUID.randomUUID().toString().take(8)}", password="test-only"))
            val token = auth.issue(owner, false, "test").token
            for (consent in listOf("omitted", "null", "false", "true")) {
                val payload = linkedMapOf<String, Any?>("message" to "합성 시험", "profiles" to emptyList<Any>(), "chatHistory" to emptyList<Any>())
                if (consent != "omitted") payload["externalAiConsent"] = when (consent) {
                    "null" -> null
                    "true" -> true
                    else -> false
                }
                val before = captures.size
                val response = mvc.perform(post("/api/chat").header("Authorization", "Bearer $token")
                    .contentType("application/json").content(mapper.writeValueAsBytes(payload))).andReturn().response
                assertEquals(200, response.status)
                assertEquals(before + 1, captures.size)
                val (headers, bytes) = captures.last()
                assertEquals(owner.id.toString(), headers["X-food-chatbot-user-id"])
                assertEquals("granted", headers["X-food-chatbot-external-ai-consent"])
                assertEquals("public-internal-test-token", headers["X-food-chatbot-token"])
                val hex = HexFormat.of()
                val canonical = listOf("v1", headers.getValue("X-food-chatbot-external-ai-timestamp"), "POST", "/chat",
                    owner.id.toString(), "granted", headers.getValue("X-food-chatbot-external-ai-nonce"),
                    hex.formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))).joinToString("\n")
                val mac = Mac.getInstance("HmacSHA256")
                mac.init(SecretKeySpec("public-consent-test-secret-not-production".toByteArray(), "HmacSHA256"))
                assertEquals(hex.formatHex(mac.doFinal(canonical.toByteArray())), headers["X-food-chatbot-external-ai-signature"])
                val body = mapper.readTree(bytes)
                assertEquals(0, body["chat_history"].size())
                assertFalse(body.has("externalAiConsent"))
                assertEquals("chat-analysis-v2", body.at("/analysisContext/contractVersion").asText())
            }
        }
    }

    @Test fun `test flag never grants anonymous forged-owner or invalid requests access`() {
        val owner = users.saveAndFlush(User(email="${UUID.randomUUID()}@example.invalid", nickname="test-${UUID.randomUUID().toString().take(8)}", password="test-only"))
        val token = auth.issue(owner, false, "test").token
        val before = captures.size
        assertEquals(401, mvc.perform(post("/api/chat").contentType("application/json")
            .content("""{"message":"test"}""")).andReturn().response.status)
        for ((body, expected) in listOf(
            """{"message":"test","userId":999999999}""" to 403,
            """{"message":"test","externalAiConsent":"true"}""" to 400,
            """{"message":"test","externalAiConsent":1}""" to 400,
            """{"message":"test","analysisContext":{}}""" to 400
        )) {
            assertEquals(expected, mvc.perform(post("/api/chat").header("Authorization", "Bearer $token")
                .contentType("application/json").content(body)).andReturn().response.status)
        }
        assertEquals(before, captures.size)
    }

    companion object {
        private val mapper = JsonMapper.builder().findAndAddModules().build()
        private val captures = mutableListOf<Pair<Map<String, String>, ByteArray>>()
        private val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
            createContext("/chat") { exchange ->
                captures += exchange.requestHeaders.mapValues { it.value.single() } to exchange.requestBody.readAllBytes()
                for (header in listOf(AiChatClient.CONTRACT_HEADER, AiChatClient.CONTEXT_HEADER))
                    exchange.responseHeaders.set(header, exchange.requestHeaders.getFirst(header))
                exchange.responseHeaders.set("Content-Type", "application/json")
                val body = """{"answer":"synthetic"}""".toByteArray()
                exchange.sendResponseHeaders(200, body.size.toLong())
                exchange.responseBody.use { it.write(body) }; exchange.close()
            }; start()
        }
        @JvmStatic @DynamicPropertySource fun properties(registry: DynamicPropertyRegistry) {
            registry.add("chat.ai.url") { "http://127.0.0.1:${server.address.port}/chat" }
        }
        @JvmStatic @AfterAll fun close() { server.stop(0) }
    }
}
