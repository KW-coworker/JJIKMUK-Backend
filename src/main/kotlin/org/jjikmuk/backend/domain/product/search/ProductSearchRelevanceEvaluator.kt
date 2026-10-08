package org.jjikmuk.backend.domain.product.search

import org.jjikmuk.backend.domain.product.Product
import kotlin.math.ceil

data class ProductSearchCaseEvaluation(
    val case: ProductSearchRelevanceCase,
    val products: List<Product>,
    val firstRelevantRank: Int?,
    val latencyMicros: Long
) {
    val passed: Boolean = firstRelevantRank != null
}

data class ProductSearchEvaluationReport(
    val results: List<ProductSearchCaseEvaluation>,
    val hitRateAtK: Double,
    val meanReciprocalRank: Double,
    val zeroResultRate: Double,
    val averageLatencyMicros: Double,
    val p95LatencyMicros: Long,
    val averageResultCount: Double,
    val pairTopKOverlap: Map<String, Double>
)

object ProductSearchRelevanceEvaluator {
    fun evaluate(
        cases: List<ProductSearchRelevanceCase>,
        search: (ProductSearchRelevanceCase) -> TimedProducts
    ): ProductSearchEvaluationReport {
        require(cases.isNotEmpty()) { "At least one relevance case is required" }
        require(cases.map { it.caseId }.distinct().size == cases.size) {
            "Relevance case IDs must be unique"
        }

        val results = cases.map { case ->
            require(case.topK > 0) { "topK must be positive for ${case.caseId}" }
            val timed = search(case)
            val products = timed.products.take(case.topK)
            val firstRelevantRank = products.indexOfFirst { product ->
                ProductSearchRelevanceDataset.isRelevant(case, product)
            }.takeIf { it >= 0 }?.plus(1)
            ProductSearchCaseEvaluation(case, products, firstRelevantRank, timed.latencyMicros)
        }
        val sortedLatencies = results.map(ProductSearchCaseEvaluation::latencyMicros).sorted()
        val p95Index = (ceil(sortedLatencies.size * 0.95).toInt() - 1)
            .coerceIn(sortedLatencies.indices)

        return ProductSearchEvaluationReport(
            results = results,
            hitRateAtK = results.count(ProductSearchCaseEvaluation::passed).toDouble() / results.size,
            meanReciprocalRank = results.sumOf { result ->
                result.firstRelevantRank?.let { 1.0 / it } ?: 0.0
            } / results.size,
            zeroResultRate = results.count { it.products.isEmpty() }.toDouble() / results.size,
            averageLatencyMicros = results.map { it.latencyMicros }.average(),
            p95LatencyMicros = sortedLatencies[p95Index],
            averageResultCount = results.map { it.products.size }.average(),
            pairTopKOverlap = calculatePairOverlap(results)
        )
    }

    private fun calculatePairOverlap(
        results: List<ProductSearchCaseEvaluation>
    ): Map<String, Double> = results
        .filter { it.case.pairGroup != null }
        .groupBy { requireNotNull(it.case.pairGroup) }
        .mapNotNull { (group, pairedResults) ->
            if (pairedResults.size != 2) return@mapNotNull null
            val first = pairedResults[0].products.map(Product::barcode).toSet()
            val second = pairedResults[1].products.map(Product::barcode).toSet()
            val union = first union second
            group to if (union.isEmpty()) 1.0 else (first intersect second).size.toDouble() / union.size
        }
        .toMap()
}

data class TimedProducts(
    val products: List<Product>,
    val latencyMicros: Long
)
