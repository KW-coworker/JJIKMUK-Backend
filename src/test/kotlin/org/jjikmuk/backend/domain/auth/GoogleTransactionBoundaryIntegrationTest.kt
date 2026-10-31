package org.jjikmuk.backend.domain.auth

import com.google.api.client.googleapis.auth.oauth2.GooglePublicKeysManager
import com.zaxxer.hikari.HikariDataSource
import jakarta.servlet.Filter
import org.jjikmuk.backend.domain.user.AuthProvider
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource
import org.mockito.ArgumentMatchers.*
import org.mockito.Mockito.*
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import org.springframework.test.web.servlet.setup.DefaultMockMvcBuilder
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.transaction.IllegalTransactionStateException
import org.springframework.transaction.PlatformTransactionManager
import org.springframework.transaction.support.TransactionSynchronizationManager
import org.springframework.transaction.support.TransactionTemplate
import org.springframework.web.context.WebApplicationContext
import java.io.IOException
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import javax.sql.DataSource
import kotlin.test.*

/**
 * Real GoogleIdTokenVerifier/RSA, Spring transaction proxies, MVC/security and H2.
 * Stub only the public-key source to simulate Google delay/outage, never contact Google/AWS/MySQL.
 * One DB connection makes a leaked transaction observable while verification is blocked.
 */
