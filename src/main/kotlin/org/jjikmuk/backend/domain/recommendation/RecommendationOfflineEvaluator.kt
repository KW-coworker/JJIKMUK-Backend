package org.jjikmuk.backend.domain.recommendation

import kotlin.math.ceil
import kotlin.math.ln
import kotlin.math.min

enum class ExpectedRecommendationOutcome { RECOMMENDATION, VERIFICATION_REQUIRED, ABSTAIN }

data class RecommendationEvaluationCase(
    val caseId: String,
    val expectedRelevantBarcodes: Set<String>,
    val response: ProductRecommendationResponse,
    val latencyMicros: Long,
    val expectedOutcome: ExpectedRecommendationOutcome = ExpectedRecommendationOutcome.RECOMMENDATION,
    // Independent reviewer labels, not the algorithm's own PASS/DANGER labels.
    val forbiddenBarcodes: Set<String> = emptySet()
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
    val resultBarcodes: List<String>,
    val expectedOutcome: ExpectedRecommendationOutcome,
    val outcomeMatched: Boolean,
    val unexpectedEmpty: Boolean,
    val presentationViolations: Int,
    val fallbackRelevant: Boolean
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
    val p95LatencyMicros: Long,
    val rankingCaseCount: Int,
    val abstentionCaseCount: Int,
    val verificationCaseCount: Int,
    val outcomeMatchRate: Double,
    val correctAbstentionRate: Double?,
    val unexpectedEmptyResponseRate: Double,
    val presentationViolationCount: Int,
    val verificationFallbackHitRate: Double?,
    val k: Int
)

object RecommendationOfflineEvaluator {
    fun evaluate(
        cases: List<RecommendationEvaluationCase>,
        catalogSize: Long,
        k: Int = 10
    ): RecommendationEvaluationReport {
        require(cases.isNotEmpty()) { "At least one recommendation evaluation case is required" }
        require(cases.map { it.caseId }.distinct().size == cases.size) {
            "Recommendation evaluation case IDs must be unique"
        }
        require(k > 0) { "K must be positive" }
        require(cases.all {
            if (it.expectedOutcome == ExpectedRecommendationOutcome.ABSTAIN) it.expectedRelevantBarcodes.isEmpty()
            else it.expectedRelevantBarcodes.isNotEmpty()
        }) {
            "Positive/fallback cases need reviewed relevant barcodes; abstention cases must have none"
        }
        require(cases.all { it.expectedRelevantBarcodes.intersect(it.forbiddenBarcodes).isEmpty() }) {
            "Relevant and forbidden reviewer labels must not overlap"
        }
        require(catalogSize > 0) { "Catalog size must be positive" }

        val results = cases.map { case ->
            val response = case.response
            // Inspect both channels even if a buggy response populates both.
            val items = response.items + response.fallbackItems
            val ranked = when (response.resultMode) {
                RecommendationResultMode.VERIFIED -> response.items
                RecommendationResultMode.RELAXED_SAFE -> response.fallbackItems
                else -> emptyList()
            }.take(k)
            val firstRelevantRank = ranked.indexOfFirst {
                isVerified(it) && it.product.barcode in case.expectedRelevantBarcodes &&
                    it.product.barcode !in case.forbiddenBarcodes
            }.takeIf { it >= 0 && case.expectedOutcome == ExpectedRecommendationOutcome.RECOMMENDATION }?.plus(1)
            val violations = items.count {
                it.product.barcode in case.forbiddenBarcodes ||
                    it.safety.status == SafetyStatus.DANGER ||
                    it.dietConstraints.status == DietConstraintStatus.MISMATCH
            }
            val presentationViolations = when (response.resultMode) {
                // This evaluator measures personal suitability, not targetless general browsing.
                RecommendationResultMode.GENERAL -> 1
                RecommendationResultMode.VERIFIED -> response.items.count {
                    !isVerified(it) || it.recommendationTier != RecommendationTier.VERIFIED
                } + response.fallbackItems.size
                RecommendationResultMode.RELAXED_SAFE -> response.items.size + response.fallbackItems.count {
                    !isVerified(it) || it.recommendationTier != RecommendationTier.RELAXED_SAFE
                }
                RecommendationResultMode.VERIFICATION_REQUIRED -> response.items.size + response.fallbackItems.count {
                    !it.verificationRequired || it.warnings.none(String::isNotBlank) || it.requiredActions.none(String::isNotBlank) ||
                        it.recommendationTier != RecommendationTier.VERIFICATION_REQUIRED ||
                        (it.safety.status != SafetyStatus.UNKNOWN && it.dietConstraints.status != DietConstraintStatus.UNKNOWN)
                }
                RecommendationResultMode.ACTION_REQUIRED -> items.size
            } + (items.size - items.map { it.product.barcode }.distinct().size)
            val expectedShape = when (case.expectedOutcome) {
                ExpectedRecommendationOutcome.RECOMMENDATION ->
                    response.resultMode in setOf(RecommendationResultMode.VERIFIED, RecommendationResultMode.RELAXED_SAFE) && ranked.isNotEmpty()
                ExpectedRecommendationOutcome.VERIFICATION_REQUIRED ->
                    response.resultMode == RecommendationResultMode.VERIFICATION_REQUIRED && response.fallbackItems.isNotEmpty()
                ExpectedRecommendationOutcome.ABSTAIN ->
                    response.resultMode == RecommendationResultMode.ACTION_REQUIRED && items.isEmpty() && response.requiredActions.any(String::isNotBlank)
            }
            val fallbackRelevant = response.fallbackItems.take(k).any {
                it.product.barcode in case.expectedRelevantBarcodes
            }
            RecommendationCaseEvaluation(
                caseId = case.caseId,
                firstRelevantRank = firstRelevantRank,
                ndcgAtK = if (case.expectedOutcome == ExpectedRecommendationOutcome.RECOMMENDATION) {
                    ndcg(ranked.map { if (isVerified(it)) it.product.barcode else "" }, case.expectedRelevantBarcodes, k)
                } else 0.0,
                resultCount = items.size,
                fallbackResultCount = case.response.fallbackItems.size,
                hardConstraintViolations = violations,
                unknownSafetyItems = items.count { it.safety.status == SafetyStatus.UNKNOWN },
                verificationRequiredItems = items.count(RecommendedProduct::verificationRequired),
                emptyResponse = items.isEmpty(),
                resultMode = case.response.resultMode,
                latencyMicros = case.latencyMicros.coerceAtLeast(0),
                resultBarcodes = items.map { it.product.barcode },
                expectedOutcome = case.expectedOutcome,
                outcomeMatched = expectedShape && violations == 0 && presentationViolations == 0,
                unexpectedEmpty = items.isEmpty() && case.expectedOutcome != ExpectedRecommendationOutcome.ABSTAIN,
                presentationViolations = presentationViolations,
                fallbackRelevant = fallbackRelevant
            )
        }
        val itemCount = results.sumOf(RecommendationCaseEvaluation::resultCount)
        val sortedLatencies = results.map(RecommendationCaseEvaluation::latencyMicros).sorted()
        val p95Index = (ceil(sortedLatencies.size * 0.95).toInt() - 1).coerceIn(sortedLatencies.indices)
        val uniqueItems = results.flatMap(RecommendationCaseEvaluation::resultBarcodes).toSet().size
        val rankingCases = results.filter { it.expectedOutcome == ExpectedRecommendationOutcome.RECOMMENDATION }
        val abstentionCases = results.filter { it.expectedOutcome == ExpectedRecommendationOutcome.ABSTAIN }
        val verificationCases = results.filter { it.expectedOutcome == ExpectedRecommendationOutcome.VERIFICATION_REQUIRED }
        val nonAbstentionCount = results.size - abstentionCases.size

        return RecommendationEvaluationReport(
            results = results,
            hitRateAtK = ratio(rankingCases.count { it.firstRelevantRank != null }, rankingCases.size),
            meanReciprocalRank = if (rankingCases.isEmpty()) 0.0 else
                rankingCases.sumOf { it.firstRelevantRank?.let { rank -> 1.0 / rank } ?: 0.0 } / rankingCases.size,
            ndcgAtK = if (rankingCases.isEmpty()) 0.0 else rankingCases.map(RecommendationCaseEvaluation::ndcgAtK).average(),
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
            p95LatencyMicros = sortedLatencies[p95Index],
            rankingCaseCount = rankingCases.size,
            abstentionCaseCount = abstentionCases.size,
            verificationCaseCount = verificationCases.size,
            outcomeMatchRate = ratio(results.count { it.outcomeMatched }, results.size),
            correctAbstentionRate = abstentionCases.takeIf { it.isNotEmpty() }?.let { ratio(it.count { r -> r.outcomeMatched }, it.size) },
            unexpectedEmptyResponseRate = ratio(results.count { it.unexpectedEmpty }, nonAbstentionCount),
            presentationViolationCount = results.sumOf { it.presentationViolations },
            verificationFallbackHitRate = verificationCases.takeIf { it.isNotEmpty() }?.let {
                ratio(it.count { r -> r.outcomeMatched && r.fallbackRelevant }, it.size)
            },
            k = k
        )
    }

