package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.ProductFoodCategory
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.security.core.Authentication
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/products")
class SafeProductRecommendationController(
    private val service: SafeProductRecommendationService
) {
    @GetMapping("/safe-recommendations")
    fun getSafeRecommendations(
        @RequestParam(defaultValue = "20") limit: Int,
        @RequestParam(required = false) cursor: String?,
        @RequestParam(required = false) seed: Long?,
        @RequestParam(required = false) excludeBarcodes: List<String>?,
        @RequestParam(required = false) categories: List<String>?,
        @RequestParam(required = false) userId: Long?,
        authentication: Authentication?
    ): ResponseEntity<*> {
        val requestedCategories = splitRequestValues(categories)
        val unknownCategories = requestedCategories.filter { ProductFoodCategory.resolve(it) == null }
        if (unknownCategories.isNotEmpty()) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "지원하지 않는 식품 카테고리가 있습니다: ${unknownCategories.joinToString()}"
            )
        }
        val targetUserId = validatedUserId(userId, authentication)
        val result = try {
            service.recommend(
                userId = targetUserId,
                limit = limit,
                cursor = cursor,
                seed = seed,
                excludedBarcodes = splitRequestValues(excludeBarcodes).toSet(),
                requestedCategories = requestedCategories.mapNotNull(ProductFoodCategory::resolve).toSet()
            )
        } catch (exception: IllegalArgumentException) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                exception.message ?: "추천 요청값이 올바르지 않습니다."
            )
        }
        val message = when (result.recommendationMode) {
            SafeRecommendationMode.PREFERENCE_MATCHED -> "맞춤 안심 상품 추천 성공"
            SafeRecommendationMode.MIXED -> "선호 조건을 우선 적용하고 일부 완화한 안심 상품 추천 성공"
            SafeRecommendationMode.PREFERENCE_RELAXED -> "안전 조건을 유지하고 선호 조건을 완화한 상품을 추천합니다."
            SafeRecommendationMode.EMPTY -> "현재 범위에서 안전성이 확인된 추천 상품을 찾지 못했습니다."
        }
        return ResponseEntity.ok(mapOf("message" to message, "data" to result))
    }

    private fun splitRequestValues(values: List<String>?): List<String> = values.orEmpty()
        .flatMap { it.split(',') }
        .map(String::trim)
        .filter(String::isNotEmpty)
        .distinct()

    private fun validatedUserId(requestedUserId: Long?, authentication: Authentication?): Long {
        if (authentication == null || authentication.principal == "anonymousUser") {
            throw CustomException(HttpStatus.UNAUTHORIZED, "맞춤 안심 상품 추천을 사용하려면 로그인이 필요합니다.")
        }
        val currentUserId = authentication.principal.toString().toLongOrNull()
            ?: throw CustomException(HttpStatus.UNAUTHORIZED, "로그인 정보가 올바르지 않습니다.")
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }
        val targetUserId = requestedUserId ?: currentUserId
        if (targetUserId != currentUserId && !isAdmin) {
            throw CustomException(HttpStatus.FORBIDDEN, "다른 사용자의 기준으로 추천받을 수 없습니다.")
        }
        return targetUserId
    }
}