@SpringBootTest(properties = [
    "spring.datasource.url=jdbc:h2:mem:google-boundary;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false",
    "spring.datasource.hikari.maximum-pool-size=1", "spring.datasource.hikari.minimum-idle=1",
    "spring.datasource.hikari.connection-timeout=1000",
    "google.client-id=unit-test-web.apps.googleusercontent.com"
])
@ActiveProfiles("test")
class GoogleTransactionBoundaryIntegrationTest @Autowired constructor(
    private val context: WebApplicationContext,
    private val auth: AuthService,
    private val verifier: GoogleIdentityVerifier,
    private val users: UserRepository,
    private val sessions: AuthSessionRepository,
    private val credentials: RefreshCredentialRepository,
    private val grants: GoogleLinkGrantRepository,
    private val encoder: BCryptPasswordEncoder,
    private val jdbc: JdbcTemplate,
    private val manager: PlatformTransactionManager,
    dataSource: DataSource
) {
    @MockitoBean private lateinit var keys: GooglePublicKeysManager
    @MockitoSpyBean private lateinit var transactions: GoogleLoginTransactions
    @MockitoSpyBean private lateinit var sessionService: AuthSessionService
    private val pool = dataSource.unwrap(HikariDataSource::class.java)
    private lateinit var mvc: MockMvc
    private val keyCalls = AtomicInteger()
    private val googleSessionWrites = AtomicInteger()
    @Volatile private var duringKeyFetch: (() -> Unit)? = null
    @Volatile private var afterSessionWrite: (() -> Unit)? = null

    @BeforeEach fun setup() {
        `when`(keys.jsonFactory).thenReturn(GoogleSignedTokenFixtures.json)
        `when`(keys.publicKeys).thenAnswer {
            assertFalse(TransactionSynchronizationManager.isActualTransactionActive(), "key fetch inside a DB transaction")
            assertEquals(0, activeConnections(), "key fetch retained a DB connection")
            keyCalls.incrementAndGet()
            duringKeyFetch?.invoke()
            listOf(GoogleSignedTokenFixtures.keys.public)
        }
        doAnswer { invocation ->
            val user = invocation.getArgument<User>(0)
            if (user.authProvider == AuthProvider.GOOGLE) {
                assertTrue(keyCalls.get() > 0, "DB phase ran before identity verification")
                assertTrue(TransactionSynchronizationManager.isActualTransactionActive())
                assertEquals(1, activeConnections())
                googleSessionWrites.incrementAndGet()
            }
            val result = invocation.callRealMethod()
            afterSessionWrite?.invoke()
            result
        }.`when`(sessionService).issue(
            any(User::class.java) ?: User(email = "matcher@example.com", password = "", nickname = "matcher"),
            anyBoolean(), anyString()
        )
        mvc = MockMvcBuilders.webAppContextSetup(context)
            .addFilters<DefaultMockMvcBuilder>(context.getBean("springSecurityFilterChain", Filter::class.java))
            .build()
    }

    @Test fun `new and existing Google logins verify outside DB and persist sessions inside DB`() {
        val token = token()
        val first = mvc.perform(googleRequest(token)).andExpect(status().isOk)
            .andExpect(jsonPath("$.isNewUser").value(true)).andReturn().response.contentAsString
        val id = (GoogleSignedTokenFixtures.json.fromString(first, Map::class.java)["userId"] as Number).toLong()
        mvc.perform(googleRequest(token)).andExpect(status().isOk)
            .andExpect(jsonPath("$.userId").value(id)).andExpect(jsonPath("$.isNewUser").value(false))
        assertEquals(2, keyCalls.get())
        assertEquals(2, googleSessionWrites.get())
        assertEquals(2, sessions.findAllByUserId(id).size)
        assertFalse(TransactionSynchronizationManager.isActualTransactionActive())
        assertEquals(0, activeConnections())
    }

    @Test fun `slow Google verification leaves the only DB connection available for password login`() {
        val local = localUser()
        val entered = CountDownLatch(1)
        val resume = CountDownLatch(1)
        duringKeyFetch = { entered.countDown(); check(resume.await(15, TimeUnit.SECONDS)) }
        val executor = Executors.newFixedThreadPool(2)
        try {
            val pending = executor.submit<Int> { mvc.perform(googleRequest(token())).andReturn().response.status }
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            assertEquals(0, activeConnections())
            verifyNoInteractions(transactions)
            val passwordLogin = executor.submit<Int> {
                mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                    .content(json(mapOf("email" to local.email, "password" to "Example123!"))))
                    .andReturn().response.status
            }
            assertEquals(200, passwordLogin.get(5, TimeUnit.SECONDS))
            assertFalse(pending.isDone, "Google response was not held until the DB probe completed")
            assertEquals(0, activeConnections())
            resume.countDown()
            assertEquals(200, pending.get(10, TimeUnit.SECONDS))
            assertEquals(1, googleSessionWrites.get())
        } finally {
            resume.countDown()
            executor.shutdownNow()
            executor.awaitTermination(5, TimeUnit.SECONDS)
        }
    }

    @Test fun `Google key outage returns 503 without starting persistence or modifying auth records`() {
        val before = counts()
        duringKeyFetch = { throw IOException("isolated public-key outage") }
        mvc.perform(googleRequest(token())).andExpect(status().isServiceUnavailable)
            .andExpect(jsonPath("$.code").value("GOOGLE_LOGIN_UNAVAILABLE"))
            .andExpect(jsonPath("$.token").doesNotExist())
        verifyNoInteractions(transactions)
        assertEquals(0, googleSessionWrites.get())
        assertEquals(before, counts())
        assertEquals(0, activeConnections())
    }

    @Test fun `malformed token returns 401 before key lookup and any DB phase`() {
        val before = counts()
        mvc.perform(googleRequest("malformed-google-token")).andExpect(status().isUnauthorized)
            .andExpect(jsonPath("$.code").value("GOOGLE_TOKEN_INVALID"))
        assertEquals(0, keyCalls.get())
        verifyNoInteractions(transactions)
        assertEquals(before, counts())
    }

    @Test fun `forged signature returns 401 after key lookup but before any DB phase`() {
        val before = counts()
        mvc.perform(googleRequest(GoogleSignedTokenFixtures.token(key = GoogleSignedTokenFixtures.otherKeys.private)))
            .andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("GOOGLE_TOKEN_INVALID"))
        assertEquals(1, keyCalls.get())
        verifyNoInteractions(transactions)
        assertEquals(before, counts())
    }

    @ParameterizedTest
    @ValueSource(booleans = [false, true])
    fun `direct verifier invocation rejects an existing write or read-only transaction before IO`(readOnly: Boolean) {
        TransactionTemplate(manager).apply { isReadOnly = readOnly }.executeWithoutResult {
            assertEquals(1, jdbc.queryForObject("SELECT 1", Int::class.java))
            assertEquals(1, activeConnections())
            assertFailsWith<IllegalTransactionStateException> { verifier.verify(token()) }
            assertTrue(TransactionSynchronizationManager.isActualTransactionActive())
        }
        assertEquals(0, keyCalls.get())
        verify(keys, never()).publicKeys
        verifyNoInteractions(transactions)
        assertEquals(0, activeConnections())
    }

    @Test fun `DB failure after session write rolls back account session and refresh together`() {
        val before = counts()
        afterSessionWrite = { throw IllegalStateException("isolated failure after session persistence") }
        assertFailsWith<IllegalStateException> { auth.googleLogin(GoogleLoginRequest(token())) }
        assertEquals(1, keyCalls.get())
        assertEquals(1, googleSessionWrites.get())
        assertEquals(before, counts())
        assertEquals(0, activeConnections())
    }

    @Test fun `same email LOCAL account still requires explicit linking after verification`() {
        val local = localUser()
        val sessionsBefore = sessions.count()
        val grantsBefore = grants.count()
        mvc.perform(googleRequest(token(local.email))).andExpect(status().isOk)
            .andExpect(jsonPath("$.code").value("GOOGLE_LINK_REQUIRED"))
            .andExpect(jsonPath("$.loginGranted").value(false)).andExpect(jsonPath("$.token").doesNotExist())
        assertEquals(1, keyCalls.get())
        assertEquals(0, googleSessionWrites.get())
        assertEquals(sessionsBefore, sessions.count())
        assertEquals(grantsBefore + 1, grants.count())
        assertNull(users.findById(local.id!!).orElseThrow().googleSubject)
        assertEquals(0, activeConnections())
    }

    private fun activeConnections() = pool.hikariPoolMXBean.activeConnections
    private fun counts() = listOf(users.count(), sessions.count(), credentials.count(), grants.count())
    private fun token(email: String = "${UUID.randomUUID()}@example.com") =
        GoogleSignedTokenFixtures.token(mapOf("sub" to UUID.randomUUID().toString(), "email" to email))
    private fun json(value: Any) = GoogleSignedTokenFixtures.json.toString(value)
    private fun googleRequest(token: String) = post("/api/auth/google")
        .header("Authorization", "Bearer ignored-stale-access-token")
        .contentType(MediaType.APPLICATION_JSON).content(json(mapOf("idToken" to token)))
    private fun localUser(): User {
        val unique = UUID.randomUUID().toString().replace("-", "")
        return users.saveAndFlush(User(email = "$unique@example.com", nickname = "u${unique.take(12)}",
            password = encoder.encode("Example123!")!!, profileCompleted = true))
    }
}
