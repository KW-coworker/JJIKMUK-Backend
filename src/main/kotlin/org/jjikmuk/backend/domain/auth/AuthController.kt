package org.jjikmuk.backend.domain.auth

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/auth")
class AuthController(
    private val authService: AuthService,
    private val emailService: EmailService
) {
    @PostMapping("/signup")
    fun signup(@RequestBody request: SignupRequest): ResponseEntity<*> {
        val savedUser = authService.signup(request)
        return ResponseEntity.ok(mapOf("message" to "회원가입 성공", "data" to savedUser.id))
    }

    @PostMapping("/login")
    fun login(@RequestBody request: LoginRequest): ResponseEntity<*> {
        val token = authService.login(request)
        return ResponseEntity.ok(mapOf("message" to "로그인 성공", "token" to token))
    }

    @PostMapping("/google")
    fun googleLogin(@RequestBody request: GoogleLoginRequest): ResponseEntity<*> {
        val token = authService.googleLogin(request)
        return ResponseEntity.ok(mapOf("message" to "구글 로그인 성공", "token" to token))
    }
    @PostMapping("/email/send")
    fun sendEmailCode(@RequestBody request: EmailSendRequest): ResponseEntity<*> {
        emailService.sendVerificationCode(request.email)
        return ResponseEntity.ok(mapOf("message" to "인증번호가 이메일로 발송되었습니다."))
    }

    @PostMapping("/email/verify")
    fun verifyEmailCode(@RequestBody request: EmailVerifyRequest): ResponseEntity<*> {
        authService.verifyEmailCode(request)
        return ResponseEntity.ok(mapOf("message" to "이메일 인증이 완료되었습니다."))
    }

    @PostMapping("/password/reset")
    fun resetPassword(@RequestBody request: PasswordResetRequest): ResponseEntity<*> {
        authService.resetPassword(request)
        return ResponseEntity.ok(mapOf("message" to "비밀번호가 성공적으로 재설정되었습니다."))
    }
}