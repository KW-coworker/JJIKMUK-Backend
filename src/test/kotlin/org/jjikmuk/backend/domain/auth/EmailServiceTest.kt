package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.mockito.ArgumentCaptor
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import org.springframework.mail.SimpleMailMessage
import org.springframework.mail.javamail.JavaMailSender
import java.time.LocalDateTime
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class EmailServiceTest {
    private val mailSender = mock(JavaMailSender::class.java)
    private val verificationRepository = mock(EmailVerificationRepository::class.java)
    private val grantRepository = mock(EmailVerificationGrantRepository::class.java)
    private val userRepository = mock(UserRepository::class.java)
    private val service = EmailService(
        mailSender,
        verificationRepository,
        grantRepository,
        userRepository
    )

    @Test
    fun `signup send creates a four digit code with five minute expiry`() {
        val email = "new-user@example.com"
        `when`(userRepository.findByEmail(email)).thenReturn(null)
        `when`(
            verificationRepository.findByEmailAndPurpose(email, EmailVerificationPurpose.SIGNUP)
        ).thenReturn(null)

        val response = service.sendVerificationCode(EmailSendRequest(email, "signup"))

        val captor = ArgumentCaptor.forClass(EmailVerification::class.java)
        verify(verificationRepository).save(captor.capture())
        val saved = captor.value
        assertTrue(saved.code.matches(Regex("\\d{4}")))
        assertEquals(EmailVerificationPurpose.SIGNUP, saved.purpose)
        assertEquals(300L, response.expiresInSeconds)
        assertEquals(60L, java.time.Duration.between(saved.sentAt, response.resendAvailableAt).seconds)
        verify(mailSender).send(org.mockito.ArgumentMatchers.any(SimpleMailMessage::class.java))
    }

    @Test
    fun `verification returns purpose scoped token and consumes otp`() {
        val email = "reset-user@example.com"
        val verification = EmailVerification(
            email = email,
            purpose = EmailVerificationPurpose.PASSWORD_RESET,
            code = "0042",
            expiredAt = LocalDateTime.now().plusMinutes(5),
            sentAt = LocalDateTime.now()
        )
        `when`(
            verificationRepository.findByEmailAndPurpose(email, EmailVerificationPurpose.PASSWORD_RESET)
        ).thenReturn(verification)
        `when`(
            grantRepository.findByEmailAndPurpose(email, EmailVerificationPurpose.PASSWORD_RESET)
        ).thenReturn(null)

        val response = service.verifyVerificationCode(
            EmailVerifyRequest(email, "0042", "password_reset")
        )

        val captor = ArgumentCaptor.forClass(EmailVerificationGrant::class.java)
        verify(grantRepository).save(captor.capture())
        assertTrue(EmailVerificationSecurity.tokenMatches(response.verificationToken, captor.value.tokenHash))
        assertEquals("password_reset", response.purpose)
        assertEquals(300L, response.expiresInSeconds)
        verify(verificationRepository).delete(verification)
    }

    @Test
    fun `signup verification grant lasts thirty minutes for onboarding`() {
        val email = "onboarding-user@example.com"
        val verification = EmailVerification(
            email = email,
            purpose = EmailVerificationPurpose.SIGNUP,
            code = "4821",
            expiredAt = LocalDateTime.now().plusMinutes(5),
            sentAt = LocalDateTime.now()
        )
        `when`(
            verificationRepository.findByEmailAndPurpose(email, EmailVerificationPurpose.SIGNUP)
        ).thenReturn(verification)
        `when`(
            grantRepository.findByEmailAndPurpose(email, EmailVerificationPurpose.SIGNUP)
        ).thenReturn(null)

        val response = service.verifyVerificationCode(
            EmailVerifyRequest(email, "4821", "signup")
        )

        assertEquals(1_800L, response.expiresInSeconds)
        assertTrue(response.expiresAt.isAfter(LocalDateTime.now().plusMinutes(29)))
    }

    @Test
    fun `wrong code increments attempts without issuing token`() {
        val email = "wrong-code@example.com"
        val verification = EmailVerification(
            email = email,
            purpose = EmailVerificationPurpose.SIGNUP,
            code = "1234",
            expiredAt = LocalDateTime.now().plusMinutes(5),
            sentAt = LocalDateTime.now()
        )
        `when`(
            verificationRepository.findByEmailAndPurpose(email, EmailVerificationPurpose.SIGNUP)
        ).thenReturn(verification)

        assertFailsWith<CustomException> {
            service.verifyVerificationCode(EmailVerifyRequest(email, "9999", "signup"))
        }

        assertEquals(1, verification.failedAttempts)
        verify(verificationRepository).save(verification)
        verify(grantRepository, never()).save(org.mockito.ArgumentMatchers.any(EmailVerificationGrant::class.java))
    }

    @Test
    fun `password reset send rejects an unregistered email`() {
        val email = "missing@example.com"
        `when`(userRepository.findByEmail(email)).thenReturn(null)

        val error = assertFailsWith<CustomException> {
            service.sendVerificationCode(EmailSendRequest(email, "password_reset"))
        }

        assertEquals(404, error.status.value())
        verify(mailSender, never()).send(org.mockito.ArgumentMatchers.any(SimpleMailMessage::class.java))
    }

    @Test
    fun `signup send rejects an already registered email`() {
        val email = "registered@example.com"
        `when`(userRepository.findByEmail(email)).thenReturn(
            User(email = email, password = "encoded", nickname = "가입 사용자")
        )

        val error = assertFailsWith<CustomException> {
            service.sendVerificationCode(EmailSendRequest(email, "signup"))
        }

        assertEquals(409, error.status.value())
    }
}
