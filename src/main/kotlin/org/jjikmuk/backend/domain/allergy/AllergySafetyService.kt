package org.jjikmuk.backend.domain.allergy

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductClassificationCatalog
import org.jjikmuk.backend.domain.recommendation.SafetyDecision
import org.jjikmuk.backend.domain.recommendation.SafetyStatus
import org.springframework.stereotype.Component
import java.text.Normalizer

/** One conservative verdict for product detail, search, filters, and recommendations. */
@Component
class AllergySafetyService {
    fun evaluate(product: Product, allergies: List<String>, profileKnown: Boolean = true): SafetyDecision {
        val profile = AllergyCatalog.parse(allergies.joinToString(","))
        val evidence = listOfNotNull(
            product.allergyWarning?.takeIf(String::isNotBlank)?.let { "allergy_warning" to it },
            product.rawMaterials?.takeIf(String::isNotBlank)?.let { "raw_materials" to it },
            product.allergy?.takeIf(String::isNotBlank)?.let { "allergy" to it }
        )
        val classifiedAllergens = ProductClassificationCatalog
            .parseAllergyClassification(product.allergyClassification)
            .allergens
            .toSet()
        val sources = evidence.map(Pair<String, String>::first) +
            if (classifiedAllergens.isEmpty()) emptyList() else listOf("allergy_classification")

        if (!profileKnown) {
            return decision(
                product, SafetyStatus.UNKNOWN, emptyList(), sources,
                "사용자 알레르기 정보가 없어 개인 안전성을 판정할 수 없습니다."
            )
        }

        if (profile.ids.isEmpty() && profile.unknownTerms.isEmpty()) {
            return decision(product, SafetyStatus.PASS, emptyList(), sources, "등록된 알레르기 조건이 없습니다.")
        }

        val conflicts = profile.ids.filter { allergy ->
            allergy in classifiedAllergens ||
                evidence.any { (_, text) -> allergy.evidenceKeywords.any { keyword -> containsEvidence(text, keyword) } }
        }.map(FoodAllergy::id)
        if (conflicts.isNotEmpty()) {
            val labels = conflicts.mapNotNull { AllergyCatalog.resolve(it)?.displayName }
            return decision(
                product, SafetyStatus.DANGER, conflicts, sources,
                "원재료 또는 알레르기 표기에 충돌 성분이 확인되었습니다: ${labels.joinToString()}"
            )
        }

        if (profile.unknownTerms.isNotEmpty()) {
            return decision(
                product, SafetyStatus.UNKNOWN, emptyList(), sources,
                "지원하지 않는 알레르기 항목이 있어 안전성을 확인할 수 없습니다: ${profile.unknownTerms.joinToString()}"
            )
        }

        if (evidence.isEmpty()) {
            return decision(
                product, SafetyStatus.UNKNOWN, emptyList(), sources,
                "원재료와 알레르기 표기 정보가 없어 안전성을 확인할 수 없습니다. 포장 라벨을 확인해 주세요."
            )
        }

        val ambiguousGroup = AMBIGUOUS_GROUPS.firstOrNull { (affected, terms) ->
            profile.ids.any { it in affected } &&
                evidence.any { (_, text) -> terms.any { containsEvidence(text, it) } }
        }
        if (ambiguousGroup != null) {
            return decision(
                product, SafetyStatus.UNKNOWN, emptyList(), sources,
                "원재료가 포괄적인 성분군으로만 표기되어 개별 알레르기 성분을 구분할 수 없습니다. 포장 라벨을 확인해 주세요."
            )
        }

        if (product.rawMaterials.isNullOrBlank() ||
            product.allergyEvidenceLevel !in PASS_CAPABLE_LEVELS ||
            profile.ids.any { it.requiresVerifiedSource } &&
                product.allergyEvidenceLevel != AllergyEvidenceLevel.VERIFIED_SOURCE
        ) {
            return decision(
                product, SafetyStatus.UNKNOWN, emptyList(), sources,
                "알레르기 안전성을 확인할 충분한 원재료·출처 정보가 없습니다. 포장 라벨을 확인해 주세요."
            )
        }

        return decision(
            product, SafetyStatus.PASS, emptyList(), sources,
            "확인된 표기 자료에서 등록된 알레르기와의 충돌은 발견되지 않았습니다. 실제 포장 라벨을 다시 확인해 주세요."
        )
    }

    private fun decision(
        product: Product,
        status: SafetyStatus,
        conflicts: List<String>,
        sources: List<String>,
        message: String
    ) = SafetyDecision(
        status = status,
        conflictingAllergens = conflicts,
        evidenceSources = sources,
        evidenceLevel = product.allergyEvidenceLevel,
        confidence = product.allergyDataConfidence,
        message = message
    )

    private fun containsEvidence(text: String, keyword: String): Boolean {
        val normalizedText = Normalizer.normalize(text, Normalizer.Form.NFKC).lowercase()
        val normalizedKeyword = Normalizer.normalize(keyword, Normalizer.Form.NFKC).lowercase()
        val tokens = normalizedText.split(NON_WORD).filter(String::isNotBlank)
        val compact = normalizedText.filter(Char::isLetterOrDigit)
        val term = normalizedKeyword.filter(Char::isLetterOrDigit)
        return when (term) {
            "밀" -> "밀" in tokens
            "콩", "게", "굴", "잣", "조개" -> tokens.any { token ->
                token == term ||
                    (token.startsWith(term) && token.removePrefix(term) in SHORT_TERM_SUFFIXES)
            }
            else -> {
                // '밀' compounds must not turn 메밀 or 밀크 into a wheat hit.
                if (term.startsWith("밀")) {
                    tokens.any { token -> term in token && "메밀" !in token && "밀크" !in token }
                } else {
                    compact.contains(term)
                }
            }
        }
    }

    private companion object {
        val NON_WORD = Regex("[^가-힣a-z0-9]+")
        val PASS_CAPABLE_LEVELS = setOf(
            AllergyEvidenceLevel.DECLARED_LABEL,
            AllergyEvidenceLevel.VERIFIED_SOURCE
        )
        val AMBIGUOUS_GROUPS = listOf(
            setOf(FoodAllergy.OYSTER, FoodAllergy.MUSSEL, FoodAllergy.ABALONE) to
                setOf("조개류", "조개", "조개육수", "조개살", "조개추출물", "shellfish"),
            setOf(FoodAllergy.WALNUT, FoodAllergy.PINE_NUT, FoodAllergy.ALMOND) to
                setOf("견과류", "견과", "tree nuts"),
            setOf(FoodAllergy.SHRIMP, FoodAllergy.CRAB) to
                setOf("갑각류", "crustacean"),
            setOf(FoodAllergy.MACKEREL) to setOf("어류", "생선", "fish"),
            setOf(FoodAllergy.SOY) to setOf("콩류")
        )
        val SHORT_TERM_SUFFIXES = setOf("함유", "가루", "분말", "추출물", "농축액", "육수", "소스", "단백", "기름", "오일", "살")
    }
}
