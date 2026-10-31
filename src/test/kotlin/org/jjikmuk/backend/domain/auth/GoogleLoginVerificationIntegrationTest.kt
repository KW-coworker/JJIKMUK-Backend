package org.jjikmuk.backend.domain.auth

import com.google.api.client.googleapis.auth.oauth2.GooglePublicKeysManager
import jakarta.servlet.Filter
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.Mockito.`when`
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.web.context.WebApplicationContext
import java.io.IOException
import java.util.UUID
import kotlin.test.assertEquals

/** H2 + real GoogleIdTokenVerifier, RSA signature, API/security/services; only public-key supply is mocked. */
@SpringBootTest(properties = [
    "spring.datasource.url=jdbc:h2:mem:google-verification;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false",
    "google.client-id=unit-test-web.apps.googleusercontent.com"
])
@ActiveProfiles("test")
class GoogleLoginVerificationIntegrationTest @Autowired constructor(
    private val context: WebApplicationContext,
    private val users: UserRepository,
    private val encoder: BCryptPasswordEncoder
) {
    @MockitoBean private lateinit var keys: GooglePublicKeysManager
    private lateinit var mvc: MockMvc

    @BeforeEach fun setup() {
        `when`(keys.jsonFactory).thenReturn(GoogleSignedTokenFixtures.json)
        `when`(keys.publicKeys).thenReturn(listOf(GoogleSignedTokenFixtures.keys.public))
        mvc = MockMvcBuilders.webAppContextSetup(context)
            .addFilters<org.springframework.test.web.servlet.setup.DefaultMockMvcBuilder>(context.getBean("springSecurityFilterChain", Filter::class.java))
            .build()
    }

    @Test fun `signed new Google login and repeat login return the same incomplete user`() {
        val unique = UUID.randomUUID().toString()
        val body = body(GoogleSignedTokenFixtures.token(mapOf("sub" to unique, "email" to "$unique@example.com")))
        mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isOk).andExpect(jsonPath("$.isNewUser").value(true))
            .andExpect(jsonPath("$.profileCompleted").value(false)).andExpect(jsonPath("$.token").isString)
            .andExpect(jsonPath("$.refreshToken").isString)
        val id = users.findByEmail("$unique@example.com")!!.id
        mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isOk).andExpect(jsonPath("$.isNewUser").value(false))
            .andExpect(jsonPath("$.userId").value(id)).andExpect(jsonPath("$.profileCompleted").value(false))
    }

    @Test fun `verified same-email login requires explicit password linking`() {
        val unique = UUID.randomUUID().toString().replace("-", "")
        val user = users.saveAndFlush(User(email = "$unique@example.com", nickname = "u${unique.take(12)}",
            password = encoder.encode("Example123!")!!, profileCompleted = true))
        val token = GoogleSignedTokenFixtures.token(mapOf("sub" to unique, "email" to user.email))
        val pending = mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON).content(body(token)))
            .andExpect(status().isOk).andExpect(jsonPath("$.code").value("GOOGLE_LINK_REQUIRED"))
            .andExpect(jsonPath("$.loginGranted").value(false)).andExpect(jsonPath("$.token").doesNotExist())
            .andReturn().response.contentAsString
        val linkToken = GoogleSignedTokenFixtures.json.fromString(pending, Map::class.java)["linkToken"]
        val linkBody = GoogleSignedTokenFixtures.json.toString(mapOf("linkToken" to linkToken, "currentPassword" to "Example123!"))
        mvc.perform(post("/api/auth/google/link").contentType(MediaType.APPLICATION_JSON).content(linkBody))
            .andExpect(status().isOk).andExpect(jsonPath("$.userId").value(user.id))
            .andExpect(jsonPath("$.authProvider").value("LOCAL_AND_GOOGLE"))
    }

    @Test fun `forged token creates no user and returns 401`() {
        val count = users.count()
        val token = GoogleSignedTokenFixtures.token(key = GoogleSignedTokenFixtures.otherKeys.private)
        mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON).content(body(token)))
            .andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("GOOGLE_TOKEN_INVALID"))
        assertEquals(count, users.count())
    }

    @Test fun `malformed token creates no user and returns 401`() {
        val count = users.count()
        mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON).content(body("not-a-real-google-token")))
            .andExpect(status().isUnauthorized).andExpect(jsonPath("$.code").value("GOOGLE_TOKEN_INVALID"))
        assertEquals(count, users.count())
    }

    @Test fun `key service outage creates no user and returns 503`() {
        val count = users.count()
        `when`(keys.publicKeys).thenThrow(IOException("test-only key service outage"))
        mvc.perform(post("/api/auth/google").contentType(MediaType.APPLICATION_JSON).content(body(GoogleSignedTokenFixtures.token())))
            .andExpect(status().isServiceUnavailable).andExpect(jsonPath("$.code").value("GOOGLE_LOGIN_UNAVAILABLE"))
        assertEquals(count, users.count())
    }

    private fun body(token: String) = GoogleSignedTokenFixtures.json.toString(mapOf("idToken" to token))
}
