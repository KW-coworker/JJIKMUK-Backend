package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.AllergySafetyService
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductFilter
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.user.User
import org.springframework.stereotype.Component
import java.text.Normalizer

@Component
class RecommendationPolicy(
    private val allergySafetyService: AllergySafetyService = AllergySafetyService()
) {
    fun allergyProfileTerms(value: String?): List<String> {
        val profile = AllergyCatalog.parse(value)
        return profile.ids.map { it.id } + profile.unknownTerms
    }

    fun profileTerms(value: String?): List<String> = value
        ?.split(Regex("[,;/|\\n]+"))
        ?.map(String::trim)
        ?.filter(String::isNotEmpty)
        ?.distinct()
        .orEmpty()

    fun requiredFilters(user: User): Set<ProductFilter> {
        val filters = ProductFilter.detectInText(user.specialDiet).toMutableSet()
        val diseases = normalize(user.diseases)
        if ("당뇨" in diseases || "혈당" in diseases) filters += ProductFilter.LOW_SUGAR
        if ("고혈압" in diseases || "혈압" in diseases) filters += ProductFilter.LOW_SODIUM
        if ("고지혈" in diseases || "이상지질" in diseases || "심혈관" in diseases) {
            filters += ProductFilter.LOW_FAT
        }
        if ("비만" in diseases || "체중조절" in diseases || "다이어트" in diseases) {
            filters += ProductFilter.LOW_CALORIE
        }
        if ("셀리악" in diseases || "글루텐" in diseases) filters += ProductFilter.GLUTEN_FREE
        return filters
    }

    fun evaluateSafety(product: Product, allergies: List<String>): SafetyDecision =
        allergySafetyService.evaluate(product, allergies)

    fun evaluateDietConstraints(
        product: Product,
        requiredFilters: Set<ProductFilter>
    ): DietConstraintDecision {
        val required = requiredFilters.sortedBy(ProductFilter::key)
        if (required.isEmpty()) {
            return DietConstraintDecision(
                status = DietConstraintStatus.PASS,
                requiredFilters = emptyList(),
                satisfiedFilters = emptyList(),
                failedFilters = emptyList(),
                uncertainFilters = emptyList(),
                evidenceOrigin = product.dietaryDataOrigin,
                confidence = product.dietaryDataConfidence,
                message = "등록된 필수 식단 조건이 없습니다."
            )
        }

        val failed = required.filterNot { it.matches(product) }
        val effectiveConfidence = product.dietaryDataConfidence
            ?: inferredDietaryConfidence(product)
        val uncertain = if (failed.isEmpty()) {
            required.filter { filter ->
                product.dietaryDataOrigin == ProductDataOrigin.UNKNOWN ||
                    effectiveConfidence == null ||
                    effectiveConfidence < MIN_DIETARY_CONFIDENCE ||
                    !hasConstraintEvidence(product, filter)
            }
        } else {
            emptyList()
        }
        val satisfied = required - failed.toSet() - uncertain.toSet()
        val status = when {
            failed.isNotEmpty() -> DietConstraintStatus.MISMATCH
            uncertain.isNotEmpty() -> DietConstraintStatus.UNKNOWN
            else -> DietConstraintStatus.PASS
        }
        val message = when (status) {
            DietConstraintStatus.MISMATCH ->
                "필수 식단 조건을 충족하지 않습니다: ${failed.joinToString { it.label }}"
            DietConstraintStatus.UNKNOWN ->
                "식단 조건 판정에 필요한 근거가 부족합니다: ${uncertain.joinToString { it.label }}"
            DietConstraintStatus.PASS ->
                "필수 식단 조건을 모두 충족합니다: ${required.joinToString { it.label }}"
        }
        return DietConstraintDecision(
            status = status,
            requiredFilters = required.map(ProductFilter::key),
            satisfiedFilters = satisfied.map(ProductFilter::key),
            failedFilters = failed.map(ProductFilter::key),
            uncertainFilters = uncertain.map(ProductFilter::key),
            evidenceOrigin = product.dietaryDataOrigin,
            confidence = effectiveConfidence,
            message = message
        )
    }

    fun containsDislikedIngredient(product: Product, dislikedIngredients: List<String>): Boolean {
        if (dislikedIngredients.isEmpty()) return false
        val evidence = normalize(
            listOfNotNull(product.rawMaterials, product.allergy, product.allergyWarning)
                .joinToString(" ")
        )
        return dislikedIngredients.any { ingredient ->
            val normalized = normalize(ingredient)
            normalized.length >= 2 && evidence.contains(normalized)
        }
    }

    fun dataQualityScore(product: Product): Double {
        val checks = listOf(
            !product.rawMaterials.isNullOrBlank(),
            !product.allergy.isNullOrBlank() || !product.allergyWarning.isNullOrBlank(),
            !product.cleanProductName.isNullOrBlank() || !product.productName.isNullOrBlank(),
            !product.manufacturer.isNullOrBlank(),
            !product.imageUrl.isNullOrBlank(),
            listOf(
                product.energyKcal,
                product.carbsG,
                product.proteinG,
                product.fatG,
                product.sugarG,
                product.sodiumMg
            ).count { it != null } >= 3
        )
        return checks.count { it }.toDouble() / checks.size
    }

    private fun normalize(value: String?): String = Normalizer
        .normalize(value.orEmpty(), Normalizer.Form.NFKC)
        .lowercase()
        .filter { it.isLetterOrDigit() }

    private fun inferredDietaryConfidence(product: Product): Double? {
        val nutritionCount = listOf(
            product.energyKcal,
            product.carbsG,
            product.proteinG,
            product.fatG,
            product.sugarG,
            product.sodiumMg
        ).count { it != null }
        return when {
            !product.rawMaterials.isNullOrBlank() && nutritionCount >= 3 -> 0.80
            !product.rawMaterials.isNullOrBlank() -> 0.70
            nutritionCount >= 3 -> 0.60
            else -> null
        }
    }

    private fun hasConstraintEvidence(product: Product, filter: ProductFilter): Boolean = when (filter) {
        ProductFilter.VEGAN,
        ProductFilter.LACTO_VEGETARIAN,
        ProductFilter.OVO_VEGETARIAN,
        ProductFilter.LACTO_OVO_VEGETARIAN,
        ProductFilter.PESCATARIAN,
        ProductFilter.POLLOTARIAN,
        ProductFilter.GLUTEN_FREE -> !product.rawMaterials.isNullOrBlank()
        ProductFilter.LOW_SUGAR -> product.sugarG != null
        ProductFilter.LOW_SODIUM -> product.sodiumMg != null
        ProductFilter.LOW_CALORIE -> product.energyKcal != null
        ProductFilter.LOW_FAT -> product.fatG != null
        ProductFilter.HIGH_PROTEIN -> product.proteinG != null
    }

    private companion object {
        const val MIN_DIETARY_CONFIDENCE = 0.50
    }
}
