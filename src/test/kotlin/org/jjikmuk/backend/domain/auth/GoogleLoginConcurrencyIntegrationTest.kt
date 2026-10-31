package org.jjikmuk.backend.domain.auth

import jakarta.servlet.Filter
import org.jjikmuk.backend.domain.user.AuthProvider
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.RepeatedTest
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.*
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.transaction.PlatformTransactionManager
import org.springframework.transaction.IllegalTransactionStateException
import org.springframework.transaction.support.TransactionSynchronization
import org.springframework.transaction.support.TransactionSynchronizationManager
import org.springframework.transaction.support.TransactionTemplate
import org.springframework.web.context.WebApplicationContext
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.CyclicBarrier
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.test.*

/** Real H2 transactions, inserts, unique constraints and locks. Google transport is replaced, not the DB. */
@SpringBootTest(properties = [
    "spring.datasource.url=jdbc:h2:mem:google-races;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false;LOCK_TIMEOUT=15000",
    "spring.datasource.hikari.transaction-isolation=TRANSACTION_REPEATABLE_READ"
])
@ActiveProfiles("test")
class GoogleLoginConcurrencyIntegrationTest @Autowired constructor(
    private val auth: AuthService,
    private val users: UserRepository,
    private val sessions: AuthSessionRepository,
    private val jdbc: JdbcTemplate,
    private val transactionManager: PlatformTransactionManager,
    private val context: WebApplicationContext
) {
    @MockitoBean private lateinit var google: GoogleIdentityVerifier
    @MockitoSpyBean private lateinit var encoder: BCryptPasswordEncoder
    @MockitoSpyBean private lateinit var transactions: GoogleLoginTransactions
    @Volatile private var beforeInsert: (() -> Unit)? = null
    private val insertTransactions = CopyOnWriteArrayList<Int>()

    @BeforeEach fun setup() {
        // Pause AFTER absence was checked but BEFORE INSERT. This forces the real creation race.
        doAnswer { invocation ->
            val result = invocation.callRealMethod()
            if (invocation.getArgument<CharSequence>(0).toString().matches(Regex("[0-9a-f-]{36}"))) {
                assertTrue(TransactionSynchronizationManager.isActualTransactionActive())
                TransactionSynchronizationManager.registerSynchronization(object : TransactionSynchronization {
                    override fun afterCompletion(status: Int) { insertTransactions.add(status) }
                })
                beforeInsert?.invoke()
            }
            result
        }.`when`(encoder).encode(any(CharSequence::class.java))
    }

    @AfterEach fun cleanup() { beforeInsert = null }

    private fun identity(subject: String = UUID.randomUUID().toString()): GoogleIdentity =
        GoogleIdentity(subject, "${UUID.randomUUID()}@example.com")

    private fun request(identity: GoogleIdentity): GoogleLoginRequest {
        val token = UUID.randomUUID().toString()
        `when`(google.verify(token)).thenAnswer {
            // External verification must not run inside either the failed or recovery transaction.
            assertFalse(TransactionSynchronizationManager.isActualTransactionActive())
            identity
        }
        return GoogleLoginRequest(token)
    }

    @RepeatedTest(3)
    fun `same Google user simultaneous first login creates one account and both requests succeed`() {
        val identity = identity()
        assertRace(identity, identity)
    }

    @Test fun `same Google subject with different emails recovers by subject not by email`() {
        val first = identity()
        assertRace(first, identity(first.subject))
    }

    @Test fun `concurrent HTTP requests recover through MVC and return two successful responses`() {
        val identity = identity()
        val requests = listOf(request(identity), request(identity))
        val barrier = CyclicBarrier(2)
        beforeInsert = { barrier.await(10, TimeUnit.SECONDS) }
        val mvc = MockMvcBuilders.webAppContextSetup(context)
            .addFilters<org.springframework.test.web.servlet.setup.DefaultMockMvcBuilder>(context.getBean("springSecurityFilterChain", Filter::class.java))
            .build()
        val executor = Executors.newFixedThreadPool(2)
        try {
            val responses = requests.map { req -> executor.submit<Map<*, *>> {
                val response = mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON)
                    .content(GoogleSignedTokenFixtures.json.toString(mapOf("idToken" to req.idToken))))
                    .andReturn().response
                assertEquals(200, response.status)
                GoogleSignedTokenFixtures.json.fromString(response.contentAsString, Map::class.java)
            } }.map { it.get(20, TimeUnit.SECONDS) }
            assertEquals(1, responses.count { it["isNewUser"] == true })
            assertEquals(1, responses.map { it["userId"] }.distinct().size)
            assertTrue(responses.all { it["profileCompleted"] == false && it["token"] is String })
            val userId = users.findByGoogleSubject(identity.subject)!!.id!!
            assertEquals(2, sessions.findAllByUserId(userId).size)
            assertEquals(1, insertTransactions.count { it == TransactionSynchronization.STATUS_ROLLED_BACK })
            verify(transactions).recoverExisting(identity)
        } finally {
            beforeInsert = null
            executor.shutdownNow()
            executor.awaitTermination(5, TimeUnit.SECONDS)
        }
    }

    private fun assertRace(first: GoogleIdentity, second: GoogleIdentity) {
        val barrier = CyclicBarrier(2)
        beforeInsert = { barrier.await(10, TimeUnit.SECONDS) }
        val requests = listOf(request(first), request(second))
        val executor = Executors.newFixedThreadPool(2)
        try {
            val results = requests.map { req -> executor.submit<AuthResponse> { assertIs<AuthResponse>(auth.googleLogin(req)) } }
                .map { it.get(20, TimeUnit.SECONDS) }
            assertEquals(1, results.count { it.isNewUser })
            assertEquals(1, results.map { it.userId }.distinct().size)
            assertTrue(results.all { !it.profileCompleted })
            val userId = users.findByGoogleSubject(first.subject)!!.id!!
            assertEquals(userId, results.first().userId)
            assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM users WHERE google_subject = ?", Int::class.java, first.subject))
            assertEquals(2, sessions.findAllByUserId(userId).size)
            assertEquals(2, jdbc.queryForObject("SELECT COUNT(*) FROM refresh_credentials r JOIN auth_sessions s ON r.session_id=s.id WHERE s.user_id=?", Int::class.java, userId))
            assertEquals(1, insertTransactions.count { it == TransactionSynchronization.STATUS_ROLLED_BACK })
            assertEquals(1, insertTransactions.count { it == TransactionSynchronization.STATUS_COMMITTED })
            val recoveries = mockingDetails(transactions).invocations.count { it.method.name == "recoverExisting" }
            assertEquals(1, recoveries)
            requests.forEach { verify(google).verify(it.idToken) }
        } finally {
            beforeInsert = null
            executor.shutdownNow()
            executor.awaitTermination(5, TimeUnit.SECONDS)
        }
    }

    @Test fun `LOCAL account winning creation race still needs explicit linking and creates no login session`() {
        val identity = identity()
        val result = withWinningAccount(identity, AuthProvider.LOCAL, null)
        val pending = assertIs<GoogleLinkRequiredResponse>(result)
        assertFalse(pending.loginGranted)
        val saved = users.findByEmail(identity.email)!!
        assertEquals(AuthProvider.LOCAL, saved.authProvider)
        assertNull(saved.googleSubject)
        assertTrue(sessions.findAllByUserId(saved.id!!).isEmpty())
        assertEquals(listOf(TransactionSynchronization.STATUS_ROLLED_BACK), insertTransactions.toList())
        verify(transactions).recoverExisting(identity)
    }

    @Test fun `different Google subject winning same email does not gain login or overwrite identity`() {
        val identity = identity()
        val error = assertIs<CustomException>(withWinningAccount(identity, AuthProvider.GOOGLE, "different-subject-${UUID.randomUUID()}"))
        assertEquals("GOOGLE_TOKEN_INVALID", error.code)
        val saved = users.findByEmail(identity.email)!!
        assertNotEquals(identity.subject, saved.googleSubject)
        assertTrue(sessions.findAllByUserId(saved.id!!).isEmpty())
        assertEquals(listOf(TransactionSynchronization.STATUS_ROLLED_BACK), insertTransactions.toList())
        verify(transactions).recoverExisting(identity)
    }

    private fun withWinningAccount(identity: GoogleIdentity, provider: AuthProvider, googleSubject: String?): Any {
        val entered = CountDownLatch(1)
        val resume = CountDownLatch(1)
        beforeInsert = { entered.countDown(); check(resume.await(10, TimeUnit.SECONDS)) }
        val req = request(identity)
        val executor = Executors.newSingleThreadExecutor()
        try {
            val losing = executor.submit<Any> { try { auth.googleLogin(req) } catch (e: CustomException) { e } }
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            users.saveAndFlush(User(email = identity.email, nickname = "u${UUID.randomUUID().toString().take(8)}",
                password = encoder.encode("Example123!")!!, authProvider = provider,
                googleSubject = googleSubject, profileCompleted = true))
            resume.countDown()
            return losing.get(20, TimeUnit.SECONDS)
        } finally {
            resume.countDown()
            beforeInsert = null
            executor.shutdownNow()
            executor.awaitTermination(5, TimeUnit.SECONDS)
        }
    }

    @Test fun `session storage failure rolls back new account and is not treated as a creation race`() {
        val identity = identity()
        val req = request(identity)
        val lastExistingId = jdbc.queryForObject("SELECT COALESCE(MAX(id), 0) FROM users", Long::class.java)!!
        jdbc.execute("ALTER TABLE auth_sessions ADD CONSTRAINT test_reject_google_session CHECK (user_id <= $lastExistingId)")
        try {
            assertFailsWith<DataIntegrityViolationException> { auth.googleLogin(req) }
            assertNull(users.findByEmail(identity.email))
            assertNull(users.findByGoogleSubject(identity.subject))
            verify(transactions, never()).recoverExisting(identity)
            assertEquals(listOf(TransactionSynchronization.STATUS_ROLLED_BACK), insertTransactions.toList())
        } finally {
            jdbc.execute("ALTER TABLE auth_sessions DROP CONSTRAINT test_reject_google_session")
        }
    }

    @Test fun `caller transaction is rejected before verification instead of suspended with resources held`() {
        val identity = identity()
        val req = request(identity)
        TransactionTemplate(transactionManager).executeWithoutResult { outer ->
            assertTrue(TransactionSynchronizationManager.isActualTransactionActive())
            assertEquals(1, jdbc.queryForObject("SELECT 1", Int::class.java))
            assertFailsWith<IllegalTransactionStateException> { auth.googleLogin(req) }
            assertTrue(TransactionSynchronizationManager.isActualTransactionActive())
            outer.setRollbackOnly()
        }
        assertNull(users.findByGoogleSubject(identity.subject))
        verify(google, never()).verify(req.idToken)
        verifyNoInteractions(transactions)
    }
}
