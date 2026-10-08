package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.Product

enum class SafeRecommendationMode {
    PREFERENCE_MATCHED,
    MIXED,
    PREFERENCE_RELAXED,
    EMPTY
}

data class SafeProductRecommendationItem(
    val product: Product,
    val safety: SafetyDecision,
    val healthConstraints: DietConstraintDecision,
    val preferences: DietConstraintDecision,
    val preferenceRelaxed: Boolean,
    val categoryIds: List<String>
)

data class SafeRecommendationCategoryGroup(
    val categoryId: String,
    val categoryName: String,
    val items: List<SafeProductRecommendationItem>
)

data class SafeRecommendationExclusionSummary(
    val danger: Int,
    val unknownSafety: Int,
    val dislikedIngredient: Int,
    val healthMismatch: Int,
    val healthUnknown: Int,
    val categoryMismatch: Int,
    val alreadyDeliveredOrDuplicate: Int
)

data class SafeProductRecommendationResponse(
    val requestId: String,
    val userId: Long,
    val seed: Long,
    val requestedLimit: Int,
    val returnedItemCount: Int,
    val returnedBarcodes: List<String>,
    val requestedCategoryIds: List<String>,
    val preferenceFilterIds: List<String>,
    val hardHealthFilterIds: List<String>,
    val recommendationMode: SafeRecommendationMode,
    val categories: List<SafeRecommendationCategoryGroup>,
    val nextCursor: String?,
    val hasNext: Boolean,
    val scannedCandidateCount: Int,
    val exclusions: SafeRecommendationExclusionSummary,
    val notice: String = "알레르기·주의성분·건강 조건을 우선 적용한 추천입니다. 실제 제품 포장 표시를 다시 확인해 주세요."
)
