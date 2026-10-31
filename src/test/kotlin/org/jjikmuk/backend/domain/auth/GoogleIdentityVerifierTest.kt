package org.jjikmuk.backend.domain.auth

import com.google.api.client.googleapis.auth.oauth2.GoogleIdTokenVerifier
import com.google.api.client.googleapis.auth.oauth2.GooglePublicKeysManager
import com.google.api.client.util.Clock
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.MethodSource
import org.junit.jupiter.params.provider.ValueSource
import org.mockito.Mockito.*
import org.springframework.http.HttpStatus
import java.io.IOException
import java.security.cert.CertificateException
import java.util.stream.Stream
import kotlin.test.*

class GoogleIdentityVerifierTest {
    private lateinit var keys: GooglePublicKeysManager
    private lateinit var verifier: GoogleIdTokenVerifier
    private lateinit var subject: GoogleIdentityVerifier

    @BeforeEach fun setup() {
        keys = mock(GooglePublicKeysManager::class.java)
        `when`(keys.jsonFactory).thenReturn(GoogleSignedTokenFixtures.json)
        `when`(keys.publicKeys).thenReturn(listOf(GoogleSignedTokenFixtures.keys.public))
        verifier = GoogleIdTokenVerifier.Builder(keys)
            .setAudience(listOf(GoogleSignedTokenFixtures.CLIENT_ID))
            .setAcceptableTimeSkewSeconds(0).setClock(Clock { NOW * 1000 }).build()
        subject = GoogleIdentityVerifier(verifier, GoogleSignedTokenFixtures.CLIENT_ID)
    }

    @ParameterizedTest
    @ValueSource(strings = ["accounts.google.com", "https://accounts.google.com"])
    fun `real RSA signature and Google claims produce a normalized identity`(issuer: String) {
        val token = GoogleSignedTokenFixtures.token(mapOf("iss" to issuer, "email" to "  Google-Test@Example.com  "), NOW)
        assertEquals(GoogleIdentity("google-test-subject", "google-test@example.com"), subject.verify(token))
        verify(keys).publicKeys
    }

    @ParameterizedTest
    @MethodSource("invalidClaims")
    fun `invalid or missing claims fail closed without a key request`(claims: Map<String, Any?>) {
        assertError(HttpStatus.UNAUTHORIZED, "GOOGLE_TOKEN_INVALID") {
            subject.verify(GoogleSignedTokenFixtures.token(claims, NOW))
        }
        verify(keys, never()).publicKeys
    }

    @Test fun `missing configuration is 503 and makes no key request`() {
        assertError(HttpStatus.SERVICE_UNAVAILABLE, "GOOGLE_LOGIN_UNAVAILABLE") {
            GoogleIdentityVerifier(verifier, " ").verify(GoogleSignedTokenFixtures.token(now = NOW))
        }
        verifyNoInteractionsAfterSetup()
    }

    @ParameterizedTest
    @ValueSource(strings = ["", "abc", "this-is-not-a-real-google-id-token", "eyJhbGciOiJSUzI1NiJ9.e30.eA", "aaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbb.cccccccccccccccccccc"])
    fun `malformed tokens are 401 not infrastructure failures`(token: String) {
        assertError(HttpStatus.UNAUTHORIZED, "GOOGLE_TOKEN_INVALID") { subject.verify(token) }
        verify(keys, never()).publicKeys
    }

    @Test fun `oversized tokens are rejected before parsing`() {
        assertError(HttpStatus.UNAUTHORIZED, "GOOGLE_TOKEN_INVALID") { subject.verify("x".repeat(10001)) }
        verifyNoInteractionsAfterSetup()
    }

    @Test fun `signature made with a different private key is rejected`() {
        assertError(HttpStatus.UNAUTHORIZED, "GOOGLE_TOKEN_INVALID") {
            subject.verify(GoogleSignedTokenFixtures.token(now = NOW, key = GoogleSignedTokenFixtures.otherKeys.private))
        }
    }

