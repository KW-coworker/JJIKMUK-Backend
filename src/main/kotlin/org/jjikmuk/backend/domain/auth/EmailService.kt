package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.mail.SimpleMailMessage
import org.springframework.mail.javamail.JavaMailSender
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Duration
import java.time.LocalDateTime

@Service
class EmailService(
    private val mailSender: JavaMailSender,
    private val emailVerificationRepository: EmailVerificationRepository,
    private val emailVerificationGrantRepository: EmailVerificationGrantRepository,
    private val userRepository: UserRepository
) {
    @Transactional
    fun sendVerificationCode(request: EmailSendRequest): EmailCodeDeliveryResponse {
        val email = AccountInputPolicy.normalizeEmail(request.email)
        val purpose = EmailVerificationPurpose.parse(request.purpose)
        validateSendTarget(email, purpose)

        val now = LocalDateTime.now()
        val existing = emailVerificationRepository.findByEmailAndPurpose(email, purpose)
        val wasActive = existing?.expiredAt?.isAfter(now) == true
        if (existing != null && wasActive) {
            val resendAvailableAt = existing.sentAt.plusSeconds(
                EmailVerificationPolicy.RESEND_COOLDOWN_SECONDS
            )
            if (resendAvailableAt.isAfter(now)) {
                val retryAfter = Duration.between(now, resendAvailableAt).seconds.coerceAtLeast(1)
                throw CustomException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "인증번호는 ${retryAfter}초 후에 다시 요청할 수 있습니다.",
                    ApiErrorCode.OTP_RATE_LIMITED
                )
            }
            if (existing.sendCount >= EmailVerificationPolicy.MAX_SENDS_PER_CODE_WINDOW) {
                throw CustomException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "인증번호 재전송 횟수를 초과했습니다. 기존 인증번호 만료 후 다시 요청해주세요.",
                    ApiErrorCode.OTP_RATE_LIMITED
                )
            }
        }

        val code = EmailVerificationSecurity.newCode()
        val expiresAt = now.plusSeconds(EmailVerificationPolicy.CODE_EXPIRATION_SECONDS)
        val verification = if (existing == null) {
            EmailVerification(
                email = email,
                purpose = purpose,
                code = code,
                expiredAt = expiresAt,
                sentAt = now
            )
        } else {
            existing.apply {
                this.code = code
                this.expiredAt = expiresAt
                this.sentAt = now
                this.failedAttempts = 0
                this.sendCount = if (wasActive) existing.sendCount + 1 else 1
            }
        }

        // 새 코드를 발송하면 이전에 발급했던 같은 용도의 인증 권한도 폐기한다.
        emailVerificationGrantRepository.deleteByEmailAndPurpose(email, purpose)
        emailVerificationRepository.save(verification)
        sendMail(email, purpose, code)

        return EmailCodeDeliveryResponse(
            email = email,
            purpose = purpose.id,
            expiresAt = expiresAt,
            expiresInSeconds = EmailVerificationPolicy.CODE_EXPIRATION_SECONDS,
            resendAvailableAt = now.plusSeconds(EmailVerificationPolicy.RESEND_COOLDOWN_SECONDS)
        )
    }

    @Transactional(noRollbackFor = [CustomException::class])
    fun verifyVerificationCode(request: EmailVerifyRequest): EmailVerificationResponse {
        val email = AccountInputPolicy.normalizeEmail(request.email)
        val purpose = EmailVerificationPurpose.parse(request.purpose)
        if (!request.code.matches(Regex("\\d{${EmailVerificationPolicy.CODE_LENGTH}}"))) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "인증번호는 4자리 숫자여야 합니다.",
                ApiErrorCode.OTP_INVALID,
                "code"
            )
        }

        val verification = emailVerificationRepository.findByEmailAndPurpose(email, purpose)
            ?: throw CustomException(
                HttpStatus.BAD_REQUEST,
                "인증 요청 내역이 없습니다.",
                ApiErrorCode.OTP_NOT_REQUESTED
            )
        val now = LocalDateTime.now()

        if (!verification.expiredAt.isAfter(now)) {
            emailVerificationRepository.delete(verification)
            throw CustomException(
                HttpStatus.GONE,
                "인증 시간이 만료되었습니다. 인증번호를 다시 요청해주세요.",
                ApiErrorCode.OTP_EXPIRED
            )
        }
        if (verification.failedAttempts >= EmailVerificationPolicy.MAX_FAILED_ATTEMPTS) {
            emailVerificationRepository.delete(verification)
            throw CustomException(
                HttpStatus.TOO_MANY_REQUESTS,
                "인증 시도 횟수를 초과했습니다. 인증번호를 다시 요청해주세요.",
                ApiErrorCode.OTP_RATE_LIMITED
            )
        }
        if (verification.code != request.code) {
            verification.failedAttempts += 1
            val remaining = EmailVerificationPolicy.MAX_FAILED_ATTEMPTS - verification.failedAttempts
            if (remaining == 0) {
                emailVerificationRepository.delete(verification)
                throw CustomException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "인증 시도 횟수를 초과했습니다. 인증번호를 다시 요청해주세요.",
                    ApiErrorCode.OTP_RATE_LIMITED
                )
            }
            emailVerificationRepository.save(verification)
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "인증번호가 일치하지 않습니다. 남은 시도 횟수: ${remaining}회",
                ApiErrorCode.OTP_INVALID,
                "code"
            )
        }

        val rawToken = EmailVerificationSecurity.newToken()
        val grantExpirationSeconds = EmailVerificationPolicy.grantExpirationSeconds(purpose)
        val grantExpiresAt = now.plusSeconds(grantExpirationSeconds)
        val grant = emailVerificationGrantRepository.findByEmailAndPurpose(email, purpose)
            ?.apply {
                tokenHash = EmailVerificationSecurity.hashToken(rawToken)
                expiredAt = grantExpiresAt
                createdAt = now
            }
            ?: EmailVerificationGrant(
                email = email,
                purpose = purpose,
                tokenHash = EmailVerificationSecurity.hashToken(rawToken),
                expiredAt = grantExpiresAt,
                createdAt = now
            )

        emailVerificationGrantRepository.save(grant)
        emailVerificationRepository.delete(verification)

        return EmailVerificationResponse(
            email = email,
            purpose = purpose.id,
            verificationToken = rawToken,
            expiresAt = grantExpiresAt,
            expiresInSeconds = grantExpirationSeconds
        )
    }

    @Transactional
    fun consumeVerificationGrant(
        emailValue: String,
        purpose: EmailVerificationPurpose,
        rawToken: String
    ) {
        val email = AccountInputPolicy.normalizeEmail(emailValue)
        if (rawToken.isBlank()) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "이메일 인증 토큰이 필요합니다.",
                ApiErrorCode.VERIFICATION_REQUIRED,
                "verificationToken"
            )
        }

        val grant = emailVerificationGrantRepository.findByEmailAndPurpose(email, purpose)
            ?: throw CustomException(
                HttpStatus.BAD_REQUEST,
                "완료된 이메일 인증 내역이 없습니다.",
                ApiErrorCode.VERIFICATION_REQUIRED
            )
        if (!grant.expiredAt.isAfter(LocalDateTime.now())) {
            throw CustomException(
                HttpStatus.GONE,
                "이메일 인증 권한이 만료되었습니다. 인증을 다시 진행해주세요.",
                ApiErrorCode.VERIFICATION_EXPIRED
            )
        }
        if (!EmailVerificationSecurity.tokenMatches(rawToken, grant.tokenHash)) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "이메일 인증 토큰이 유효하지 않습니다.",
                ApiErrorCode.VERIFICATION_TOKEN_INVALID,
                "verificationToken"
            )
        }

        // 토큰은 회원가입 또는 비밀번호 재설정 한 번에만 사용할 수 있다.
        emailVerificationGrantRepository.delete(grant)
    }

    private fun validateSendTarget(email: String, purpose: EmailVerificationPurpose) {
        val user = userRepository.findByEmail(email)
        when (purpose) {
            EmailVerificationPurpose.SIGNUP -> if (user != null) {
                throw CustomException(
                    HttpStatus.CONFLICT,
                    "이미 가입된 이메일입니다. 가입 요청의 응답을 받지 못했다면 로그인을 시도해주세요.",
                    ApiErrorCode.EMAIL_ALREADY_REGISTERED,
                    "email"
                )
            }
            EmailVerificationPurpose.PASSWORD_RESET -> {
                if (user == null) {
                    throw CustomException(
                        HttpStatus.NOT_FOUND,
                        "가입되지 않은 이메일입니다.",
                        ApiErrorCode.USER_NOT_FOUND,
                        "email"
                    )
                }
                if (!user.authProvider.supportsPassword) {
                    throw CustomException(
                        HttpStatus.CONFLICT,
                        "Google 전용 계정은 비밀번호 재설정을 사용할 수 없습니다.",
                        ApiErrorCode.AUTH_METHOD_NOT_SUPPORTED,
                        "email"
                    )
                }
            }
        }
    }

    private fun sendMail(email: String, purpose: EmailVerificationPurpose, code: String) {
        val purposeName = when (purpose) {
            EmailVerificationPurpose.SIGNUP -> "회원가입"
            EmailVerificationPurpose.PASSWORD_RESET -> "비밀번호 재설정"
        }
        val message = SimpleMailMessage().apply {
            setTo(email)
            subject = "[찍먹] ${purposeName} 이메일 인증번호입니다."
            text = "안녕하세요!\n${purposeName} 인증번호는 [$code] 입니다.\n5분 안에 입력해주세요."
        }
        mailSender.send(message)
    }

}
