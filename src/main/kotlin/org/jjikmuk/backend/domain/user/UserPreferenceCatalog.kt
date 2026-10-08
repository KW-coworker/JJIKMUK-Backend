package org.jjikmuk.backend.domain.user

import org.jjikmuk.backend.domain.product.ProductFilter
import java.text.Normalizer

data class DietPreferenceProfile(
    val filters: List<ProductFilter>,
    val unknownTerms: List<String>
)

/** Canonical API/storage rules for vegetarian type and dietary preferences. */
object DietPreferenceCatalog {
    private val vegetarianTypes = setOf(
        ProductFilter.VEGAN,
        ProductFilter.LACTO_VEGETARIAN,
        ProductFilter.OVO_VEGETARIAN,
        ProductFilter.LACTO_OVO_VEGETARIAN,
        ProductFilter.PESCATARIAN,
        ProductFilter.POLLOTARIAN
    )

    fun parse(value: String?): DietPreferenceProfile {
        val filters = linkedSetOf<ProductFilter>()
        val unknown = linkedSetOf<String>()
        DelimitedProfileNormalizer.terms(value).forEach { term ->
            val resolved = ProductFilter.fromRequest(term)
            if (resolved == null) unknown += term else filters += resolved
        }
        return DietPreferenceProfile(
            filters = ProductFilter.entries.filter(filters::contains),
            unknownTerms = unknown.toList()
        )
    }

    fun normalizeForStorage(value: String?): String? {
        val parsed = parse(value)
        require(parsed.unknownTerms.isEmpty()) {
            "지원하지 않는 식이조건 ID: ${parsed.unknownTerms.joinToString()}"
        }
        val selectedVegetarianTypes = parsed.filters.filter(vegetarianTypes::contains)
        require(selectedVegetarianTypes.size <= 1) {
            "채식 유형은 하나만 선택할 수 있습니다: " +
                selectedVegetarianTypes.joinToString { it.key }
        }
        return parsed.filters
            .map(ProductFilter::key)
            .takeIf(List<String>::isNotEmpty)
            ?.joinToString(",")
    }

    /** Reads supported legacy aliases without letting unknown values affect recommendations. */
    fun knownFilters(value: String?): Set<ProductFilter> = parse(value).filters.toSet()
}

object DelimitedProfileNormalizer {
    private const val MAX_TERMS = 50
    private const val MAX_TERM_LENGTH = 100
    private const val MAX_STORAGE_LENGTH = 1_000

    fun normalizeForStorage(value: String?, fieldName: String): String? {
        val terms = terms(value)
        require(terms.size <= MAX_TERMS) { "${fieldName}은 최대 ${MAX_TERMS}개까지 입력할 수 있습니다." }
        require(terms.all { it.length <= MAX_TERM_LENGTH }) {
            "${fieldName}의 각 항목은 ${MAX_TERM_LENGTH}자 이하여야 합니다."
        }
        val normalized = terms
            .distinctBy { it.lowercase() }
            .takeIf(List<String>::isNotEmpty)
            ?.joinToString(",")
        require(normalized == null || normalized.length <= MAX_STORAGE_LENGTH) {
            "${fieldName} 전체 길이는 ${MAX_STORAGE_LENGTH}자 이하여야 합니다."
        }
        return normalized
    }

    fun terms(value: String?): List<String> = value.orEmpty()
        .split(Regex("[,;/|\\n]+"))
        .map { term ->
            Normalizer.normalize(term, Normalizer.Form.NFKC)
                .trim()
                .replace(Regex("\\s+"), " ")
        }
        .filter(String::isNotBlank)
}
