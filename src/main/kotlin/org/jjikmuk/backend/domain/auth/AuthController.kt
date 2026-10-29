package org.jjikmuk.backend.domain.auth

import org.springframework.http.ResponseEntity
import org.springframework.http.HttpStatus
import org.springframework.security.core.Authentication
import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/auth")
class AuthController(
    private val authService: AuthService,
    private val emailService: EmailService,
    private val sessions: AuthSessionService
) {
    @PostMapping("/signup")
    fun signup(@RequestBody request: SignupRequest): ResponseEntity<*> {
        val savedUser = authService.signup(request)
        return ResponseEntity.status(HttpStatus.CREATED).body(
            mapOf("message" to "회원가입 성공", "data" to mapOf("userId" to savedUser.id))
        )
    }

    @PostMapping("/login")
    fun login(@RequestBody request: LoginRequest): ResponseEntity<*> {
        return ResponseEntity.ok(authService.login(request))
    }

    @PostMapping("/google")
    fun googleLogin(@RequestBody request: GoogleLoginRequest): ResponseEntity<*> {
        return ResponseEntity.ok(authService.googleLogin(request))
    }

    @PostMapping("/refresh")
    fun refresh(@RequestBody request: RefreshRequest) = ResponseEntity.ok(sessions.refresh(request.refreshToken))

    @PostMapping("/google/link")
    fun linkGoogle(@RequestBody request: GoogleLinkRequest) = ResponseEntity.ok(authService.linkGoogle(request))

    @PostMapping("/google/link/cancel")
    fun cancelLink(@RequestBody request: GoogleLinkCancelRequest): ResponseEntity<*> {
        authService.cancelGoogleLink(request.linkToken)
        return ResponseEntity.ok(mapOf("message" to "연결 요청을 취소했습니다."))
    }

    @GetMapping("/nicknames/availability")
    fun nicknameAvailability(@RequestParam nickname: String): ResponseEntity<*> =
        ResponseEntity.ok(
            mapOf(
                "message" to "닉네임 사용 가능 여부 조회 성공",
                "data" to authService.nicknameAvailability(nickname)
            )
        )

    @PostMapping("/logout")
    fun logout(authentication: Authentication): ResponseEntity<*> {
        sessions.logout(authentication.principal.toString().toLong(), authentication.details as? String)
        return ResponseEntity.ok(
        mapOf(
            "message" to "서버 세션을 폐기했습니다. 기기에 저장된 토큰을 삭제해주세요.",
            "data" to mapOf(
                "userId" to authentication.principal.toString().toLong(),
                "serverTokenRevoked" to true
            )
        )
        )
    }
    @PostMapping("/email/send")
    fun sendEmailCode(@RequestBody request: EmailSendRequest): ResponseEntity<*> {
        val result = emailService.sendVerificationCode(request)
        return ResponseEntity.ok(
            mapOf(
                "message" to "인증번호가 이메일로 발송되었습니다.",
                "data" to result
            )
        )
    }

    @PostMapping("/email/verify")
    fun verifyEmailCode(@RequestBody request: EmailVerifyRequest): ResponseEntity<*> {
        val result = emailService.verifyVerificationCode(request)
        return ResponseEntity.ok(
            mapOf(
                "message" to "이메일 인증이 완료되었습니다.",
                "data" to result
            )
        )
    }

    @PostMapping("/password/reset")
    fun resetPassword(@RequestBody request: PasswordResetRequest): ResponseEntity<*> {
        authService.resetPassword(request)
        return ResponseEntity.ok(mapOf("message" to "비밀번호가 성공적으로 재설정되었습니다."))
    }
}
