package org.jjikmuk.backend.domain.history

import org.springframework.data.jpa.repository.JpaRepository
import org.jjikmuk.backend.domain.product.Product
import java.time.LocalDateTime

data class HistoryResponse(
    val id: Long,
    val actionType: String,
    val scannedAt: LocalDateTime,
    val product: Product?, // Current display data, not a reconstruction of the historical label.
    val productId: Long? = null,
    val attributeSnapshotId: Long? = null,
    val identityStatus: String = "LEGACY_VERSION_UNKNOWN"
)

interface HistoryRepository : JpaRepository<History, Long> {
    fun findByUserIdOrderByCreatedAtDesc(userId: Long): List<History>
    fun findByUserIdAndActionTypeOrderByCreatedAtDesc(
        userId: Long,
        actionType: UserActionType
    ): List<History>
    fun findTop200ByUserIdOrderByCreatedAtDesc(userId: Long): List<History>
    fun deleteByUserId(userId: Long)
}
