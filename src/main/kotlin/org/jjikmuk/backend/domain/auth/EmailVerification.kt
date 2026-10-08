package org.jjikmuk.backend.domain.auth

import jakarta.persistence.*
import java.time.LocalDateTime

@Entity
@Table(
    name = "email_verifications",
    uniqueConstraints = [UniqueConstraint(
        name = "uk_email_verifications_email_purpose",
        columnNames = ["email", "purpose"]
    )]
)
class EmailVerification(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    @Column(nullable = false)
    val email: String,

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    val purpose: EmailVerificationPurpose,

    @Column(nullable = false)
    var code: String,

    @Column(nullable = false)
    var expiredAt: LocalDateTime,

    @Column(nullable = false)
    var sentAt: LocalDateTime,

    @Column(nullable = false)
    var sendCount: Int = 1,

    @Column(nullable = false)
    var failedAttempts: Int = 0
)
