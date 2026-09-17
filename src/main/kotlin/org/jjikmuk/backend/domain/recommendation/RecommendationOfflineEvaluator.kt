package org.jjikmuk.backend.domain.recommendation

import kotlin.math.ceil
import kotlin.math.ln
import kotlin.math.min

data class RecommendationEvaluationCase(
    val caseId: String,
    val expectedRelevantBarcodes: Set<String>,
    val response: ProductRecommendationResponse,
    val latencyMicros: Long
)

data class RecommendationCaseEvaluation(
    val caseId: String,
    val firstRelevantRank: Int?,
    val ndcgAtK: Double,
    val resultCount: Int,
    val fallbackResultCount: Int,
    val hardConstraintViolations: Int,
    val unknownSafetyItems: Int,
    val verificationRequiredItems: Int,
    val emptyResponse: Boolean,
    val resultMode: RecommendationResultMode,
    val latencyMicros: Long,
    val resultBarcodes: List<String>
)

data class RecommendationEvaluationReport(
    val results: List<RecommendationCaseEvaluation>,
    val hitRateAtK: Double,
    val meanReciprocalRank: Double,
    val ndcgAtK: Double,
    val hardConstraintViolationRate: Double,
    val unknownSafetyRate: Double,
    val verificationRequiredRate: Double,
    val fallbackCaseRate: Double,
    val emptyResponseRate: Double,
    val catalogCoverage: Double,
    val averageResultCount: Double,
    val averageLatencyMicros: Double,
    val p95LatencyMicros: Long
)

object RecommendationOfflineEvaluator {
    fun evaluate(
        cases: List<RecommendationEvaluationCase>,
        catalogSize: Long
    ): RecommendationEvaluationReport {
        require(cases.isNotEmpty()) { "At least one recommendation evaluation case is required" }
        require(cases.map { it.caseId }.distinct().size == cases.size) {
            "Recommendation evaluation case IDs must be unique"
        }
        require(cases.all { it.expectedRelevantBarcodes.isNotEmpty() }) {
            "Every recommendation evaluation case needs at least one reviewed relevant barcode"
        }
        require(catalogSize > 0) { "Catalog size must be positive" }

        val results = cases.map { case ->
            val items = case.response.items.ifEmpty { case.response.fallbackItems }
            val firstRelevantRank = items.indexOfFirst {
                it.product.barcode in case.expectedRelevantBarcodes
            }.takeIf { it >= 0 }?.plus(1)
            val violations = items.count {
                it.safety.status == SafetyStatus.DANGER ||
                    it.dietConstraints.status == DietConstraintStatus.MISMATCH
            }
            RecommendationCaseEvaluation(
                caseId = case.caseId,
                firstRelevantRank = firstRelevantRank,
                ndcgAtK = ndcg(items.map { it.product.barcode }, case.expectedRelevantBarcodes),
                resultCount = items.size,
                fallbackResultCount = case.response.fallbackItems.size,
                hardConstraintViolations = violations,
                unknownSafetyItems = items.count { it.safety.status == SafetyStatus.UNKNOWN },
                verificationRequiredItems = items.count(RecommendedProduct::verificationRequired),
                emptyResponse = items.isEmpty(),
                resultMode = case.response.resultMode,
                latencyMicros = case.latencyMicros.coerceAtLeast(0),
                resultBarcodes = items.map { it.product.barcode }
            )
        }
        val itemCount = results.sumOf(RecommendationCaseEvaluation::resultCount)
        val sortedLatencies = results.map(RecommendationCaseEvaluation::latencyMicros).sorted()
        val p95Index = (ceil(sortedLatencies.size * 0.95).toInt() - 1).coerceIn(sortedLatencies.indices)
        val uniqueItems = results.flatMap(RecommendationCaseEvaluation::resultBarcodes).toSet().size

        return RecommendationEvaluationReport(
            results = results,
            hitRateAtK = results.count { it.firstRelevantRank != null }.toDouble() / results.size,
            meanReciprocalRank = results.sumOf { it.firstRelevantRank?.let { rank -> 1.0 / rank } ?: 0.0 } /
                results.size,
            ndcgAtK = results.map(RecommendationCaseEvaluation::ndcgAtK).average(),
            hardConstraintViolationRate = if (itemCount == 0) 0.0 else
                results.sumOf(RecommendationCaseEvaluation::hardConstraintViolations).toDouble() / itemCount,
            unknownSafetyRate = if (itemCount == 0) 0.0 else
                results.sumOf(RecommendationCaseEvaluation::unknownSafetyItems).toDouble() / itemCount,
            verificationRequiredRate = if (itemCount == 0) 0.0 else
                results.sumOf(RecommendationCaseEvaluation::verificationRequiredItems).toDouble() / itemCount,
            fallbackCaseRate = results.count { it.fallbackResultCount > 0 }.toDouble() / results.size,
            emptyResponseRate = results.count(RecommendationCaseEvaluation::emptyResponse).toDouble() / results.size,
            catalogCoverage = uniqueItems.toDouble() / catalogSize,
            averageResultCount = results.map(RecommendationCaseEvaluation::resultCount).average(),
            averageLatencyMicros = results.map(RecommendationCaseEvaluation::latencyMicros).average(),
            p95LatencyMicros = sortedLatencies[p95Index]
        )
    }

    private fun ndcg(rankedBarcodes: List<String>, relevantBarcodes: Set<String>): Double {
        val dcg = rankedBarcodes.mapIndexed { index, barcode ->
            if (barcode in relevantBarcodes) 1.0 / log2(index + 2.0) else 0.0
        }.sum()
        val idealCount = min(rankedBarcodes.size, relevantBarcodes.size)
        if (idealCount == 0) return 0.0
        val idealDcg = (0 until idealCount).sumOf { index -> 1.0 / log2(index + 2.0) }
        return dcg / idealDcg
    }

    private fun log2(value: Double): Double = ln(value) / ln(2.0)
}
