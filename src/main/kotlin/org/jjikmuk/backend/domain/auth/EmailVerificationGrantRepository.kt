package org.jjikmuk.backend.domain.auth

import jakarta.persistence.LockModeType
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock

interface EmailVerificationGrantRepository : JpaRepository<EmailVerificationGrant, Long> {
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    fun findByEmailAndPurpose(email: String, purpose: EmailVerificationPurpose): EmailVerificationGrant?
    fun deleteByEmailAndPurpose(email: String, purpose: EmailVerificationPurpose)
}