    private fun ndcg(rankedBarcodes: List<String>, relevantBarcodes: Set<String>, k: Int): Double {
        val seen = mutableSetOf<String>()
        val dcg = rankedBarcodes.mapIndexed { index, barcode ->
            if (barcode in relevantBarcodes && seen.add(barcode)) 1.0 / log2(index + 2.0) else 0.0
        }.sum()
        val idealCount = min(k, relevantBarcodes.size)
        if (idealCount == 0) return 0.0
        val idealDcg = (0 until idealCount).sumOf { index -> 1.0 / log2(index + 2.0) }
        return dcg / idealDcg
    }

    private fun log2(value: Double): Double = ln(value) / ln(2.0)

    private fun ratio(numerator: Int, denominator: Int): Double =
        if (denominator == 0) 0.0 else numerator.toDouble() / denominator

    private fun isVerified(item: RecommendedProduct): Boolean =
        item.safety.status == SafetyStatus.PASS && item.dietConstraints.status == DietConstraintStatus.PASS &&
            !item.verificationRequired && item.recommendationTier != RecommendationTier.VERIFICATION_REQUIRED
}

data class RecommendationEvaluationThresholds(
    val minimumHitRate: Double = 0.30,
    val minimumNdcg: Double = 0.15,
    val maximumVerificationRequiredRate: Double = 1.0,
    val maximumUnexpectedEmptyResponseRate: Double = 0.0,
    val maximumP95Ms: Long = 1000
) {
    fun passes(report: RecommendationEvaluationReport): Boolean =
        (report.rankingCaseCount == 0 || (report.hitRateAtK >= minimumHitRate && report.ndcgAtK >= minimumNdcg)) &&
            report.hardConstraintViolationRate == 0.0 && report.presentationViolationCount == 0 &&
            report.outcomeMatchRate == 1.0 &&
            report.verificationRequiredRate <= maximumVerificationRequiredRate &&
            report.unexpectedEmptyResponseRate <= maximumUnexpectedEmptyResponseRate &&
            report.p95LatencyMicros <= maximumP95Ms * 1_000
}
