package org.jjikmuk.backend.domain.auth

// 💡 회원가입 시 프론트엔드가 보내줄 데이터
data class SignupRequest(
    val email: String,
    val password: String, // 유저가 입력한 원본 비밀번호
    val nickname: String,
    val allergies: String?,
    val diseases: String?
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
    val code: String,
    val newPassword: String
)

data class EmailSendRequest(val email: String)
data class EmailVerifyRequest(val email: String, val code: String)