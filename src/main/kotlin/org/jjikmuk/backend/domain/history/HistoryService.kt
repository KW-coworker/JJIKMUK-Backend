package org.jjikmuk.backend.domain.history

import org.jjikmuk.backend.domain.product.ProductRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import java.time.LocalDateTime

data class UserActionEventRequest(
    val barcode: String? = null,
    val actionType: String,
    val productId: Long? = null
)

data class UserActionEventResponse(
    val eventId: Long,
    val barcode: String,
    val actionType: String,
    val createdAt: LocalDateTime,
    val productId: Long? = null,
    val attributeSnapshotId: Long? = null
)

@Service
@Transactional(readOnly = true)
class HistoryService(
    private val historyRepository: HistoryRepository,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository
) {
    fun getUserHistory(userId: Long): List<HistoryResponse> {
        // 1. 해당 유저의 기록을 최신순으로 가져옵니다.
        val histories = historyRepository.findByUserIdOrderByCreatedAtDesc(userId)

        // 2. 기록 속 바코드를 이용해 상품 정보를 찾고, 아까 만든 DTO(바구니)에 담아 반환합니다.
        return histories.map { history ->
            val internalId = history.productId
            val product = if (internalId != null) productRepository.findByProductId(internalId)
                else if (history.barcode.startsWith("NO_BARCODE_ROW_")) null
                else productRepository.findFirstByBarcode(history.barcode)

            HistoryResponse(
                id = history.id!!,
                actionType = history.actionType.name,
                scannedAt = history.createdAt,
                product = product,
                productId = history.productId,
                attributeSnapshotId = history.attributeSnapshotId,
                identityStatus = if (history.productId == null) "LEGACY_VERSION_UNKNOWN" else if (product == null) "NOT_IN_ACTIVE_DATASET" else "INTERNAL_ID"
            )
        }
    }

    @Transactional
    fun recordAction(userId: Long, request: UserActionEventRequest): UserActionEventResponse {
        val barcode = request.barcode?.trim()
        if ((barcode == null && request.productId == null) || (barcode != null && (barcode.isBlank() || barcode.length > 32)) ||
            (request.productId != null && request.productId <= 0)) {
            throw CustomException(HttpStatus.BAD_REQUEST, "바코드 형식이 올바르지 않습니다.")
        }
        val actionType = UserActionType.fromRequest(request.actionType)
            ?: throw CustomException(
                HttpStatus.BAD_REQUEST,
                "지원하지 않는 행동 유형입니다. 지원값: ${UserActionType.supportedValues().joinToString()}"
            )
        val user = userRepository.findById(userId).orElseThrow {
            CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")
        }
        val product = if (request.productId != null) productRepository.findByProductId(request.productId)
            else productRepository.findFirstByBarcode(requireNotNull(barcode))
        if (product == null) throw CustomException(HttpStatus.NOT_FOUND, "해당 제품을 찾을 수 없습니다.")
        if (barcode != null && barcode != product.barcode) throw CustomException(HttpStatus.BAD_REQUEST, "productId와 barcode가 서로 다른 상품을 가리킵니다.")

        val saved = historyRepository.save(
            History(user = user, barcode = product.barcode, actionType = actionType,
                productId = product.productId, attributeSnapshotId = product.attributeSnapshotId)
        )
        return UserActionEventResponse(
            eventId = requireNotNull(saved.id),
            barcode = saved.barcode,
            actionType = saved.actionType.name,
            createdAt = saved.createdAt,
            productId = saved.productId,
            attributeSnapshotId = saved.attributeSnapshotId
        )
    }
}
