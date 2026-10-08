package org.jjikmuk.backend.domain.recommendation

import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.CommandLineRunner
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.support.GeneratedKeyHolder
import java.sql.Statement
import java.time.LocalDateTime

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(
    prefix = "recommendation.evaluation",
    name = ["enabled"],
    havingValue = "true"
)
class RecommendationEvaluationRunner(
    private val recommendationService: RecommendationService,
    private val jdbcTemplate: JdbcTemplate,
    @Value("\${recommendation.evaluation.dataset-version:reviewed-v1}")
    private val datasetVersion: String,
    @Value("\${recommendation.evaluation.limit:10}")
    private val limit: Int,
    @Value("\${recommendation.evaluation.min-similarity-score:0.2}")
    private val minSimilarityScore: Double,
    @Value("\${recommendation.evaluation.minimum-hit-rate:0.30}")
    private val minimumHitRate: Double,
    @Value("\${recommendation.evaluation.minimum-ndcg:0.15}")
    private val minimumNdcg: Double,
    @Value("\${recommendation.evaluation.maximum-verification-required-rate:1.0}")
    private val maximumVerificationRequiredRate: Double,
    @Value("\${recommendation.evaluation.maximum-empty-response-rate:0.0}")
    private val maximumEmptyResponseRate: Double,
    @Value("\${recommendation.evaluation.maximum-p95-ms:1000}")
    private val maximumP95Ms: Long
) {
    @Bean
    @Order(210)
    fun evaluateRecommendations(): CommandLineRunner = CommandLineRunner {
        validateSettings()
        val definitions = loadCases()
        require(definitions.isNotEmpty()) {
            "활성 추천 평가셋이 없습니다. product_recommendation_evaluation_cases를 먼저 채워주세요."
        }
        val cases = definitions.map { definition ->
            val startedAt = System.nanoTime()
            val response = recommendationService.recommendAlternatives(
                referenceBarcode = definition.referenceBarcode,
                userId = definition.userId,
                limit = limit,
                minSimilarityScore = minSimilarityScore
            )
            RecommendationEvaluationCase(
                caseId = definition.caseId,
                expectedRelevantBarcodes = definition.expectedRelevantBarcodes,
                response = response,
                latencyMicros = (System.nanoTime() - startedAt) / 1_000
            )
        }
        val catalogSize = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM products", Long::class.java) ?: 0L
        val report = RecommendationOfflineEvaluator.evaluate(cases, catalogSize)
        val passed = passesThresholds(report)
        val runId = saveRun(report, passed)
        saveResults(runId, report.results)
        logger.info(
            "추천 오프라인 평가 완료: runId={}, cases={}, Hit@K={}, MRR={}, NDCG={}, " +
                "constraintViolationRate={}, unknownRate={}, verificationRequiredRate={}, " +
                "fallbackCaseRate={}, emptyResponseRate={}, coverage={}, p95Micros={}",
            runId,
            report.results.size,
            report.hitRateAtK,
            report.meanReciprocalRank,
            report.ndcgAtK,
            report.hardConstraintViolationRate,
            report.unknownSafetyRate,
            report.verificationRequiredRate,
            report.fallbackCaseRate,
            report.emptyResponseRate,
            report.catalogCoverage,
            report.p95LatencyMicros
        )
        require(passed) {
            "Recommendation quality gate failed: Hit@K=${report.hitRateAtK}, " +
                "NDCG=${report.ndcgAtK}, violations=${report.hardConstraintViolationRate}, " +
                "verificationRequired=${report.verificationRequiredRate}, " +
                "empty=${report.emptyResponseRate}, p95Micros=${report.p95LatencyMicros}"
        }
    }

    private fun validateSettings() {
        require(limit in 1..20) { "recommendation.evaluation.limit must be between 1 and 20" }
        require(minSimilarityScore in 0.0..1.0) { "min-similarity-score must be between 0 and 1" }
        require(minimumHitRate in 0.0..1.0) { "minimum-hit-rate must be between 0 and 1" }
        require(minimumNdcg in 0.0..1.0) { "minimum-ndcg must be between 0 and 1" }
        require(maximumVerificationRequiredRate in 0.0..1.0) {
            "maximum-verification-required-rate must be between 0 and 1"
        }
        require(maximumEmptyResponseRate in 0.0..1.0) {
            "maximum-empty-response-rate must be between 0 and 1"
        }
        require(maximumP95Ms > 0) { "maximum-p95-ms must be positive" }
    }

    private fun loadCases(): List<EvaluationCaseDefinition> = jdbcTemplate.query(
        """
        SELECT case_id, user_id, reference_barcode, expected_relevant_barcodes
        FROM product_recommendation_evaluation_cases
        WHERE active = TRUE
        ORDER BY case_id
        """.trimIndent()
    ) { resultSet, _ ->
        val expected = resultSet.getString("expected_relevant_barcodes")
            .split(',')
            .map(String::trim)
            .filterTo(linkedSetOf(), String::isNotEmpty)
        require(expected.isNotEmpty()) {
            "추천 평가 case ${resultSet.getString("case_id")}의 관련 상품 정답이 비어 있습니다."
        }
        EvaluationCaseDefinition(
            caseId = resultSet.getString("case_id"),
            userId = resultSet.getLong("user_id"),
            referenceBarcode = resultSet.getString("reference_barcode"),
            expectedRelevantBarcodes = expected
        )
    }

    private fun passesThresholds(report: RecommendationEvaluationReport): Boolean =
        report.hitRateAtK >= minimumHitRate &&
            report.ndcgAtK >= minimumNdcg &&
            report.hardConstraintViolationRate == 0.0 &&
            report.verificationRequiredRate <= maximumVerificationRequiredRate &&
            report.emptyResponseRate <= maximumEmptyResponseRate &&
            report.p95LatencyMicros <= maximumP95Ms * 1_000

    private fun saveRun(report: RecommendationEvaluationReport, passed: Boolean): Long {
        val keyHolder = GeneratedKeyHolder()
        jdbcTemplate.update({ connection ->
            connection.prepareStatement(
                """
                INSERT INTO product_recommendation_evaluation_runs
                    (dataset_version, policy_version, case_count, hit_rate_at_k,
                     mean_reciprocal_rank, ndcg_at_k, hard_constraint_violation_rate,
                     unknown_safety_rate, verification_required_rate, fallback_case_rate,
                     empty_response_rate, catalog_coverage, average_result_count,
                     average_latency_micros, p95_latency_micros, passed, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.trimIndent(),
                Statement.RETURN_GENERATED_KEYS
            ).apply {
                setString(1, datasetVersion.take(100))
                setString(2, RecommendationService.POLICY_VERSION)
                setInt(3, report.results.size)
                setDouble(4, report.hitRateAtK)
                setDouble(5, report.meanReciprocalRank)
                setDouble(6, report.ndcgAtK)
                setDouble(7, report.hardConstraintViolationRate)
                setDouble(8, report.unknownSafetyRate)
                setDouble(9, report.verificationRequiredRate)
                setDouble(10, report.fallbackCaseRate)
                setDouble(11, report.emptyResponseRate)
                setDouble(12, report.catalogCoverage)
                setDouble(13, report.averageResultCount)
                setDouble(14, report.averageLatencyMicros)
                setLong(15, report.p95LatencyMicros)
                setBoolean(16, passed)
                setObject(17, LocalDateTime.now())
            }
        }, keyHolder)
        return requireNotNull(keyHolder.key).toLong()
    }

    private fun saveResults(runId: Long, results: List<RecommendationCaseEvaluation>) {
        results.forEach { result ->
            jdbcTemplate.update(
                """
                INSERT INTO product_recommendation_evaluation_results
                    (evaluation_run_id, case_id, first_relevant_rank, result_count,
                     fallback_result_count, hard_constraint_violations, unknown_safety_items,
                     verification_required_items, empty_response, result_mode, latency_micros,
                     result_barcodes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.trimIndent(),
                runId,
                result.caseId,
                result.firstRelevantRank,
                result.resultCount,
                result.fallbackResultCount,
                result.hardConstraintViolations,
                result.unknownSafetyItems,
                result.verificationRequiredItems,
                result.emptyResponse,
                result.resultMode.name,
                result.latencyMicros,
                result.resultBarcodes.joinToString(",")
            )
        }
    }

    private data class EvaluationCaseDefinition(
        val caseId: String,
        val userId: Long,
        val referenceBarcode: String,
        val expectedRelevantBarcodes: Set<String>
    )

    private companion object {
        private val logger = LoggerFactory.getLogger(RecommendationEvaluationRunner::class.java)
    }
}
