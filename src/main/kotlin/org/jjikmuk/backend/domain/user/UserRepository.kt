package org.jjikmuk.backend.domain.user

import org.springframework.data.jpa.repository.JpaRepository

interface UserRepository : JpaRepository<User, Long> {
    fun findByEmail(email: String): User?
    fun existsByNicknameIgnoreCase(nickname: String): Boolean
    fun existsByNicknameIgnoreCaseAndIdNot(nickname: String, id: Long): Boolean
}
