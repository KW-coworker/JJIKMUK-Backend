package org.jjikmuk.backend.domain.auth

import jakarta.persistence.*
import java.time.LocalDateTime

@Entity
@Table(name = "email_verifications")
class EmailVerification(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    @Column(nullable = false)
    val email: String,

    @Column(nullable = false)
    var code: String, // 6자리 인증번호

    @Column(nullable = false)
    var expiredAt: LocalDateTime // 만료 시간 (예: 5분 뒤)
)