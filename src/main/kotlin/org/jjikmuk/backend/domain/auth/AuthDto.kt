package org.jjikmuk.backend.domain.auth

import java.time.Instant

// 💡 회원가입 시 프론트엔드가 보내줄 데이터
data class SignupRequest(
    val email: String,
    val password: String = "",
    val nickname: String,
    val allergies: String? = null,
    val diseases: String? = null,
    val specialDiet: String? = null,
    val dislikedIngredients: String? = null,
    val verificationToken: String
)

// 💡 로그인 시 프론트엔드가 보내줄 데이터
data class LoginRequest(
    val email: String,
    val password: String
)

data class GoogleLoginRequest(
    val idToken: String
)

data class FindPasswordRequest(
    val email: String
)

data class PasswordResetRequest(
    val email: String,
    val verificationToken: String,
    val newPassword: String
)

data class EmailSendRequest(
    val email: String,
    val purpose: String
)

data class EmailVerifyRequest(
    val email: String,
    val code: String,
    val purpose: String
)

data class EmailCodeDeliveryResponse(
    val email: String,
    val purpose: String,
    val expiresAt: java.time.LocalDateTime,
    val expiresInSeconds: Long,
    val resendAvailableAt: java.time.LocalDateTime
)

data class EmailVerificationResponse(
    val email: String,
    val purpose: String,
    val verificationToken: String,
    val expiresAt: java.time.LocalDateTime,
    val expiresInSeconds: Long
)

data class AuthResponse(
    val message: String,
    val token: String,
    val tokenType: String = "Bearer",
    val userId: Long,
    val email: String,
    val expiresAt: Instant,
    val expiresInSeconds: Long,
    val isNewUser: Boolean,
    val profileCompleted: Boolean
)

data class NicknameAvailabilityResponse(
    val nickname: String,
    val available: Boolean
)
