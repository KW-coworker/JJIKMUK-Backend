package org.jjikmuk.backend.domain.history

import org.springframework.data.jpa.repository.JpaRepository
import org.jjikmuk.backend.domain.product.Product
import java.time.LocalDateTime
import org.springframework.data.domain.Pageable
import org.springframework.data.domain.Slice
import org.springframework.data.jpa.repository.Query

data class HistoryResponse(
    val id: Long,
    val actionType: String,
    val scannedAt: LocalDateTime,
    val product: Product?, // Current display data, not a reconstruction of the historical label.
    val productId: Long? = null,
    val attributeSnapshotId: Long? = null,
    val identityStatus: String = "LEGACY_VERSION_UNKNOWN",
    val analysisMode: String = "self",
    val personalizationAllowed: Boolean = true
)

interface HistoryRepository : JpaRepository<History, Long> {
    fun findByUserIdOrderByCreatedAtDesc(userId: Long): List<History>
    fun findByUserIdAndActionTypeOrderByCreatedAtDesc(
        userId: Long,
        actionType: UserActionType
    ): List<History>
    fun findTop200ByUserIdOrderByCreatedAtDesc(userId: Long): List<History>
    fun findTop200ByUserIdAndPersonalizationAllowedTrueOrderByCreatedAtDescIdDesc(userId: Long): List<History>

    // Latest actual view per stable ID (legacy rows remain barcode-scoped); likes are not views.
    @Query("""
        select h from History h
        where h.user.id = :userId and h.actionType in :actions
          and not exists (
            select n.id from History n
            where n.user.id = :userId and n.actionType in :actions
              and ((h.productId is not null and n.productId = h.productId)
                or (h.productId is null and n.productId is null and n.barcode = h.barcode))
              and (n.createdAt > h.createdAt or (n.createdAt = h.createdAt and n.id > h.id))
          )
        order by h.createdAt desc, h.id desc
    """)
    fun findRecentViews(userId: Long, actions: Collection<UserActionType>, pageable: Pageable): Slice<History>
    fun deleteByUserId(userId: Long)
}
