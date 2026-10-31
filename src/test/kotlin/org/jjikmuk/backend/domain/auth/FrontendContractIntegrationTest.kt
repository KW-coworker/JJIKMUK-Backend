package org.jjikmuk.backend.domain.auth

import jakarta.servlet.Filter
import org.jjikmuk.backend.domain.user.*
import org.jjikmuk.backend.domain.product.*
import org.jjikmuk.backend.domain.recommendation.*
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.Mockito.`when`
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.mock.web.MockMultipartFile
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.web.context.WebApplicationContext
import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import java.time.Duration
import java.time.Instant
import java.util.UUID
import javax.imageio.ImageIO
import kotlin.test.*

/** Real transactions and security filter chain; H2 only, no mail/Google/MySQL/network. */
@SpringBootTest(properties = ["spring.datasource.url=jdbc:h2:mem:frontend-contract;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@ActiveProfiles("test")
class FrontendContractIntegrationTest @Autowired constructor(
    private val context: WebApplicationContext,
    private val users: UserRepository,
    private val service: UserService,
    private val auth: AuthService,
    private val sessions: AuthSessionService,
    private val sessionRepository: AuthSessionRepository,
    private val credentials: RefreshCredentialRepository,
    private val grants: GoogleLinkGrantRepository,
    private val encoder: BCryptPasswordEncoder,
    private val families: FamilyProfileService,
    private val familyRepository: FamilyProfileRepository,
    private val photos: ProfilePhotoService,
    private val photoRepository: ProfilePhotoRepository,
    private val selection: AnalysisSelectionService,
    private val products: ProductRepository,
    private val home: SafeProductRecommendationService,
    private val alternatives: RecommendationService,
    private val emailGrants: EmailVerificationGrantRepository,
    private val neighbors: ProductNeighborSetRepository,
    private val jdbc: org.springframework.jdbc.core.JdbcTemplate
) {
    @MockitoBean lateinit var google: GoogleIdentityVerifier
    @Value("\${jwt.secret}") lateinit var jwtSecret: String
    private lateinit var mvc: MockMvc
    @BeforeEach fun setup() {
        mvc = MockMvcBuilders.webAppContextSetup(context)
            .addFilters<org.springframework.test.web.servlet.setup.DefaultMockMvcBuilder>(context.getBean("springSecurityFilterChain", Filter::class.java))
            .build()
        // JDBC-only operational tables are not created by Hibernate in the H2 test profile.
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_feedback (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_logs (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
    }
    private fun user(password: String = "Example123!", allergies: String? = "milk", complete: Boolean = true): User {
        val suffix = UUID.randomUUID().toString().replace("-", "").take(12)
        return users.saveAndFlush(User(email = "$suffix@example.com", nickname = "u$suffix",
            password = encoder.encode(password)!!, allergies = allergies, specialDiet = "lowSugar", profileCompleted = complete))
    }
    private fun login(user: User, password: String = "Example123!") = auth.login(LoginRequest(user.email, password))
    private fun bearer(token: String) = "Bearer $token"
    private fun error(code: String, action: () -> Unit) = assertEquals(code, assertFailsWith<CustomException> { action() }.code)
    private fun png() = ByteArrayOutputStream().also { ImageIO.write(BufferedImage(4, 4, BufferedImage.TYPE_INT_RGB), "png", it) }.toByteArray()

    @Test fun `incomplete Google account is limited until explicit completion then same token works`() {
        val unique = UUID.randomUUID().toString().replace("-", "")
        `when`(google.verify("onboarding")).thenReturn(GoogleIdentity(unique, "$unique@example.com"))
        val issued = assertIs<AuthResponse>(auth.googleLogin(GoogleLoginRequest("onboarding")))
        val account = users.findById(issued.userId).orElseThrow()
        assertFalse(issued.profileCompleted)
        val barcode = "ONBOARD-${account.id}"
        products.saveAndFlush(Product(barcode = barcode, productName = "온보딩 테스트"))
        for (path in listOf("/api/products/$barcode", "/api/products/search?keyword=$barcode",
            "/api/products/filter", "/api/products/safe-recommendations?analysisMode=none",
            "/api/recommendations/products/$barcode", "/api/histories/user/${account.id}",
            "/api/users/me/family-profiles", "/api/users/${account.id}")) {
            mvc.perform(get(path).header("Authorization", bearer(issued.token)))
                .andExpect(status().isForbidden).andExpect(jsonPath("$.code").value("PROFILE_INCOMPLETE"))
        }
        for (path in listOf("/api/chat", "/api/histories/events", "/api/recommendations/feedback")) {
            mvc.perform(post(path).header("Authorization", bearer(issued.token)).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden).andExpect(jsonPath("$.code").value("PROFILE_INCOMPLETE"))
        }
        for (path in listOf("/api/users/me", "/api/users/${account.id}")) {
            mvc.perform(put(path).header("Authorization", bearer(issued.token)).contentType(MediaType.APPLICATION_JSON)
                .content("""{"nickname":"${account.nickname}"}"""))
                .andExpect(status().isForbidden).andExpect(jsonPath("$.code").value("PROFILE_INCOMPLETE"))
        }
        for (path in listOf("/api/users/me", "/api/products/filters", "/api/products/classifications")) {
            mvc.perform(get(path).header("Authorization", bearer(issued.token))).andExpect(status().isOk)
        }
        mvc.perform(patch("/api/users/me").header("Authorization", bearer(issued.token)).contentType(MediaType.APPLICATION_JSON)
            .content("""{"nickname":"${account.nickname}"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.profileCompleted").value(false))
        mvc.perform(post("/api/users/me/profile/complete").header("Authorization", bearer(issued.token))
            .contentType(MediaType.APPLICATION_JSON).content("""{"nickname":"${account.nickname}","allergies":null,"specialDiet":null}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.profileCompleted").value(true))
        mvc.perform(get("/api/products/$barcode").header("Authorization", bearer(issued.token))).andExpect(status().isOk)
    }

    @Test fun `incomplete account can manage own photo and withdraw but not delete another account`() {
        val account = user(complete = false); val other = user(); val issued = login(account)
        mvc.perform(multipart("/api/users/me/photo").file(MockMultipartFile("file", "avatar.png", "image/png", png()))
            .with { it.method = "PUT"; it }.header("Authorization", bearer(issued.token))).andExpect(status().isOk)
        mvc.perform(get("/api/users/me/photo").header("Authorization", bearer(issued.token))).andExpect(status().isOk)
        mvc.perform(delete("/api/users/me/photo").header("Authorization", bearer(issued.token))).andExpect(status().isOk)
        mvc.perform(delete("/api/users/${other.id}").header("Authorization", bearer(issued.token)))
            .andExpect(status().isForbidden).andExpect(jsonPath("$.code").value("PROFILE_INCOMPLETE"))
        mvc.perform(delete("/api/users/${account.id}").header("Authorization", bearer(issued.token))).andExpect(status().isOk)
        assertFalse(users.existsById(account.id!!)); assertTrue(users.existsById(other.id!!))
    }

    @Test fun `incomplete account can refresh and logout without completing profile`() {
        val account = user(complete = false); val issued = login(account)
        mvc.perform(post("/api/auth/refresh").contentType(MediaType.APPLICATION_JSON)
            .content("""{"refreshToken":"${issued.refreshToken}"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.profileCompleted").value(false))
        mvc.perform(post("/api/auth/logout").header("Authorization", bearer(issued.token))).andExpect(status().isOk)
        assertFalse(users.findById(account.id!!).orElseThrow().profileCompleted)
    }

    @Test fun `anonymous catalog access is preserved and invalid or expired access never becomes a profile error`() {
        val account = user(complete = false); val issued = login(account)
        val barcode = "ANON-${account.id}"
        products.saveAndFlush(Product(barcode = barcode, productName = "공개 상품"))
        mvc.perform(get("/api/products/$barcode")).andExpect(status().isOk)
        mvc.perform(get("/api/products/$barcode").header("Authorization", "Bearer invalid"))
            .andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("AUTH_TOKEN_INVALID"))
        val expired = org.jjikmuk.backend.global.config.JwtProvider(jwtSecret, -60000)
            .createToken(account.id!!, account.email, "USER", account.tokenVersion,
                credentials.sessionIdForHash(EmailVerificationSecurity.hashToken(issued.refreshToken))).token
        mvc.perform(get("/api/products/$barcode").header("Authorization", bearer(expired)))
            .andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("AUTH_TOKEN_EXPIRED"))
    }

    @Test fun `refresh logout accepts expired access is idempotent and preserves other sessions and private data`() {
        val account = user(complete = false); val issued = login(account); val otherDevice = login(account)
        val otherAccount = user(); val foreignSession = login(otherAccount)
        val id = credentials.sessionIdForHash(EmailVerificationSecurity.hashToken(issued.refreshToken))!!
        val expired = org.jjikmuk.backend.global.config.JwtProvider(jwtSecret, -60000)
            .createToken(account.id!!, account.email, "USER", account.tokenVersion, id).token
        photos.upload(account.id!!, MockMultipartFile("file", "avatar.png", "image/png", png()))
        families.create(account.id!!, mapOf("nickname" to "유지가족"))
        val before = credentials.count()
        for (header in listOf(expired, foreignSession.token, null)) {
            val request = post("/api/auth/logout/refresh").contentType(MediaType.APPLICATION_JSON)
                .content("""{"refreshToken":"${issued.refreshToken}"}""")
            if (header != null) request.header("Authorization", bearer(header))
            mvc.perform(request).andExpect(status().isOk)
                .andExpect(jsonPath("$.data.userId").value(account.id!!.toInt()))
                .andExpect(jsonPath("$.data.serverTokenRevoked").value(true))
                .andExpect(jsonPath("$.token").doesNotExist()).andExpect(jsonPath("$.refreshToken").doesNotExist())
        }
        assertEquals(before, credentials.count())
        assertNotNull(sessionRepository.findById(id).orElseThrow().revokedAt)
        mvc.perform(get("/api/users/me").header("Authorization", bearer(issued.token))).andExpect(status().isUnauthorized)
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(issued.refreshToken) }
        for (token in listOf(otherDevice.token, foreignSession.token)) {
            mvc.perform(get("/api/users/me").header("Authorization", bearer(token))).andExpect(status().isOk)
        }
        assertTrue(photoRepository.existsById(account.id!!)); assertEquals(1L, familyRepository.countByOwnerId(account.id!!))
    }

    @Test fun `retained rotated or expired refresh can only revoke not restore a session`() {
        val account = user(); val issued = login(account); val rotated = sessions.refresh(issued.refreshToken)
        mvc.perform(post("/api/auth/logout/refresh").contentType(MediaType.APPLICATION_JSON)
            .content("""{"refreshToken":"${issued.refreshToken}"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.serverTokenRevoked").value(true))
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(rotated.refreshToken) }
        val expired = sessionRepository.saveAndFlush(AuthSession(userId = account.id!!, tokenVersion = 0,
            expiresAt = Instant.now().minusSeconds(1)))
        val raw = EmailVerificationSecurity.newToken()
        credentials.saveAndFlush(RefreshCredential(EmailVerificationSecurity.hashToken(raw), expired.id))
        assertEquals(account.id, sessions.logoutByRefresh(raw))
        assertNotNull(sessionRepository.findById(expired.id).orElseThrow().revokedAt)
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(raw) }
    }

    @Test fun `invalid refresh logout never revokes an access header session`() {
        val account = user(); val issued = login(account)
        for (raw in listOf("", "bad", EmailVerificationSecurity.newToken())) {
            mvc.perform(post("/api/auth/logout/refresh").header("Authorization", bearer(issued.token))
                .contentType(MediaType.APPLICATION_JSON).content("""{"refreshToken":"$raw"}"""))
                .andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("REFRESH_TOKEN_INVALID"))
        }
        for (body in listOf("{}", """{"refreshToken":null}""")) {
            mvc.perform(post("/api/auth/logout/refresh").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isBadRequest).andExpect(jsonPath("$.code").value("INVALID_REQUEST_BODY"))
        }
        mvc.perform(get("/api/auth/logout/refresh")).andExpect(status().isUnauthorized)
        mvc.perform(get("/api/users/me").header("Authorization", bearer(issued.token))).andExpect(status().isOk)
        assertNotNull(sessions.refresh(issued.refreshToken).refreshToken)
    }

    @Test fun `refresh racing logout cannot leave a live rotated session`() {
        val account = user(); val issued = login(account)
        val pool = java.util.concurrent.Executors.newFixedThreadPool(2)
        val start = java.util.concurrent.CountDownLatch(1)
        try {
            val refresh = pool.submit(java.util.concurrent.Callable {
                start.await()
                try { sessions.refresh(issued.refreshToken) as Any } catch (e: CustomException) { e.code }
            })
            val logout = pool.submit(java.util.concurrent.Callable { start.await(); sessions.logoutByRefresh(issued.refreshToken) })
            start.countDown()
            assertEquals(account.id, logout.get(10, java.util.concurrent.TimeUnit.SECONDS))
            val result = refresh.get(10, java.util.concurrent.TimeUnit.SECONDS)
            if (result is AuthResponse) error("REFRESH_TOKEN_INVALID") { sessions.refresh(result.refreshToken) }
            else assertEquals("REFRESH_TOKEN_INVALID", result)
            mvc.perform(get("/api/users/me").header("Authorization", bearer(issued.token))).andExpect(status().isUnauthorized)
        } finally { pool.shutdownNow() }
    }

    @Test fun `nickname availability excludes only authenticated self and final save still rejects duplicates`() {
        val account = user(complete = false); val other = user(); val issued = login(account)
        mvc.perform(get("/api/auth/nicknames/availability").param("nickname", " ${account.nickname.uppercase()} ")
            .header("Authorization", bearer(issued.token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.available").value(true))
        mvc.perform(get("/api/auth/nicknames/availability").param("nickname", account.nickname)
            .param("userId", account.id.toString()))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.available").value(false))
        mvc.perform(get("/api/auth/nicknames/availability").param("nickname", other.nickname)
            .param("userId", other.id.toString()).header("Authorization", bearer(issued.token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.available").value(false))
        mvc.perform(get("/api/auth/nicknames/availability").param("nickname", "n" + UUID.randomUUID().toString().take(8)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.available").value(true))
        mvc.perform(get("/api/auth/nicknames/availability").param("nickname", "!"))
            .andExpect(status().isBadRequest).andExpect(jsonPath("$.code").value("NICKNAME_INVALID"))
        mvc.perform(get("/api/auth/nicknames/availability").param("nickname", account.nickname).header("Authorization", "Bearer bad"))
            .andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("AUTH_TOKEN_INVALID"))
        mvc.perform(patch("/api/users/me").header("Authorization", bearer(issued.token)).contentType(MediaType.APPLICATION_JSON)
            .content("""{"nickname":"${other.nickname}"}"""))
            .andExpect(status().isConflict).andExpect(jsonPath("$.code").value("NICKNAME_ALREADY_EXISTS"))
    }

    @Test fun `public proof routes reach their own verification without an access token`() {
        val unknownProof = EmailVerificationSecurity.newToken()
        for (header in listOf(null, "Bearer stale-access")) {
            val link = post("/api/auth/google/link").contentType(MediaType.APPLICATION_JSON)
                .content("""{"linkToken":"$unknownProof","currentPassword":"Example123!"}""")
            val cancel = post("/api/auth/google/link/cancel").contentType(MediaType.APPLICATION_JSON)
                .content("""{"linkToken":"$unknownProof"}""")
            val refresh = post("/api/auth/refresh").contentType(MediaType.APPLICATION_JSON)
                .content("""{"refreshToken":"$unknownProof"}""")
            if (header != null) listOf(link, cancel, refresh).forEach { it.header("Authorization", header) }
            mvc.perform(link).andExpect(status().isGone).andExpect(jsonPath("$.code").value("GOOGLE_LINK_EXPIRED"))
            mvc.perform(cancel).andExpect(status().isOk)
            mvc.perform(refresh).andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("REFRESH_TOKEN_INVALID"))
        }
    }

    @Test fun `refresh rotates hashed tokens without extending fixed expiry and replay revokes session`() {
        val account = user()
        val first = login(account)
        assertEquals(900L, first.expiresInSeconds)
        assertTrue(Duration.between(Instant.now(), first.refreshExpiresAt).toDays() in 29..30)
        assertFalse(credentials.existsById(first.refreshToken))
        assertTrue(credentials.existsById(EmailVerificationSecurity.hashToken(first.refreshToken)))
        val second = sessions.refresh(first.refreshToken)
        assertNotEquals(first.refreshToken, second.refreshToken)
        assertEquals(first.refreshExpiresAt.toEpochMilli(), second.refreshExpiresAt.toEpochMilli())
        error("REFRESH_TOKEN_REUSED") { sessions.refresh(first.refreshToken) }
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(second.refreshToken) }
        mvc.perform(get("/api/users/me").header("Authorization", bearer(second.token))).andExpect(status().isUnauthorized)
    }

    @Test fun `logout revokes current device only and refresh ignores stale access header`() {
        val account = user()
        val first = login(account)
        val second = login(account)
        mvc.perform(post("/api/auth/logout").header("Authorization", bearer(first.token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.serverTokenRevoked").value(true))
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(first.refreshToken) }
        mvc.perform(post("/api/auth/refresh").servletPath("/api/auth/refresh")
            .header("Authorization", "Bearer stale-access-token").contentType(MediaType.APPLICATION_JSON)
            .content("""{"refreshToken":"${second.refreshToken}"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.refreshToken").isString)
        mvc.perform(get("/api/users/me").header("Authorization", bearer(second.token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.hasPassword").value(true))
    }

    @Test fun `simultaneous refresh has one winner and replay closes its session`() {
        val account = user(); val issued = login(account)
        val pool = java.util.concurrent.Executors.newFixedThreadPool(2)
        val start = java.util.concurrent.CountDownLatch(1)
        try {
            val futures = (1..2).map { pool.submit(java.util.concurrent.Callable {
                start.await()
                try { sessions.refresh(issued.refreshToken) as Any } catch (e: CustomException) { e.code }
            }) }
            start.countDown()
            val results = futures.map { it.get(10, java.util.concurrent.TimeUnit.SECONDS) }
            assertEquals(1, results.filterIsInstance<AuthResponse>().size)
            assertEquals(listOf("REFRESH_TOKEN_REUSED"), results.filterIsInstance<String>())
            error("REFRESH_TOKEN_INVALID") { sessions.refresh(results.filterIsInstance<AuthResponse>().single().refreshToken) }
        } finally { pool.shutdownNow() }
    }

    @Test fun `expired refresh and Google proofs fail without granting login`() {
        val account = user()
        val expired = sessionRepository.saveAndFlush(AuthSession(userId = account.id!!, tokenVersion = 0, expiresAt = Instant.now().minusSeconds(1)))
        val raw = EmailVerificationSecurity.newToken()
        credentials.saveAndFlush(RefreshCredential(EmailVerificationSecurity.hashToken(raw), expired.id))
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(raw) }
        grants.saveAndFlush(GoogleLinkGrant(EmailVerificationSecurity.hashToken(raw), account.id!!, "expired-${account.id}", 0, Instant.now().minusSeconds(1)))
        error("GOOGLE_LINK_EXPIRED") { auth.linkGoogle(GoogleLinkRequest(raw, "Example123!")) }
        assertEquals(AuthProvider.LOCAL, users.findById(account.id!!).orElseThrow().authProvider)
    }

    @Test fun `failed password change preserves sessions while success revokes all devices`() {
        val account = user()
        val a = login(account); val b = login(account)
        error("LOGIN_FAILED") { service.updatePassword(account.id!!, UpdatePasswordRequest("incorrect", "Changed123!")) }
        mvc.perform(get("/api/users/me").header("Authorization", bearer(a.token))).andExpect(status().isOk)
        service.updatePassword(account.id!!, UpdatePasswordRequest("Example123!", "Changed123!"))
        for (old in listOf(a, b)) {
            error("REFRESH_TOKEN_INVALID") { sessions.refresh(old.refreshToken) }
            mvc.perform(get("/api/users/me").header("Authorization", bearer(old.token))).andExpect(status().isUnauthorized)
        }
        assertEquals(account.id, login(account, "Changed123!").userId)
    }

    @Test fun `password reset consumes proof and revokes every refresh session`() {
        val account = user(); val login = login(account)
        val proof = EmailVerificationSecurity.newToken()
        emailGrants.saveAndFlush(EmailVerificationGrant(email = account.email, purpose = EmailVerificationPurpose.PASSWORD_RESET,
            tokenHash = EmailVerificationSecurity.hashToken(proof), expiredAt = java.time.LocalDateTime.now().plusMinutes(5), createdAt = java.time.LocalDateTime.now()))
        auth.resetPassword(PasswordResetRequest(account.email, proof, "Reset123!"))
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(login.refreshToken) }
        assertEquals(account.id, login(account, "Reset123!").userId)
        assertFailsWith<CustomException> { auth.resetPassword(PasswordResetRequest(account.email, proof, "Reset456!")) }
    }

    @Test fun `partial edits preserve omitted values reject arrays and never finish onboarding`() {
        val account = user(complete = false); val token = login(account).token
        mvc.perform(patch("/api/users/me").header("Authorization", bearer(token)).contentType(MediaType.APPLICATION_JSON)
            .content("""{"nickname":"${account.nickname.uppercase()}"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.allergies").value("milk"))
            .andExpect(jsonPath("$.data.specialDiet").value("lowSugar"))
            .andExpect(jsonPath("$.data.profileCompleted").value(false))
        mvc.perform(patch("/api/users/me").header("Authorization", bearer(token)).contentType(MediaType.APPLICATION_JSON)
            .content("""{"allergies":[],"profileCompleted":true}"""))
            .andExpect(status().isBadRequest)
        error("VALIDATION_FAILED") { service.patchProfile(account.id!!, mapOf("allergies" to emptyList<String>())) }
        assertFailsWith<CustomException> { service.patchProfile(account.id!!, mapOf("nickname" to null)) }
        val cleared = service.patchProfile(account.id!!, mapOf("allergies" to null, "specialDiet" to ""))
        assertNull(cleared.allergies); assertNull(cleared.specialDiet); assertFalse(cleared.profileCompleted)
        mvc.perform(post("/api/users/me/profile/complete").header("Authorization", bearer(token)).contentType(MediaType.APPLICATION_JSON)
            .content("""{"nickname":"${account.nickname}"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.profileCompleted").value(true))
        assertTrue(login(account).profileCompleted)
    }

    @Test fun `Google same email requires one time ownership proof and new users remain incomplete`() {
        val account = user()
        `when`(google.verify("existing")).thenReturn(GoogleIdentity("google-${account.id}", account.email))
        val pending = assertIs<GoogleLinkRequiredResponse>(auth.googleLogin(GoogleLoginRequest("existing")))
        assertFalse(pending.loginGranted)
        assertEquals(AuthProvider.LOCAL, users.findById(account.id!!).orElseThrow().authProvider)
        mvc.perform(get("/api/users/me").header("Authorization", bearer(pending.linkToken))).andExpect(status().isUnauthorized)
        error("GOOGLE_LINK_PASSWORD_INVALID") { auth.linkGoogle(GoogleLinkRequest(pending.linkToken, "wrong")) }
        assertEquals(1, grants.findById(EmailVerificationSecurity.hashToken(pending.linkToken)).orElseThrow().attempts)
        val connected = auth.linkGoogle(GoogleLinkRequest(pending.linkToken, "Example123!"))
        assertEquals("LOCAL_AND_GOOGLE", connected.authProvider); assertTrue(connected.hasPassword)
        error("GOOGLE_LINK_EXPIRED") { auth.linkGoogle(GoogleLinkRequest(pending.linkToken, "Example123!")) }
        assertIs<AuthResponse>(auth.googleLogin(GoogleLoginRequest("existing")))
        `when`(google.verify("new")).thenReturn(GoogleIdentity("new-${account.id}", "new-${account.email}"))
        val fresh = assertIs<AuthResponse>(auth.googleLogin(GoogleLoginRequest("new")))
        assertTrue(fresh.isNewUser); assertFalse(fresh.profileCompleted); assertFalse(fresh.hasPassword)
    }

    @Test fun `Google link cancellation and attempt exhaustion preserve local account`() {
        val account = user()
        `when`(google.verify("cancel")).thenReturn(GoogleIdentity("cancel-${account.id}", account.email))
        val pending = assertIs<GoogleLinkRequiredResponse>(auth.googleLogin(GoogleLoginRequest("cancel")))
        auth.cancelGoogleLink(pending.linkToken)
        error("GOOGLE_LINK_EXPIRED") { auth.linkGoogle(GoogleLinkRequest(pending.linkToken, "Example123!")) }
        val next = assertIs<GoogleLinkRequiredResponse>(auth.googleLogin(GoogleLoginRequest("cancel")))
        repeat(5) { error("GOOGLE_LINK_PASSWORD_INVALID") { auth.linkGoogle(GoogleLinkRequest(next.linkToken, "wrong")) } }
        error("GOOGLE_LINK_EXPIRED") { auth.linkGoogle(GoogleLinkRequest(next.linkToken, "Example123!")) }
        assertEquals(AuthProvider.LOCAL, users.findById(account.id!!).orElseThrow().authProvider)
    }

    @Test fun `family ownership version conflicts and analysis restriction union are enforced`() {
        val account = user(); val other = user()
        val member = families.create(account.id!!, mapOf("nickname" to "가족일", "allergies" to "soy", "specialDiet" to "vegan"))
        error("FAMILY_NOT_FOUND") { families.owned(other.id!!, member.id) }
        val updated = families.patch(account.id!!, member.id, mapOf("version" to member.version, "nickname" to "가족이"))
        assertTrue(updated.version > member.version)
        error("PROFILE_VERSION_CONFLICT") { families.patch(account.id!!, member.id, mapOf("version" to member.version, "allergies" to null)) }
        val selected = selection.resolve(account.id, "selected", true, listOf(member.id))
        assertEquals(setOf("milk", "soy"), selected.profile.allergies!!.split(',').toSet())
        assertEquals(setOf("lowSugar", "vegan"), selected.profile.specialDiet!!.split(',').toSet())
        assertNull(selected.profile.id); assertFalse(selected.personalHistoryAllowed)
        error("FAMILY_NOT_FOUND") { selection.resolve(other.id, "selected", false, listOf(member.id)) }
        error("ANALYSIS_SELECTION_INVALID") { selection.resolve(account.id, "selected", false, emptyList()) }
        families.delete(account.id!!, member.id, updated.version)
        error("FAMILY_NOT_FOUND") { selection.resolve(account.id, "selected", false, listOf(member.id)) }
    }

    @Test fun `private photo survives logout and invalid replacement and is removed by delete`() {
        val account = user(); val other = user(); val token = login(account).token
        val image = png()
        mvc.perform(multipart("/api/users/me/photo").file(MockMultipartFile("file", "avatar.png", "image/png", image))
            .with { it.method = "PUT"; it }.header("Authorization", bearer(token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.authenticationRequired").value(true))
        val original = photos.get(account.id!!).content
        error("PHOTO_INVALID") { photos.upload(account.id!!, MockMultipartFile("file", "fake.png", "image/png", "not an image".toByteArray())) }
        assertContentEquals(original, photos.get(account.id!!).content)
        error("PHOTO_INVALID") { photos.upload(account.id!!, MockMultipartFile("file", "wrong.jpg", "image/jpeg", image)) }
        error("PHOTO_TOO_LARGE") { photos.upload(account.id!!, MockMultipartFile("file", "huge.png", "image/png", ByteArray(2 * 1024 * 1024 + 1))) }
        mvc.perform(get("/api/users/me/photo")).andExpect(status().isUnauthorized)
        mvc.perform(get("/api/users/me/photo").header("Authorization", bearer(login(other).token))).andExpect(status().isNotFound)
        mvc.perform(get("/api/users/me/photo").header("Authorization", bearer(token)))
            .andExpect(status().isOk).andExpect(header().string("Cache-Control", "no-store"))
        mvc.perform(post("/api/auth/logout").header("Authorization", bearer(token))).andExpect(status().isOk)
        assertContentEquals(original, photos.get(account.id!!).content)
        photos.delete(account.id!!); photos.delete(account.id!!)
        assertFalse(users.findById(account.id!!).orElseThrow().hasProfilePhoto)
        error("PHOTO_NOT_FOUND") { photos.get(account.id!!) }
    }

    @Test fun `explicit none never uses account conditions in product detail variants search or recommendations`() {
        val account = user(); val token = login(account).token
        val barcode = "FRONT-${account.id}"
        products.saveAndFlush(Product(barcode = barcode, productName = barcode, manufacturer = "테스트제조사", totalWeight = "100g",
            rawMaterials = "우유, 대두", allergyWarning = "우유, 대두 함유", allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL))
        val candidate = "$barcode-C"
        products.saveAndFlush(Product(barcode = candidate, productName = candidate, rawMaterials = "우유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL))
        neighbors.saveAndFlush(ProductNeighborSet(barcode, "test", 1, "$candidate|0.9"))
        mvc.perform(get("/api/products/$barcode").header("Authorization", bearer(token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.analysis.status").value("DANGER"))
        for ((path, analysisPath) in listOf(
            "/api/products/$barcode" to "$.data.analysis",
            "/api/products/$barcode/variants" to "$.data.options[0].data.analysis",
            "/api/products/search?keyword=$barcode" to "$.data[0].analysis")) {
            mvc.perform(get(path).param("analysisMode", "none").header("Authorization", bearer(token)))
                .andExpect(status().isOk).andExpect(jsonPath("$analysisPath.status").value("NOT_EVALUATED"))
                .andExpect(jsonPath("$analysisPath.analysisApplied").value(false))
                .andExpect(jsonPath("$analysisPath.dietConstraints.status").value("NOT_EVALUATED"))
        }
        val none = selection.resolve(account.id, "none", null, null)
        assertNull(none.profile.allergies); assertNull(none.profile.specialDiet)
        val feed = home.recommend(account.id!!, 10, null, 72L, emptySet(), emptySet(), none)
        assertEquals(SafeRecommendationMode.GENERAL, feed.recommendationMode)
        assertTrue(feed.categories.flatMap { it.items }.all { it.safety.status == SafetyStatus.NOT_EVALUATED })
        val similar = alternatives.recommendAlternatives(barcode, account.id!!, 10, 0.0, none)
        assertEquals(RecommendationResultMode.GENERAL, similar.resultMode)
        assertEquals(SafetyStatus.NOT_EVALUATED, similar.referenceSafety.status)
        assertTrue(similar.items.all { it.safety.status == SafetyStatus.NOT_EVALUATED && it.recommendationTier == RecommendationTier.GENERAL })
        mvc.perform(get("/api/users/me").header("Authorization", bearer(token))).andExpect(status().isOk)
    }

    @Test fun `account deletion removes private child data and all credentials`() {
        val account = user(); val token = login(account)
        families.create(account.id!!, mapOf("nickname" to "가족삭제"))
        photos.upload(account.id!!, MockMultipartFile("file", "photo.png", "image/png", png()))
        service.deleteUser(account.id!!)
        assertFalse(users.existsById(account.id!!)); assertFalse(photoRepository.existsById(account.id!!))
        assertEquals(0L, familyRepository.countByOwnerId(account.id!!))
        assertTrue(sessionRepository.findAllByUserId(account.id!!).isEmpty())
        error("REFRESH_TOKEN_INVALID") { sessions.refresh(token.refreshToken) }
    }

    @Test fun `family selection applies to HTTP detail and filtered results without own allergies`() {
        val account = user(); val other = user(); val token = login(account).token
        val family = families.create(account.id!!, mapOf("nickname" to "콩알레르기", "allergies" to "soy", "specialDiet" to "vegan"))
        val barcode = "FAMILY-${account.id}"
        products.saveAndFlush(Product(barcode = barcode, productName = barcode, manufacturer = "가족테스트", totalWeight = "100g",
            rawMaterials = "우유, 설탕", allergyWarning = "우유 함유", allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL,
            lowSugar = true, vegan = false, dietaryDataOrigin = ProductDataOrigin.SOURCE))
        mvc.perform(get("/api/products/$barcode").param("analysisMode", "selected").param("familyProfileIds", family.id.toString())
            .header("Authorization", bearer(token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.analysis.status").value("PASS"))
            .andExpect(jsonPath("$.data.analysis.dietConstraints.status").value("MISMATCH"))
            .andExpect(jsonPath("$.data.analysis.selection.includeSelf").value(false))
        mvc.perform(get("/api/products/$barcode").param("analysisMode", "selected").param("familyProfileIds", family.id.toString())
            .header("Authorization", bearer(login(other).token))).andExpect(status().isNotFound)
        mvc.perform(get("/api/products/filter").param("filters", "lowSugar").param("keyword", barcode)
            .param("analysisMode", "none").header("Authorization", bearer(token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items[0].analysis.status").value("NOT_EVALUATED"))
        mvc.perform(get("/api/products/$barcode").param("analysisMode", "selected").param("familyProfileIds", "invalid")
            .header("Authorization", bearer(token))).andExpect(status().isBadRequest)
    }

    @Test fun `home cursors reject changed analysis targets and profiles`() {
        val account = user(); val none = selection.resolve(account.id, "none", null, null)
        products.saveAllAndFlush((1..3).map { Product(barcode = "CURSOR-${account.id}-$it", productName = "커서${account.id}상품$it") })
        val first = home.recommend(account.id!!, 1, null, 72L, emptySet(), emptySet(), none)
        assertNotNull(first.nextCursor)
        val own = selection.resolve(account.id, "self", null, null)
        assertFailsWith<IllegalArgumentException> { home.recommend(account.id!!, 1, first.nextCursor, null, emptySet(), emptySet(), own) }
        val other = user()
        assertFailsWith<IllegalArgumentException> { home.recommend(other.id!!, 1, first.nextCursor, null, emptySet(), emptySet(), selection.resolve(other.id, "none", null, null)) }
    }

    @Test fun `capacity duplicates cannot hide conflicting family dietary data`() {
        val account = user(); val token = login(account).token
        val family = families.create(account.id!!, mapOf("nickname" to "채식가족", "specialDiet" to "vegan"))
        val barcode = "DIET-${account.id}"
        products.saveAllAndFlush(listOf(
            Product(barcode = barcode, productName = barcode, manufacturer = "같은회사", totalWeight = "100g",
                rawMaterials = "쌀, 소금", energyKcal = 100.0, vegan = true, dietaryDataOrigin = ProductDataOrigin.SOURCE, dietaryDataConfidence = 0.9),
            Product(barcode = "$barcode-B", productName = barcode, manufacturer = "같은회사", totalWeight = "100g",
                rawMaterials = "쌀, 소금", vegan = false, dietaryDataOrigin = ProductDataOrigin.SOURCE, dietaryDataConfidence = 0.9)))
        mvc.perform(get("/api/products/$barcode/variants").param("analysisMode", "selected").param("familyProfileIds", family.id.toString())
            .header("Authorization", bearer(token))).andExpect(status().isOk)
            .andExpect(jsonPath("$.data.options[0].data.analysis.dietConstraints.status").value("MISMATCH"))
            .andExpect(jsonPath("$.data.options[0].hasSafetyDifferences").value(true))
    }

    @Test fun `new passwords have explicit ascii byte boundary but legacy passwords still log in`() {
        AccountInputPolicy.validatePassword("A1" + "!".repeat(70))
        for (password in listOf("Ab12", "abcdefgh", "12345678", "Abc1234 ", "한글Abc1234", "éAbc12345", "A1" + "!".repeat(71))) {
            assertFailsWith<CustomException> { AccountInputPolicy.validatePassword(password) }
        }
        val legacy = user(password = "구형암호1")
        assertEquals(legacy.id, login(legacy, "구형암호1").userId)
    }
}
