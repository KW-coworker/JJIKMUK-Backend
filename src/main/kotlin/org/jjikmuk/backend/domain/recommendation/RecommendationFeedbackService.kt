package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.dao.DuplicateKeyException
import org.springframework.http.HttpStatus
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.LocalDateTime
import java.util.UUID

enum class RecommendationFeedbackType {
    IMPRESSION,
    CLICK,
    ACCEPT,
    DISMISS;

    companion object {
        fun fromRequest(value: String): RecommendationFeedbackType? = entries.firstOrNull {
            it.name.equals(value.trim(), ignoreCase = true)
        }
    }
}

data class RecommendationFeedbackRequest(
    val requestId: String,
    val productBarcode: String,
    val feedbackType: String,
    val rankPosition: Int? = null
)

data class RecommendationFeedbackResponse(
    val requestId: String,
    val productBarcode: String,
    val feedbackType: String,
    val rankPosition: Int?,
    val createdAt: LocalDateTime
)

@Service
class RecommendationFeedbackService(
    private val jdbcTemplate: JdbcTemplate,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository
) {
    @Transactional
    fun record(userId: Long, request: RecommendationFeedbackRequest): RecommendationFeedbackResponse {
        val requestId = request.requestId.trim()
        runCatching { UUID.fromString(requestId) }.getOrElse {
            throw CustomException(HttpStatus.BAD_REQUEST, "requestId 형식이 올바르지 않습니다.")
        }
        if (!userRepository.existsById(userId)) {
            throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")
        }
        val barcode = request.productBarcode.trim()
        if (!productRepository.existsById(barcode)) {
            throw CustomException(HttpStatus.NOT_FOUND, "해당 추천 상품($barcode)을 찾을 수 없습니다.")
        }
        val feedbackType = RecommendationFeedbackType.fromRequest(request.feedbackType)
            ?: throw CustomException(
                HttpStatus.BAD_REQUEST,
                "feedbackType은 ${RecommendationFeedbackType.entries.joinToString()} 중 하나여야 합니다."
            )
        request.rankPosition?.let { rank ->
            if (rank !in 1..20) throw CustomException(HttpStatus.BAD_REQUEST, "rankPosition은 1~20 범위여야 합니다.")
        }
        val createdAt = LocalDateTime.now()
        try {
            jdbcTemplate.update(
                """
                INSERT INTO product_recommendation_feedback
                    (request_id, user_id, product_barcode, feedback_type, rank_position, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """.trimIndent(),
                requestId,
                userId,
                barcode,
                feedbackType.name,
                request.rankPosition,
                createdAt
            )
        } catch (_: DuplicateKeyException) {
            throw CustomException(HttpStatus.CONFLICT, "같은 추천 피드백이 이미 기록되었습니다.")
        }
        return RecommendationFeedbackResponse(
            requestId = requestId,
            productBarcode = barcode,
            feedbackType = feedbackType.name,
            rankPosition = request.rankPosition,
            createdAt = createdAt
        )
    }

    @Transactional
    fun deleteByUserId(userId: Long) {
        jdbcTemplate.update("DELETE FROM product_recommendation_feedback WHERE user_id = ?", userId)
        jdbcTemplate.update("UPDATE product_recommendation_logs SET user_id = NULL WHERE user_id = ?", userId)
    }
}