    @Test fun `tampered payload is rejected even with valid claims`() {
        val original = GoogleSignedTokenFixtures.token(now = NOW).split('.')
        val changed = GoogleSignedTokenFixtures.token(mapOf("sub" to "attacker"), NOW).split('.')
        assertError(HttpStatus.UNAUTHORIZED, "GOOGLE_TOKEN_INVALID") {
            subject.verify("${original[0]}.${changed[1]}.${original[2]}")
        }
    }

    @Test fun `short RSA signature is rejected without a server error`() {
        val original = GoogleSignedTokenFixtures.token(now = NOW).substringBeforeLast('.')
        assertError(HttpStatus.UNAUTHORIZED, "GOOGLE_TOKEN_INVALID") { subject.verify("$original.eA") }
    }

    @ParameterizedTest
    @ValueSource(strings = ["none", "HS256", "RS512"])
    fun `only RS256 is accepted`(algorithm: String) {
        assertError(HttpStatus.UNAUTHORIZED, "GOOGLE_TOKEN_INVALID") {
            subject.verify(GoogleSignedTokenFixtures.token(now = NOW, algorithm = algorithm))
        }
        verify(keys, never()).publicKeys
    }

    @Test fun `public key download failure is 503`() {
        `when`(keys.publicKeys).thenThrow(IOException("test-only failure"))
        assertError(HttpStatus.SERVICE_UNAVAILABLE, "GOOGLE_LOGIN_UNAVAILABLE") {
            subject.verify(GoogleSignedTokenFixtures.token(now = NOW))
        }
    }

    @Test fun `invalid certificate from key service is 503`() {
        `when`(keys.publicKeys).thenThrow(CertificateException("test-only failure"))
        assertError(HttpStatus.SERVICE_UNAVAILABLE, "GOOGLE_LOGIN_UNAVAILABLE") {
            subject.verify(GoogleSignedTokenFixtures.token(now = NOW))
        }
    }

    @Test fun `production verifier has one audience strict expiry and a shared key cache`() {
        val configured = GoogleTokenVerificationConfig().googleIdTokenVerifier(keys, " ${GoogleSignedTokenFixtures.CLIENT_ID} ")
        assertEquals(listOf(GoogleSignedTokenFixtures.CLIENT_ID), configured.audience.toList())
        assertEquals(0L, configured.acceptableTimeSkewSeconds)
        assertSame(keys, configured.publicKeysManager)
        assertEquals(setOf("accounts.google.com", "https://accounts.google.com"), configured.issuers.toSet())
    }

    private fun verifyNoInteractionsAfterSetup() { verify(keys, never()).publicKeys }
    private fun assertError(status: HttpStatus, code: String, action: () -> Unit) {
        val error = assertFailsWith<CustomException> { action() }
        assertEquals(status, error.status)
        assertEquals(code, error.code)
    }

    companion object {
        private const val NOW = 1_800_000_000L
        @JvmStatic fun invalidClaims(): Stream<Map<String, Any?>> = listOf(
            mapOf("aud" to "other-client"), mapOf("aud" to null),
            mapOf("aud" to listOf(GoogleSignedTokenFixtures.CLIENT_ID, "other-client")),
            mapOf("iss" to "https://attacker.example"), mapOf("iss" to null),
            mapOf("exp" to NOW - 1), mapOf("exp" to NOW), mapOf("exp" to null), mapOf("exp" to "invalid"),
            mapOf("iat" to NOW + 60), mapOf("iat" to null),
            mapOf("sub" to null), mapOf("sub" to " "), mapOf("sub" to "x".repeat(256)),
            mapOf("email" to null), mapOf("email" to "invalid-email"),
            mapOf("email_verified" to null), mapOf("email_verified" to false),
            mapOf("email_verified" to 1), mapOf("email_verified" to mapOf("value" to true))
        ).stream()
    }
}
