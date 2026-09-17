package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductFilter
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.user.User
import org.springframework.stereotype.Component
import java.text.Normalizer

@Component
class RecommendationPolicy {
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

    fun evaluateSafety(product: Product, allergies: List<String>): SafetyDecision {
        val evidenceParts = listOfNotNull(
            product.allergyWarning?.takeIf(String::isNotBlank)?.let { "allergy_warning" to it },
            product.allergy?.takeIf(String::isNotBlank)?.let { "allergy" to it },
            product.rawMaterials?.takeIf(String::isNotBlank)?.let { "raw_materials" to it }
        )
        val evidenceSources = evidenceParts.map { it.first }

        if (allergies.isEmpty()) {
            return SafetyDecision(
                status = SafetyStatus.PASS,
                conflictingAllergens = emptyList(),
                evidenceSources = evidenceSources,
                evidenceLevel = product.allergyEvidenceLevel,
                confidence = product.allergyDataConfidence,
                message = "등록된 알레르기 조건이 없습니다."
            )
        }
        if (evidenceParts.isEmpty()) {
            return SafetyDecision(
                status = SafetyStatus.UNKNOWN,
                conflictingAllergens = emptyList(),
                evidenceSources = emptyList(),
                evidenceLevel = product.allergyEvidenceLevel,
                confidence = product.allergyDataConfidence,
                message = "원재료와 알레르기 표기 정보가 없어 안전성을 확인할 수 없습니다."
            )
        }

        val rawEvidence = evidenceParts.joinToString(" ") { it.second }
        val evidence = normalize(rawEvidence)
        val evidenceTokens = evidenceTokens(rawEvidence)
        val conflicts = allergies.mapNotNull { allergy ->
            val normalizedAllergy = normalize(allergy)
            if (normalizedAllergy.isEmpty()) return@mapNotNull null
            val rule = ALLERGEN_RULES.firstOrNull { normalizedAllergy in it.inputAliases }
                ?: normalizedAllergy.takeIf { it.length >= 2 }?.let { profileTerm ->
                    ALLERGEN_RULES.firstOrNull { candidate ->
                        candidate.inputAliases.any { alias ->
                            alias.length >= 2 &&
                                (profileTerm.contains(alias) || alias.contains(profileTerm))
                        }
                    }
                }
            val matched = if (rule != null) {
                rule.evidenceKeywords.any { keyword ->
                    evidenceContains(evidence, evidenceTokens, keyword)
                }
            } else {
                normalizedAllergy.length >= 2 && evidence.contains(normalizedAllergy)
            }
            if (matched) rule?.canonical ?: allergy.trim() else null
        }.distinct()

        if (conflicts.isNotEmpty()) {
            return SafetyDecision(
                status = SafetyStatus.DANGER,
                conflictingAllergens = conflicts,
                evidenceSources = evidenceSources,
                evidenceLevel = product.allergyEvidenceLevel,
                confidence = product.allergyDataConfidence,
                message = "사용자 알레르기와 충돌하는 성분이 확인되었습니다: ${conflicts.joinToString()}"
            )
        }

        if (product.allergyEvidenceLevel !in PASS_CAPABLE_ALLERGY_EVIDENCE) {
            return SafetyDecision(
                status = SafetyStatus.UNKNOWN,
                conflictingAllergens = emptyList(),
                evidenceSources = evidenceSources,
                evidenceLevel = product.allergyEvidenceLevel,
                confidence = product.allergyDataConfidence,
                message = "공식 알레르기 표기 근거가 충분하지 않아 충돌 여부를 확정할 수 없습니다."
            )
        }

        return SafetyDecision(
            status = SafetyStatus.PASS,
            conflictingAllergens = emptyList(),
            evidenceSources = evidenceSources,
            evidenceLevel = product.allergyEvidenceLevel,
            confidence = product.allergyDataConfidence,
            message = "확인된 공식 표기 데이터에서 사용자 알레르기와의 충돌이 확인되지 않았습니다."
        )
    }

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

