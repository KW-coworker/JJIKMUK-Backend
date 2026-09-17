package org.jjikmuk.backend.domain.auth

import org.springframework.data.jpa.repository.JpaRepository

interface EmailVerificationRepository : JpaRepository<EmailVerification, Long> {
    fun findByEmail(email: String): EmailVerification?
}