package org.jjikmuk.backend.domain.history

import org.jjikmuk.backend.domain.product.ProductRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import java.time.LocalDateTime
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.user.AnalysisSelectionService
import org.jjikmuk.backend.domain.user.validateListPage
import org.springframework.data.domain.PageRequest

data class UserActionEventRequest(
    val barcode: String? = null,
    val actionType: String,
    val productId: Long? = null,
    val analysisMode: String? = null,
    val includeSelf: Boolean? = null,
    val familyProfileIds: List<Long>? = null
)

data class UserActionEventResponse(
    val eventId: Long,
    val barcode: String,
    val actionType: String,
    val createdAt: LocalDateTime,
    val productId: Long? = null,
    val attributeSnapshotId: Long? = null,
    val analysisMode: String = "self",
    val personalizationAllowed: Boolean = true
)

data class RecentProductPage(val items: List<HistoryResponse>, val page: Int, val size: Int, val hasNext: Boolean)

@Service
@Transactional(readOnly = true)
class HistoryService(
    private val historyRepository: HistoryRepository,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository,
    private val analysisSelection: AnalysisSelectionService
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
                identityStatus = if (history.productId == null) "LEGACY_VERSION_UNKNOWN" else if (product == null) "NOT_IN_ACTIVE_DATASET" else "INTERNAL_ID",
                analysisMode = history.analysisMode,
                personalizationAllowed = history.personalizationAllowed
            )
        }
    }

    fun getRecentProducts(userId: Long, page: Int, size: Int): RecentProductPage {
        validateListPage(page, size)
        val rows = historyRepository.findRecentViews(userId,
            listOf(UserActionType.SCAN, UserActionType.DETAIL_VIEW), PageRequest.of(page, size))
        val ids = rows.content.mapNotNull { it.productId }.distinct()
        val byId = if (ids.isEmpty()) emptyMap() else productRepository.findAllByProductIdIn(ids).associateBy { it.productId }
        val barcodes = rows.content.filter { it.productId == null && !it.barcode.startsWith("NO_BARCODE_ROW_") }
            .map { it.barcode }.distinct()
        val byBarcode = if (barcodes.isEmpty()) emptyMap() else productRepository.findAllById(barcodes).associateBy(Product::barcode)
        return RecentProductPage(rows.content.map { row ->
            val product = if (row.productId != null) byId[row.productId] else byBarcode[row.barcode]
            HistoryResponse(requireNotNull(row.id), row.actionType.name, row.createdAt, product,
                row.productId, row.attributeSnapshotId,
                if (row.productId == null) "LEGACY_VERSION_UNKNOWN" else if (product == null) "NOT_IN_ACTIVE_DATASET" else "INTERNAL_ID",
                row.analysisMode, row.personalizationAllowed)
        }, page, size, rows.hasNext())
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
        val analysis = analysisSelection.resolve(userId, request.analysisMode, request.includeSelf, request.familyProfileIds)
        val product = if (request.productId != null) productRepository.findByProductId(request.productId)
            else productRepository.findFirstByBarcode(requireNotNull(barcode))
        if (product == null) throw CustomException(HttpStatus.NOT_FOUND, "해당 제품을 찾을 수 없습니다.")
        if (barcode != null && barcode != product.barcode) throw CustomException(HttpStatus.BAD_REQUEST, "productId와 barcode가 서로 다른 상품을 가리킵니다.")

        val saved = historyRepository.save(
            History(user = user, barcode = product.barcode, actionType = actionType,
                productId = product.productId, attributeSnapshotId = product.attributeSnapshotId,
                analysisMode = analysis.selection.mode, personalizationAllowed = analysis.personalHistoryAllowed)
        )
        return UserActionEventResponse(
            eventId = requireNotNull(saved.id),
            barcode = saved.barcode,
            actionType = saved.actionType.name,
            createdAt = saved.createdAt,
            productId = saved.productId,
            attributeSnapshotId = saved.attributeSnapshotId,
            analysisMode = saved.analysisMode,
            personalizationAllowed = saved.personalizationAllowed
        )
    }
}
