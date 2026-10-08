package org.jjikmuk.backend.domain.auth

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

object EmailVerificationPolicy {
    const val CODE_LENGTH = 4
    const val CODE_EXPIRATION_SECONDS = 300L
    const val SIGNUP_GRANT_EXPIRATION_SECONDS = 1_800L
    const val PASSWORD_RESET_GRANT_EXPIRATION_SECONDS = 300L
    const val RESEND_COOLDOWN_SECONDS = 60L
    const val MAX_SENDS_PER_CODE_WINDOW = 5
    const val MAX_FAILED_ATTEMPTS = 5

    fun grantExpirationSeconds(purpose: EmailVerificationPurpose): Long = when (purpose) {
        EmailVerificationPurpose.SIGNUP -> SIGNUP_GRANT_EXPIRATION_SECONDS
        EmailVerificationPurpose.PASSWORD_RESET -> PASSWORD_RESET_GRANT_EXPIRATION_SECONDS
    }
}

internal object EmailVerificationSecurity {
    private val secureRandom = SecureRandom()

    fun newCode(): String = secureRandom.nextInt(10_000).toString().padStart(4, '0')

    fun newToken(): String {
        val bytes = ByteArray(32)
        secureRandom.nextBytes(bytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }

    fun hashToken(token: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(token.toByteArray(StandardCharsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    fun tokenMatches(rawToken: String, expectedHash: String): Boolean {
        val actual = hashToken(rawToken).toByteArray(StandardCharsets.US_ASCII)
        val expected = expectedHash.toByteArray(StandardCharsets.US_ASCII)
        return MessageDigest.isEqual(actual, expected)
    }
}
