package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.security.core.Authentication
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/recommendations")
class RecommendationController(
    private val recommendationService: RecommendationService,
    private val feedbackService: RecommendationFeedbackService
) {
    @PostMapping("/feedback")
    fun recordFeedback(
        @RequestBody request: RecommendationFeedbackRequest,
        authentication: Authentication?
    ): ResponseEntity<*> {
        val userId = validatedUserId(null, authentication)
        val data = feedbackService.record(userId, request)
        return ResponseEntity.ok(mapOf("message" to "추천 피드백 기록 성공", "data" to data))
    }

    @GetMapping("/products/{barcode}")
    fun recommendAlternatives(
        @PathVariable barcode: String,
        @RequestParam(required = false) userId: Long?,
        @RequestParam(defaultValue = "10") limit: Int,
        @RequestParam(defaultValue = "0.2") minScore: Double,
        authentication: Authentication?
    ): ResponseEntity<*> {
        val targetUserId = validatedUserId(userId, authentication)
        val data = try {
            recommendationService.recommendAlternatives(barcode, targetUserId, limit, minScore)
        } catch (exception: IllegalArgumentException) {
            throw CustomException(HttpStatus.BAD_REQUEST, exception.message ?: "추천 요청값이 올바르지 않습니다.")
        }
        return ResponseEntity.ok(
            mapOf(
                "message" to when (data.resultMode) {
                    RecommendationResultMode.VERIFIED -> "개인화 대체 상품 추천 성공"
                    RecommendationResultMode.RELAXED_SAFE ->
                        "안전·식단 조건을 유지하고 유사도 기준을 완화한 대안을 찾았습니다."
                    RecommendationResultMode.VERIFICATION_REQUIRED ->
                        "안전성을 확정할 수 없어 제품 라벨 확인이 필요한 대안을 표시합니다."
                    RecommendationResultMode.ACTION_REQUIRED ->
                        "위험 상품을 대신 표시하지 않았습니다. 제품 라벨 확인 또는 다른 상품 선택이 필요합니다."
                },
                "data" to data
            )
        )
    }

    private fun validatedUserId(requestedUserId: Long?, authentication: Authentication?): Long {
        if (authentication == null || authentication.principal == "anonymousUser") {
            throw CustomException(HttpStatus.UNAUTHORIZED, "개인화 추천을 사용하려면 로그인이 필요합니다.")
        }
        val currentUserId = authentication.principal.toString().toLong()
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }
        val targetUserId = requestedUserId ?: currentUserId
        if (targetUserId != currentUserId && !isAdmin) {
            throw CustomException(HttpStatus.FORBIDDEN, "다른 사용자의 기준으로 추천받을 수 없습니다.")
        }
        return targetUserId
    }
}
