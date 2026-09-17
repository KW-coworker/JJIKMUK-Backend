package org.jjikmuk.backend.domain.history

import org.springframework.data.jpa.repository.JpaRepository
import org.jjikmuk.backend.domain.product.Product
import java.time.LocalDateTime

data class HistoryResponse(
    val id: Long,
    val actionType: String,
    val scannedAt: LocalDateTime,
    val product: Product? // 바코드를 기반으로 찾아낸 실제 상품 정보 전체
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
