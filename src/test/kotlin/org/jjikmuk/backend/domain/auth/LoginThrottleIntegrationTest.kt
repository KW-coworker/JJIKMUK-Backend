package org.jjikmuk.backend.domain.auth

import jakarta.servlet.Filter
import org.jjikmuk.backend.domain.user.AuthProvider
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.Mockito.*
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.ResultActions
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import org.springframework.test.web.servlet.setup.DefaultMockMvcBuilder
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.web.context.WebApplicationContext
import java.util.UUID
import java.util.concurrent.Callable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlin.test.assertEquals

/** Real API/security/transactional auth/BCrypt against H2; only time and Google identity are mocked. */
@SpringBootTest(properties = [
    "spring.datasource.url=jdbc:h2:mem:login-throttle;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false",
    "auth.login-throttle.account-limit=5", "auth.login-throttle.ip-limit=8",
    "auth.login-throttle.window-seconds=300"
])
@ActiveProfiles("test")
class LoginThrottleIntegrationTest @Autowired constructor(
    private val context: WebApplicationContext,
    private val users: UserRepository,
    private val sessions: AuthSessionRepository
) {
    @MockitoBean private lateinit var ticker: LoginThrottleTicker
    @MockitoBean private lateinit var google: GoogleIdentityVerifier
    @MockitoSpyBean private lateinit var encoder: BCryptPasswordEncoder
    private val now = AtomicLong()
    private lateinit var mvc: MockMvc

    @BeforeEach fun setup() {
        // Never move the shared limiter's clock backwards; advancing expires the prior test's state.
        now.set(testTime.addAndGet(1_000_000))
        `when`(ticker.millis()).thenAnswer { now.get() }
        mvc = MockMvcBuilders.webAppContextSetup(context)
            .addFilters<DefaultMockMvcBuilder>(context.getBean("springSecurityFilterChain", Filter::class.java))
            .build()
    }

    @Test fun `fifth failed login is 401 and sixth is 429 before BCrypt and session creation`() {
        val user = user()
        clearInvocations(encoder)
        repeat(5) {
            login(user.email, "wrong").andExpect(status().isUnauthorized)
                .andExpect(jsonPath("$.code").value("LOGIN_FAILED"))
        }
        login(user.email, PASSWORD).andExpect(status().isTooManyRequests)
            .andExpect(header().string("Retry-After", "300"))
            .andExpect(jsonPath("$.status").value(429))
            .andExpect(jsonPath("$.code").value("LOGIN_RATE_LIMITED"))
            .andExpect(jsonPath("$.retryAfterSeconds").value(300))
            .andExpect(jsonPath("$.token").doesNotExist())
            .andExpect(jsonPath("$.remainingAttempts").doesNotExist())
        verify(encoder, times(5)).matches(anyString(), anyString())
        assertEquals(0, sessions.findAllByUserId(user.id!!).size)
    }

    @Test fun `account restriction survives rolled-back failures and IP rotation with normalized email`() {
        val user = user()
        repeat(5) { login(user.email, "wrong", "192.0.2.${it + 1}").andExpect(status().isUnauthorized) }
        login("  ${user.email.uppercase()}  ", PASSWORD, "198.51.100.1")
            .andExpect(status().isTooManyRequests)
    }

    @Test fun `nonexistent and malformed email attempts are throttled without exposing account existence`() {
        listOf("${UUID.randomUUID()}@example.com", "invalid email").forEachIndexed { index, email ->
            repeat(5) { login(email, "wrong", "192.0.2.${index + 1}").andExpect(status().isUnauthorized) }
            login(email, "wrong", "198.51.100.${index + 1}").andExpect(status().isTooManyRequests)
                .andExpect(jsonPath("$.code").value("LOGIN_RATE_LIMITED"))
        }
    }

    @Test fun `IP limit applies across accounts and spoofed forwarding headers cannot bypass it`() {
        repeat(8) {
            login("absent$it@example.com", "wrong", headers = mapOf("X-Forwarded-For" to "198.51.100.${it + 1}"))
                .andExpect(status().isUnauthorized)
        }
        login("another@example.com", "wrong", headers = mapOf(
            "X-Forwarded-For" to "203.0.113.1", "Forwarded" to "for=203.0.113.2", "X-Real-IP" to "203.0.113.3"
        )).andExpect(status().isTooManyRequests)
        login("another@example.com", "wrong", "192.0.2.2").andExpect(status().isUnauthorized)
    }

    @Test fun `successful login counts and does not clear either quota`() {
        val user = user()
        repeat(4) { login(user.email, "wrong").andExpect(status().isUnauthorized) }
        login(user.email, PASSWORD).andExpect(status().isOk)
            .andExpect(jsonPath("$.token").isString).andExpect(jsonPath("$.refreshToken").isString)
        login(user.email, PASSWORD, "192.0.2.2").andExpect(status().isTooManyRequests)
        repeat(3) { login("absent$it@example.com", "wrong").andExpect(status().isUnauthorized) }
        login("last@example.com", "wrong").andExpect(status().isTooManyRequests)
        assertEquals(1, sessions.findAllByUserId(user.id!!).size)
    }

    @Test fun `server retry countdown rounds up and expires without extending on rejected requests`() {
        val user = user()
        repeat(5) { login(user.email, "wrong").andExpect(status().isUnauthorized) }
        now.addAndGet(299_001)
        login(user.email, PASSWORD).andExpect(status().isTooManyRequests)
            .andExpect(header().string("Retry-After", "1")).andExpect(jsonPath("$.retryAfterSeconds").value(1))
        now.addAndGet(999)
        login(user.email, PASSWORD).andExpect(status().isOk)
        assertEquals(1, sessions.findAllByUserId(user.id!!).size)
    }

    @Test fun `Google-only password login retains 409 but still consumes attempts`() {
        val user = user(AuthProvider.GOOGLE)
        repeat(5) { login(user.email, PASSWORD).andExpect(status().isConflict)
            .andExpect(jsonPath("$.code").value("AUTH_METHOD_NOT_SUPPORTED")) }
        login(user.email, PASSWORD).andExpect(status().isTooManyRequests)
    }

    @Test fun `stale bearer does not block credential login but does not bypass throttle`() {
        val user = user()
        val headers = mapOf("Authorization" to "Bearer old-invalid-token")
        login(user.email, PASSWORD, headers = headers).andExpect(status().isOk)
        repeat(4) { login(user.email, "wrong", headers = headers).andExpect(status().isUnauthorized) }
        login(user.email, PASSWORD, headers = headers).andExpect(status().isTooManyRequests)
    }

    @Test fun `password throttle does not block refresh logout or Google login`() {
        val user = user()
        val response = login(user.email, PASSWORD).andExpect(status().isOk).andReturn().response.contentAsString
        val refresh = GoogleSignedTokenFixtures.json.fromString(response, Map::class.java)["refreshToken"] as String
        repeat(4) { login(user.email, "wrong").andExpect(status().isUnauthorized) }
        login(user.email, PASSWORD).andExpect(status().isTooManyRequests)
        mvc.perform(post("/api/auth/refresh").contentType(MediaType.APPLICATION_JSON)
            .content(json(mapOf("refreshToken" to refresh)))).andExpect(status().isOk)
        mvc.perform(post("/api/auth/logout/refresh").contentType(MediaType.APPLICATION_JSON)
            .content(json(mapOf("refreshToken" to refresh)))).andExpect(status().isOk)
        val identity = UUID.randomUUID().toString()
        `when`(google.verify("test-google-token")).thenReturn(GoogleIdentity(identity, "$identity@example.com"))
        mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON)
            .content(json(mapOf("idToken" to "test-google-token")))).andExpect(status().isOk)
    }

    @Test fun `concurrent HTTP attempts issue no more sessions than account quota`() {
        val user = user()
        val executor = Executors.newFixedThreadPool(10)
        val start = CountDownLatch(1)
        try {
            val results = (0 until 10).map { index -> executor.submit(Callable {
                check(start.await(5, TimeUnit.SECONDS))
                login(user.email, PASSWORD, "192.0.2.${index + 1}").andReturn().response.status
            }) }
            start.countDown()
            val statuses = results.map { it.get(20, TimeUnit.SECONDS) }
            assertEquals(5, statuses.count { it == 200 })
            assertEquals(5, statuses.count { it == 429 })
            assertEquals(5, sessions.findAllByUserId(user.id!!).size)
        } finally { executor.shutdownNow() }
    }

    private fun user(provider: AuthProvider = AuthProvider.LOCAL): User {
        val id = UUID.randomUUID().toString().replace("-", "")
        return users.saveAndFlush(User(email = "$id@example.com", nickname = "u${id.take(12)}",
            password = encoder.encode(PASSWORD)!!, profileCompleted = true, authProvider = provider))
    }

    private fun login(email: String, password: String, ip: String = "192.0.2.1", headers: Map<String, String> = emptyMap()): ResultActions {
        val request = post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
            .content(json(mapOf("email" to email, "password" to password)))
            .with { it.remoteAddr = ip; it }
        headers.forEach { (name, value) -> request.header(name, value) }
        return mvc.perform(request)
    }
    private fun json(value: Any): String = GoogleSignedTokenFixtures.json.toString(value)

    companion object {
        private const val PASSWORD = "Example123!"
        private val testTime = AtomicLong()
    }
}
