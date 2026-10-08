package org.jjikmuk.backend.domain.auth

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.EnumType
import jakarta.persistence.Enumerated
import jakarta.persistence.GeneratedValue
import jakarta.persistence.GenerationType
import jakarta.persistence.Id
import jakarta.persistence.Table
import jakarta.persistence.UniqueConstraint
import java.time.LocalDateTime

@Entity
@Table(
    name = "email_verification_grants",
    uniqueConstraints = [UniqueConstraint(
        name = "uk_email_verification_grants_email_purpose",
        columnNames = ["email", "purpose"]
    )]
)
class EmailVerificationGrant(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    @Column(nullable = false)
    val email: String,

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    val purpose: EmailVerificationPurpose,

    @Column(nullable = false, length = 64)
    var tokenHash: String,

    @Column(nullable = false)
    var expiredAt: LocalDateTime,

    @Column(nullable = false)
    var createdAt: LocalDateTime
)
