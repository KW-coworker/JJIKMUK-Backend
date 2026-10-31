package org.jjikmuk.backend.domain.auth

import jakarta.persistence.*
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock
import org.springframework.data.jpa.repository.Query
import java.time.Instant

@Entity @Table(name = "google_link_grants")
class GoogleLinkGrant(
    @Id @Column(length = 64) val tokenHash: String,
    @Column(nullable = false) val userId: Long,
    @Column(nullable = false, length = 255) val googleSubject: String,
    @Column(nullable = false) val tokenVersion: Int,
    @Column(nullable = false) val expiresAt: Instant,
    @Column(nullable = false) var attempts: Int = 0,
    var consumedAt: Instant? = null
)
interface GoogleLinkGrantRepository : JpaRepository<GoogleLinkGrant, String> {
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select g from GoogleLinkGrant g where g.tokenHash = :hash")
    fun lockByHash(hash: String): GoogleLinkGrant?
    @Query("select g.userId from GoogleLinkGrant g where g.tokenHash = :hash")
    fun ownerForHash(hash: String): Long?
    fun deleteByUserId(userId: Long)
}