    private fun evidenceTokens(value: String): Set<String> = Normalizer
        .normalize(value, Normalizer.Form.NFKC)
        .lowercase()
        .split(Regex("[^가-힣a-z0-9]+"))
        .filterTo(linkedSetOf()) { it.isNotBlank() }

    private fun evidenceContains(compactEvidence: String, tokens: Set<String>, keyword: String): Boolean =
        when {
            keyword == "밀" -> keyword in tokens
            keyword.startsWith("밀") -> tokens.any { token ->
                keyword in token && "메밀" !in token
            }
            keyword.length == 1 -> keyword in tokens
            else -> compactEvidence.contains(keyword)
        }

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

    private data class AllergenRule(
        val canonical: String,
        val inputAliases: Set<String>,
        val evidenceKeywords: Set<String>
    )

    private companion object {
        val PASS_CAPABLE_ALLERGY_EVIDENCE = setOf(
            AllergyEvidenceLevel.VERIFIED_SOURCE,
            AllergyEvidenceLevel.DECLARED_LABEL
        )
        const val MIN_DIETARY_CONFIDENCE = 0.50
        val ALLERGEN_RULES = listOf(
            AllergenRule("난류", setOf("난류", "계란", "달걀", "알류"), setOf("계란", "달걀", "난백", "난황", "전란", "알부민")),
            AllergenRule("우유", setOf("우유", "유제품", "유단백"), setOf("우유", "유청", "유단백", "카제인", "분유", "버터", "치즈")),
            AllergenRule("메밀", setOf("메밀"), setOf("메밀")),
            AllergenRule("대두", setOf("대두", "콩", "소이"), setOf("대두", "콩", "소이", "두유", "두부")),
            AllergenRule("밀", setOf("밀", "글루텐"), setOf("밀", "밀가루", "밀함유", "소맥", "글루텐")),
            AllergenRule("땅콩", setOf("땅콩", "피넛"), setOf("땅콩", "피넛")),
            AllergenRule("견과류", setOf("견과류", "호두", "잣", "아몬드", "캐슈넛", "피스타치오"), setOf("호두", "잣", "아몬드", "캐슈", "피스타치오", "마카다미아", "헤이즐넛", "브라질넛")),
            AllergenRule("갑각류", setOf("갑각류"), setOf("새우", "쉬림프", "크릴", "꽃게", "대게", "홍게", "게살", "게분말", "크랩")),
            AllergenRule("새우", setOf("새우", "갑각류"), setOf("새우", "쉬림프", "크릴")),
            AllergenRule("게", setOf("게", "크랩"), setOf("꽃게", "대게", "홍게", "게살", "게분말", "크랩")),
            AllergenRule("고등어", setOf("고등어"), setOf("고등어")),
            AllergenRule("어류", setOf("생선", "어류"), setOf("고등어", "참치", "연어", "멸치", "정어리", "어육", "어류")),
            AllergenRule("조개류", setOf("조개", "조개류", "굴", "전복", "홍합"), setOf("조개", "굴", "전복", "홍합", "바지락", "가리비")),
            AllergenRule("돼지고기", setOf("돼지고기", "돈육"), setOf("돼지고기", "돈육", "돈지", "라드")),
            AllergenRule("닭고기", setOf("닭고기", "계육"), setOf("닭고기", "계육", "치킨")),
            AllergenRule("쇠고기", setOf("쇠고기", "소고기", "우육"), setOf("쇠고기", "소고기", "우육", "비프")),
            AllergenRule("오징어", setOf("오징어"), setOf("오징어")),
            AllergenRule("복숭아", setOf("복숭아", "피치"), setOf("복숭아", "피치")),
            AllergenRule("토마토", setOf("토마토"), setOf("토마토")),
            AllergenRule("아황산류", setOf("아황산", "아황산류", "설파이트"), setOf("아황산", "메타중아황산", "설파이트"))
        )
    }
}
