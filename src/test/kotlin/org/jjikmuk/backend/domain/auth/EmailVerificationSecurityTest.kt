package org.jjikmuk.backend.domain.auth

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class EmailVerificationSecurityTest {
    @Test
    fun `otp is always four numeric digits`() {
        repeat(1_000) {
            assertTrue(EmailVerificationSecurity.newCode().matches(Regex("\\d{4}")))
        }
        assertEquals(300L, EmailVerificationPolicy.CODE_EXPIRATION_SECONDS)
        assertEquals(
            1_800L,
            EmailVerificationPolicy.grantExpirationSeconds(EmailVerificationPurpose.SIGNUP)
        )
        assertEquals(
            300L,
            EmailVerificationPolicy.grantExpirationSeconds(EmailVerificationPurpose.PASSWORD_RESET)
        )
    }

    @Test
    fun `verification tokens are hashed and compared without storing raw token`() {
        val token = EmailVerificationSecurity.newToken()
        val hash = EmailVerificationSecurity.hashToken(token)

        assertFalse(hash.contains(token))
        assertTrue(EmailVerificationSecurity.tokenMatches(token, hash))
        assertFalse(EmailVerificationSecurity.tokenMatches("different-token", hash))
    }
}
