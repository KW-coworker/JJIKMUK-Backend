package org.jjikmuk.backend.domain.auth

import jakarta.persistence.LockModeType
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock

interface EmailVerificationRepository : JpaRepository<EmailVerification, Long> {
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    fun findByEmailAndPurpose(email: String, purpose: EmailVerificationPurpose): EmailVerification?
}
