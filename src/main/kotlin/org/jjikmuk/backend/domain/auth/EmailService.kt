package org.jjikmuk.backend.domain.auth

import org.springframework.mail.SimpleMailMessage
import org.springframework.mail.javamail.JavaMailSender
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.LocalDateTime
import kotlin.random.Random

@Service
class EmailService(
    private val mailSender: JavaMailSender,
    private val emailVerificationRepository: EmailVerificationRepository
) {
    @Transactional
    fun sendVerificationCode(email: String) {
        // 🚀 6자리 -> 4자리 난수(인증번호)로 변경! (1000 ~ 9999)
        val code = Random.nextInt(1000, 9999).toString()

        val expiredAt = LocalDateTime.now().plusMinutes(5)
        var verification = emailVerificationRepository.findByEmail(email)

        if (verification != null) {
            verification.code = code
            verification.expiredAt = expiredAt
        } else {
            verification = EmailVerification(email = email, code = code, expiredAt = expiredAt)
        }
        emailVerificationRepository.save(verification)

        val message = SimpleMailMessage()
        message.setTo(email)
        message.subject = "[찍먹] 이메일 인증번호입니다."
        message.text = "안녕하세요!\n요청하신 인증번호는 [$code] 입니다.\n5분 안에 입력해주세요."

        mailSender.send(message)
    }
}