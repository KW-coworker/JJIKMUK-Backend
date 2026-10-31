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
    val expiresAt: java.time.OffsetDateTime,
    val expiresInSeconds: Long,
    val resendAvailableAt: java.time.OffsetDateTime
)

data class EmailVerificationResponse(
    val email: String,
    val purpose: String,
    val verificationToken: String,
    val expiresAt: java.time.OffsetDateTime,
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
    val profileCompleted: Boolean,
    val refreshToken: String,
    val refreshExpiresAt: Instant,
    val authProvider: String,
    val hasPassword: Boolean
)

data class RefreshRequest(val refreshToken: String)
data class RefreshLogoutRequest(val refreshToken: String)
data class GoogleLinkRequest(val linkToken: String, val currentPassword: String)
data class GoogleLinkCancelRequest(val linkToken: String)
data class GoogleLinkRequiredResponse(
    val message: String = "기존 계정 소유 확인 후 Google 계정을 연결해주세요.",
    val code: String = "GOOGLE_LINK_REQUIRED",
    val linkToken: String,
    val expiresAt: Instant,
    val expiresInSeconds: Long = 300,
    val loginGranted: Boolean = false
)

data class NicknameAvailabilityResponse(
    val nickname: String,
    val available: Boolean
)
