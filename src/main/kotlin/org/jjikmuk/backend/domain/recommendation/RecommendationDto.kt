package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.ProductDataOrigin

enum class SafetyStatus {
    PASS,
    DANGER,
    UNKNOWN
}

data class SafetyDecision(
    val status: SafetyStatus,
    val conflictingAllergens: List<String>,
    val evidenceSources: List<String>,
    val evidenceLevel: AllergyEvidenceLevel,
    val confidence: Double?,
    val message: String
)

enum class DietConstraintStatus {
    PASS,
    MISMATCH,
    UNKNOWN
}

enum class RecommendationResultMode {
    VERIFIED,
    RELAXED_SAFE,
    VERIFICATION_REQUIRED,
    ACTION_REQUIRED
}

enum class RecommendationTier {
    VERIFIED,
    RELAXED_SAFE,
    VERIFICATION_REQUIRED
}

enum class RecommendationFallbackReason {
    MINIMUM_SIMILARITY_RELAXED,
    INSUFFICIENT_VERIFICATION_DATA,
    NO_RETURNABLE_CANDIDATE
}

data class DietConstraintDecision(
    val status: DietConstraintStatus,
    val requiredFilters: List<String>,
    val satisfiedFilters: List<String>,
    val failedFilters: List<String>,
    val uncertainFilters: List<String>,
    val evidenceOrigin: ProductDataOrigin,
    val confidence: Double?,
    val message: String
)

data class UserRecommendationContext(
    val userId: Long,
    val allergies: List<String>,
    val requiredDietFilters: List<String>,
    val dislikedIngredients: List<String>,
    val usableHistorySignals: Int,
    val usableHistoryProducts: Int,
    val positiveHistoryWeight: Double,
    val negativeHistoryWeight: Double
)

data class RecommendationExclusionSummary(
    val missingProduct: Int,
    val lowSimilarity: Int,
    val danger: Int,
    val unknownSafety: Int,
    val dietMismatch: Int,
    val dietUnknown: Int,
    val dislikedIngredient: Int
)

data class RecommendationScoreBreakdown(
    val similarityWeight: Double,
    val preferenceWeight: Double,
    val dataQualityWeight: Double,
    val similarityContribution: Double,
    val preferenceContribution: Double?,
    val dataQualityContribution: Double
)

data class RecommendationTiming(
    val neighborLookupMicros: Long,
    val productFetchMicros: Long,
    val historyFetchMicros: Long,
    val rankingMicros: Long,
    val totalMicros: Long
)

data class ProductDataEvidence(
    val allergyEvidenceLevel: AllergyEvidenceLevel,
    val allergyConfidence: Double?,
    val nutritionOrigin: ProductDataOrigin,
    val nutritionConfidence: Double?,
    val dietaryOrigin: ProductDataOrigin,
    val dietaryConfidence: Double?
)

data class RecommendedProduct(
    val product: Product,
    val originalRank: Int,
    val baseSimilarityScore: Double,
    val preferenceScore: Double?,
    val dataQualityScore: Double,
    val finalScore: Double,
    val mmrScore: Double,
    val safety: SafetyDecision,
    val dietConstraints: DietConstraintDecision,
    val dataEvidence: ProductDataEvidence,
    val scoreBreakdown: RecommendationScoreBreakdown,
    val reasons: List<String>,
    val recommendationTier: RecommendationTier = RecommendationTier.VERIFIED,
    val verificationRequired: Boolean = false,
    val warnings: List<String> = emptyList(),
    val requiredActions: List<String> = emptyList()
)

data class ProductRecommendationResponse(
    val requestId: String,
    val referenceProduct: Product,
    val referenceSafety: SafetyDecision,
    val userContext: UserRecommendationContext,
    val policyVersion: String,
    val modelVersion: String,
    val precomputedCandidateCount: Int,
    val eligibleCandidateCount: Int,
    val requestedLimit: Int,
    val minSimilarityScore: Double,
    val items: List<RecommendedProduct>,
    val excluded: RecommendationExclusionSummary,
    val timing: RecommendationTiming,
    val fallbackItems: List<RecommendedProduct> = emptyList(),
    val resultMode: RecommendationResultMode = if (items.isEmpty()) {
        RecommendationResultMode.ACTION_REQUIRED
    } else {
        RecommendationResultMode.VERIFIED
    },
    val fallbackCandidateCount: Int = 0,
    val fallbackReason: RecommendationFallbackReason? = null,
    val requiredActions: List<String> = emptyList(),
    val notice: String = "추천 결과는 표기 데이터 기반이며 실제 포장 라벨과 의료 전문가의 지침을 우선해야 합니다."
)
