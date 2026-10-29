package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.AllergySafetyService
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductFilter
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.DietPreferenceCatalog
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
        return selectedDietFilters(user) + healthConstraintFilters(user)
    }

    /** The profile has no hard/soft distinction: selected diets are mandatory in both APIs. */
    fun selectedDietFilters(user: User): Set<ProductFilter> =
        DietPreferenceCatalog.knownFilters(user.specialDiet)

    /** Disease-derived constraints remain hard constraints in every recommendation tier. */
    fun healthConstraintFilters(user: User): Set<ProductFilter> {
        val filters = linkedSetOf<ProductFilter>()
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

        val attributes = required.map { evaluateDietaryAttribute(product, it) }
        val byKey = attributes.associateBy(DietaryAttributeDecision::key)
        val failed = required.filter { byKey.getValue(it.key).status == DietaryAttributeStatus.NOT_MET }
        val uncertain = required.filter { byKey.getValue(it.key).status == DietaryAttributeStatus.UNKNOWN }
        val satisfied = required - failed.toSet() - uncertain.toSet()
        val status = when {
            failed.isNotEmpty() -> DietConstraintStatus.MISMATCH
            uncertain.isNotEmpty() -> DietConstraintStatus.UNKNOWN
            else -> DietConstraintStatus.PASS
        }
        val message = when (status) {
            DietConstraintStatus.NOT_EVALUATED -> "식단 조건을 검사하지 않았습니다."
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
            confidence = product.dietaryDataConfidence,
            message = message,
            attributes = attributes
        )
    }

    /** Boolean false alone is not evidence of a negative classification. Never invent confidence. */
    fun evaluateDietaryAttribute(product: Product, filter: ProductFilter): DietaryAttributeDecision {
        val confidence = product.dietaryDataConfidence
        // Raw ingredient contradictions override inferred flags AND absent/low confidence.
        // Allergy warnings may describe shared facilities; do not treat them as vegan ingredients.
        val ingredients = if (filter == ProductFilter.VEGAN) {
            VeganIngredientEvidence.inspect(product.rawMaterials)
        } else VeganIngredientEvidence.Findings(emptyList(), emptyList())
        val reason = when {
            ingredients.conflicts.isNotEmpty() -> DietaryAttributeReason.EXPLICIT_INGREDIENT_CONFLICT
            ingredients.uncertain.isNotEmpty() -> DietaryAttributeReason.AMBIGUOUS_INGREDIENT_EVIDENCE
            product.dietaryDataOrigin in setOf(ProductDataOrigin.UNKNOWN, ProductDataOrigin.IMPUTED) ->
                DietaryAttributeReason.UNRELIABLE_ORIGIN
            confidence == null || !confidence.isFinite() || confidence < MIN_DIETARY_CONFIDENCE ->
                DietaryAttributeReason.INSUFFICIENT_CONFIDENCE
            !hasConstraintEvidence(product, filter) -> DietaryAttributeReason.MISSING_OR_INVALID_EVIDENCE
            else -> DietaryAttributeReason.STORED_CLASSIFICATION
        }
        return DietaryAttributeDecision(
            key = filter.key,
            status = when {
                reason == DietaryAttributeReason.EXPLICIT_INGREDIENT_CONFLICT -> DietaryAttributeStatus.NOT_MET
                reason != DietaryAttributeReason.STORED_CLASSIFICATION -> DietaryAttributeStatus.UNKNOWN
                filter.matches(product) -> DietaryAttributeStatus.MET
                else -> DietaryAttributeStatus.NOT_MET
            },
            storedValue = filter.matches(product),
            evidenceOrigin = product.dietaryDataOrigin,
            confidence = confidence,
            reason = reason,
            ingredientEvidence = ingredients.conflicts.ifEmpty { ingredients.uncertain }
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

    private fun hasConstraintEvidence(product: Product, filter: ProductFilter): Boolean = when (filter) {
        ProductFilter.VEGAN,
        ProductFilter.LACTO_VEGETARIAN,
        ProductFilter.OVO_VEGETARIAN,
        ProductFilter.LACTO_OVO_VEGETARIAN,
        ProductFilter.PESCATARIAN,
        ProductFilter.POLLOTARIAN,
        ProductFilter.GLUTEN_FREE -> normalize(product.rawMaterials) !in MISSING_INGREDIENT_MARKERS
        ProductFilter.LOW_SUGAR -> hasNutrientEvidence(product, product.sugarG)
        ProductFilter.LOW_SODIUM -> hasNutrientEvidence(product, product.sodiumMg)
        ProductFilter.LOW_CALORIE -> hasNutrientEvidence(product, product.energyKcal)
        ProductFilter.LOW_FAT -> hasNutrientEvidence(product, product.fatG)
        ProductFilter.HIGH_PROTEIN -> hasNutrientEvidence(product, product.proteinG)
    }

    private fun hasNutrientEvidence(product: Product, value: Double?): Boolean =
        value != null && value.isFinite() && value >= 0.0 &&
            product.nutritionDataOrigin in setOf(
                ProductDataOrigin.SOURCE, ProductDataOrigin.NORMALIZED, ProductDataOrigin.CALCULATED
            )

    private companion object {
        const val MIN_DIETARY_CONFIDENCE = 0.50
        val MISSING_INGREDIENT_MARKERS = setOf("", "null", "none", "na", "unknown", "정보없음", "미상", "미입력", "해당없음")
    }
}
