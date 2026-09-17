package org.jjikmuk.backend.domain.product.search

import org.jjikmuk.backend.domain.product.Product

data class ProductSearchRelevanceCase(
    val caseId: String,
    val query: String,
    val expectedCompactNameFragments: Set<String>,
    val topK: Int = 10,
    val pairGroup: String? = null
)

/**
 * Versioned, human-reviewable seed judgments. A result is relevant when its
 * visible product name contains one of the reviewed compact fragments.
 */
object ProductSearchRelevanceDataset {
    const val VERSION = "product-search-relevance-v1"

    val cases: List<ProductSearchRelevanceCase> = listOf(
        case("protein-chip-compact", "단백질칩", "단백질칩", pairGroup = "protein-chip"),
        case("protein-chip-spaced", "단백질 칩", "단백질칩", pairGroup = "protein-chip"),
        case("soy-bar-compact", "두유바", "두유바", pairGroup = "soy-bar"),
        case("soy-bar-spaced", "두유 바", "두유바", pairGroup = "soy-bar"),
        case("spicy-shrimp-cracker-compact", "매운새우깡", "매운새우깡", pairGroup = "spicy-shrimp-cracker"),
        case("spicy-shrimp-cracker-spaced", "매운 새우깡", "매운새우깡", pairGroup = "spicy-shrimp-cracker"),
        case("pocky", "포키", "포키"),
        case("choco-pie", "초코파이", "초코파이"),
        case("shin-ramyun", "신라면", "신라면"),
        case("kkokkalcorn", "꼬깔콘", "꼬깔콘")
    )

    fun isRelevant(case: ProductSearchRelevanceCase, product: Product): Boolean {
        val visibleNames = sequenceOf(product.productName, product.cleanProductName)
            .filterNotNull()
            .map(ProductSearchKeywordBuilder::normalizeQuery)
            .filter(String::isNotEmpty)
            .toList()
        return case.expectedCompactNameFragments.any { expected ->
            val compactExpected = ProductSearchKeywordBuilder.normalizeQuery(expected)
            visibleNames.any { name -> compactExpected in name }
        }
    }

    private fun case(
        caseId: String,
        query: String,
        expectedFragment: String,
        pairGroup: String? = null
    ) = ProductSearchRelevanceCase(
        caseId = caseId,
        query = query,
        expectedCompactNameFragments = setOf(expectedFragment),
        pairGroup = pairGroup
    )
}
