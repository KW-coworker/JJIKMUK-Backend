package org.jjikmuk.backend.domain.ocr

import com.sun.net.httpserver.HttpServer
import org.jjikmuk.backend.domain.auth.AuthSession
import org.jjikmuk.backend.domain.auth.AuthSessionRepository
import org.jjikmuk.backend.domain.auth.AuthSessionService
import org.jjikmuk.backend.domain.user.AuthProvider
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.config.JwtProvider
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc
import org.springframework.mock.web.MockMultipartFile
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.transaction.annotation.Transactional
import java.net.InetSocketAddress
import java.time.Instant
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

@ActiveProfiles("test")
@SpringBootTest(properties = ["spring.config.import=", "jwt.secret=unit-test-only-jwt-secret-32-characters-long"])
@AutoConfigureMockMvc
@Transactional
class OcrJwtSessionIntegrationTest @Autowired constructor(
    private val mvc: MockMvc,
    private val users: UserRepository,
    private val sessions: AuthSessionRepository,
    private val auth: AuthSessionService,
    private val jwt: JwtProvider
) {
    companion object {
        private val calls = AtomicInteger()
        private val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
            createContext("/ocr") { exchange ->
                calls.incrementAndGet()
                assertEquals("POST", exchange.requestMethod)
                assertNull(exchange.requestHeaders.getFirst("Authorization"))
                assertEquals("public-test-service-token-not-a-real-secret", exchange.requestHeaders.getFirst("X-OCR-Service-Token"))
                exchange.requestBody.use { it.readAllBytes() }
                val body = """{"message":"test","data":{"status":"OK","searchKeyword":"test tea"}}""".toByteArray()
                exchange.responseHeaders.set("Content-Type", "application/json")
                exchange.sendResponseHeaders(200, body.size.toLong())
                exchange.responseBody.use { it.write(body) }
                exchange.close()
            }
            start()
        }

        @JvmStatic @DynamicPropertySource
        fun properties(registry: DynamicPropertyRegistry) {
            registry.add("ocr.proxy.enabled") { true }
            registry.add("ocr.proxy.base-url") { "http://127.0.0.1:${server.address.port}" }
            registry.add("ocr.proxy.service-token") { "public-test-service-token-not-a-real-secret" }
        }

        @JvmStatic @AfterAll fun stopServer() { server.stop(0) }
    }

    private fun user(provider: AuthProvider = AuthProvider.LOCAL, complete: Boolean = true): User {
        val id = UUID.randomUUID().toString()
        return users.saveAndFlush(User(email="$id@example.invalid", nickname=id, password="test-only",
            authProvider=provider, profileCompleted=complete))
    }

    private fun issue(user: User) = auth.issue(user, false, "test").token

    private fun probe(token: String, expected: Int, code: String? = null, path: String = "/api/ocr") {
        val before = calls.get()
        val response = mvc.perform(post(path).header("Authorization", "Bearer $token")).andReturn().response
        assertEquals(expected, response.status)
        if (code != null) assertTrue(response.contentAsString.contains(code))
        assertEquals(before, calls.get(), "Rejected/input-validation probes must not call the OCR server")
        assertFalse(response.contentAsString.contains(token))
    }

    @Test fun `local google and linked completed accounts use the same JWT guard`() {
        for (provider in AuthProvider.entries) probe(issue(user(provider)), 415)
    }

    @Test fun `Google profile completion unlocks OCR with the same access token`() {
        val member = user(AuthProvider.GOOGLE, false)
        val token = issue(member)
        probe(token, 403, "PROFILE_INCOMPLETE")
        probe(token, 403, "PROFILE_INCOMPLETE", "/api/ocr/debug")
        assertEquals(200, mvc.perform(get("/api/users/me").header("Authorization", "Bearer $token")).andReturn().response.status)
        member.profileCompleted = true
        users.saveAndFlush(member)
        probe(token, 415)
    }

    @Test fun `expired JWT is rejected before OCR processing`() {
        val member = user()
        val expired = JwtProvider("unit-test-only-jwt-secret-32-characters-long", -1000)
            .createToken(member.id!!, member.email, member.role.name, member.tokenVersion).token
        probe(expired, 401, "AUTH_TOKEN_EXPIRED")
    }

    @Test fun `logout revokes session bound OCR access`() {
        val member = user()
        val token = issue(member)
        auth.logout(member.id!!, sessions.findAllByUserId(member.id!!).single().id)
        probe(token, 401, "AUTH_TOKEN_INVALID")
        probe(token, 401, "AUTH_TOKEN_INVALID", "/api/ocr/debug")
    }

    @Test fun `refreshed access token reaches OCR and refresh logout revokes it`() {
        val member = user()
        val initial = auth.issue(member, false, "test")
        val renewed = auth.refresh(initial.refreshToken)
        probe(renewed.token, 415)
        auth.logoutByRefresh(renewed.refreshToken)
        probe(renewed.token, 401, "AUTH_TOKEN_INVALID")
    }

    @Test fun `changed token version revokes OCR access`() {
        val member = user()
        val token = issue(member)
        member.invalidateSessions()
        users.saveAndFlush(member)
        probe(token, 401, "AUTH_TOKEN_INVALID")
    }

    @Test fun `deleted account cannot retain OCR access`() {
        val member = user()
        val token = issue(member)
        users.delete(member)
        users.flush()
        probe(token, 401, "AUTH_TOKEN_INVALID")
    }

    @Test fun `missing expired and other account sessions cannot authorize OCR`() {
        val member = user()
        val other = user()
        val expired = sessions.saveAndFlush(AuthSession(userId=member.id!!, tokenVersion=0, expiresAt=Instant.now().minusSeconds(1)))
        val foreign = sessions.saveAndFlush(AuthSession(userId=other.id!!, tokenVersion=0, expiresAt=Instant.now().plusSeconds(300)))
        for (sid in listOf(UUID.randomUUID().toString(), expired.id, foreign.id)) {
            val token = jwt.createToken(member.id!!, member.email, member.role.name, member.tokenVersion, sid).token
            probe(token, 401, "AUTH_TOKEN_INVALID")
        }
    }

    @Test fun `authenticated multipart traverses the full security chain and only one upstream call`() {
        val before = calls.get()
        val token = issue(user())
        val file = MockMultipartFile("image", "scan.jpg", "image/jpeg", byteArrayOf(-1, -40, -1, 0))
        val response = mvc.perform(multipart("/api/ocr").file(file)
            .contentType("multipart/form-data; boundary=test-boundary")
            .header("Authorization", "Bearer $token")).andReturn().response
        assertEquals(200, response.status)
        assertTrue(response.contentAsString.contains("test tea"))
        assertEquals("no-store", response.getHeader("Cache-Control"))
        assertEquals(before+1, calls.get())
    }

    @Test fun `OCR multipart allowance does not raise the profile photo application limit`() {
        val token = issue(user())
        val huge = MockMultipartFile("file", "large.png", "image/png", ByteArray(2*1024*1024+1))
        val response = mvc.perform(multipart("/api/users/me/photo").file(huge)
            .with { it.method="PUT"; it }.header("Authorization", "Bearer $token")).andReturn().response
        assertEquals(413, response.status)
        assertTrue(response.contentAsString.contains("PHOTO_TOO_LARGE"))
    }
}
