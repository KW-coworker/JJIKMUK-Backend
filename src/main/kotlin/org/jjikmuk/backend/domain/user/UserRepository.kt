package org.jjikmuk.backend.domain.user

import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock
import org.springframework.data.jpa.repository.Query
import jakarta.persistence.LockModeType

interface UserRepository : JpaRepository<User, Long> {
    // Resolve identities without caching an unlocked entity before authentication writes.
    @Query("select u.id from User u where u.email = :email")
    fun idForEmail(email: String): Long?
    @Query("select u.id from User u where u.googleSubject = :subject")
    fun idForGoogleSubject(subject: String): Long?
    fun findByGoogleSubject(googleSubject: String): User?
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select u from User u where u.id = :id")
    fun lockById(id: Long): User?
    fun findByEmail(email: String): User?
    fun existsByNicknameIgnoreCase(nickname: String): Boolean
    fun existsByNicknameIgnoreCaseAndIdNot(nickname: String, id: Long): Boolean
}
