package org.jjikmuk.backend.domain.history

import org.jjikmuk.backend.domain.product.ProductRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import java.time.LocalDateTime

data class UserActionEventRequest(
    val barcode: String,
    val actionType: String
)

data class UserActionEventResponse(
    val eventId: Long,
    val barcode: String,
    val actionType: String,
    val createdAt: LocalDateTime
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
            val product = productRepository.findFirstByBarcode(history.barcode)

            HistoryResponse(
                id = history.id!!,
                actionType = history.actionType.name,
                scannedAt = history.createdAt,
                product = product // 여기서 합체!
            )
        }
    }

    @Transactional
    fun recordAction(userId: Long, request: UserActionEventRequest): UserActionEventResponse {
        val barcode = request.barcode.trim()
        if (barcode.isBlank() || barcode.length > 32) {
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
        if (!productRepository.existsById(barcode)) {
            throw CustomException(HttpStatus.NOT_FOUND, "해당 바코드($barcode)의 제품을 찾을 수 없습니다.")
        }

        val saved = historyRepository.save(
            History(user = user, barcode = barcode, actionType = actionType)
        )
        return UserActionEventResponse(
            eventId = requireNotNull(saved.id),
            barcode = saved.barcode,
            actionType = saved.actionType.name,
            createdAt = saved.createdAt
        )
    }
}
