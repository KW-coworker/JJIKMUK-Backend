package org.jjikmuk.backend.domain.auth

import com.google.api.client.googleapis.auth.oauth2.GoogleIdToken
import com.google.api.client.googleapis.auth.oauth2.GoogleIdTokenVerifier
import com.google.api.client.googleapis.auth.oauth2.GooglePublicKeysManager
import com.google.api.client.http.javanet.NetHttpTransport
import com.google.api.client.json.gson.GsonFactory
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.beans.factory.annotation.Value
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Component
import org.springframework.transaction.annotation.Propagation
import org.springframework.transaction.annotation.Transactional
import java.io.IOException
import java.security.GeneralSecurityException
import java.security.cert.CertificateException

data class GoogleIdentity(val subject: String, val email: String)

@Configuration(proxyBeanMethods = false)
class GoogleTokenVerificationConfig {
    // Singleton cache; construction does not contact Google or prevent email login when unconfigured.
    @Bean
    fun googlePublicKeysManager(): GooglePublicKeysManager =
        GooglePublicKeysManager(NetHttpTransport(), GsonFactory.getDefaultInstance())

    @Bean
    fun googleIdTokenVerifier(
        keys: GooglePublicKeysManager,
        @Value("\${google.client-id:}") clientId: String
    ): GoogleIdTokenVerifier = GoogleIdTokenVerifier.Builder(keys)
        .setAudience(listOf(clientId.trim()))
        // Keep expired tokens invalid; the library otherwise allows five minutes of clock skew.
        .setAcceptableTimeSkewSeconds(0)
        .build()
}

@Component
class GoogleIdentityVerifier(
    private val verifier: GoogleIdTokenVerifier,
    @Value("\${google.client-id:}") private val clientId: String
) {
    // Guard this boundary too, so future callers cannot download public keys inside a DB transaction.
    @Transactional(propagation = Propagation.NEVER)
    fun verify(idToken: String): GoogleIdentity {
        if (clientId.isBlank()) throw CustomException(HttpStatus.SERVICE_UNAVAILABLE,
            "Google 로그인이 아직 구성되지 않았습니다.", ApiErrorCode.GOOGLE_LOGIN_UNAVAILABLE)
        if (idToken.length !in 20..10000) throw invalid()

        // Parse separately: malformed client input is 401, not a Google network outage (503).
        val parsed = try {
            GoogleIdToken.parse(verifier.jsonFactory, idToken)
        } catch (_: IOException) {
            throw invalid()
        } catch (_: IllegalArgumentException) {
            throw invalid()
        }
        val payload = parsed.payload
        val now = verifier.clock.currentTimeMillis() / 1000
        val subject = payload.subject?.takeIf { it.isNotBlank() && it.length <= 255 } ?: throw invalid()
        if (parsed.header.algorithm != "RS256" || payload.audience != clientId.trim() ||
            payload.issuer !in setOf("accounts.google.com", "https://accounts.google.com") ||
            payload["email_verified"]?.toString() != "true" ||
            (payload.expirationTimeSeconds ?: 0) <= now ||
            payload.issuedAtTimeSeconds == null || payload.issuedAtTimeSeconds > now) throw invalid()
        val email = try {
            AccountInputPolicy.normalizeEmail(payload.email ?: "")
        } catch (_: CustomException) {
            throw invalid()
        }

        // No identity is returned until Google's verifier has checked the RSA signature and claims.
        // Only Google's public certificates are downloaded; the user's token is never sent in a URL.
        val valid = try {
            verifier.verify(parsed)
        } catch (_: IOException) {
            throw unavailable()
        } catch (_: CertificateException) {
            throw unavailable()
        } catch (_: GeneralSecurityException) {
            throw invalid()
        } catch (_: IllegalArgumentException) {
            throw invalid()
        }
        if (!valid) throw invalid()
        return GoogleIdentity(subject, email)
    }

    private fun invalid() = CustomException(HttpStatus.UNAUTHORIZED,
        "유효하지 않은 Google ID 토큰입니다.", ApiErrorCode.GOOGLE_TOKEN_INVALID)
    private fun unavailable() = CustomException(HttpStatus.SERVICE_UNAVAILABLE,
        "Google 인증 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", ApiErrorCode.GOOGLE_LOGIN_UNAVAILABLE)
}
