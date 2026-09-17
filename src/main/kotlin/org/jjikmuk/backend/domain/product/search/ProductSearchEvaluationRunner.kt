package org.jjikmuk.backend.domain.product.search

import org.jjikmuk.backend.domain.config.SystemConfigRepository
import org.jjikmuk.backend.domain.product.DistinctProductSearchRepository
import org.jjikmuk.backend.domain.product.Product
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
    prefix = "product.search.evaluation",
    name = ["enabled"],
    havingValue = "true"
)
class ProductSearchEvaluationRunner(
    private val searchRepository: DistinctProductSearchRepository,
    private val systemConfigRepository: SystemConfigRepository,
    private val jdbcTemplate: JdbcTemplate,
    @Value("\${product.search.evaluation.warmup-runs:1}")
    private val warmupRuns: Int,
    @Value("\${product.search.evaluation.measurement-runs:3}")
    private val measurementRuns: Int,
    @Value("\${product.search.evaluation.minimum-hit-rate:0.8}")
    private val minimumHitRate: Double,
    @Value("\${product.search.evaluation.minimum-mrr:0.5}")
    private val minimumMrr: Double,
    @Value("\${product.search.evaluation.minimum-pair-overlap:0.8}")
    private val minimumPairOverlap: Double,
    @Value("\${product.search.evaluation.maximum-p95-ms:1000}")
    private val maximumP95Ms: Long
) {
    @Bean
    @Order(200)
    fun evaluateProductSearch(): CommandLineRunner = CommandLineRunner {
        require(warmupRuns in 0..10) { "warmup-runs must be between 0 and 10" }
        require(measurementRuns in 1..20) { "measurement-runs must be between 1 and 20" }
        require(minimumHitRate in 0.0..1.0) { "minimum-hit-rate must be between 0 and 1" }
        require(minimumMrr in 0.0..1.0) { "minimum-mrr must be between 0 and 1" }
        require(minimumPairOverlap in 0.0..1.0) { "minimum-pair-overlap must be between 0 and 1" }
        require(maximumP95Ms > 0) { "maximum-p95-ms must be positive" }
        val databaseName = jdbcTemplate.dataSource?.connection?.use {
            it.metaData.databaseProductName
        }.orEmpty()
        require(databaseName.contains("mysql", ignoreCase = true)) {
            "Product search evaluation requires MySQL, actual=$databaseName"
        }

        repeat(warmupRuns) {
            ProductSearchRelevanceDataset.cases.forEach { case ->
                searchRepository.searchByProductName(case.query, case.topK)
            }
        }

        val report = ProductSearchRelevanceEvaluator.evaluate(
            ProductSearchRelevanceDataset.cases
        ) { case -> measuredSearch(case) }
        val passed = passesThresholds(report)
        val runId = saveRun(report, passed)
        saveResults(runId, report.results)

        logger.info(
            "상품 검색 평가 완료: runId={}, dataset={}, mode={}, Hit@K={}, MRR={}, " +
                "zeroRate={}, avgMicros={}, p95Micros={}, pairOverlap={}",
            runId,
            ProductSearchRelevanceDataset.VERSION,
            searchRepository.activeSearchMode(),
            report.hitRateAtK,
            report.meanReciprocalRank,
            report.zeroResultRate,
            report.averageLatencyMicros,
            report.p95LatencyMicros,
            report.pairTopKOverlap
        )
        require(passed) {
            "Product search relevance gate failed: Hit@K=${report.hitRateAtK}, " +
                "MRR=${report.meanReciprocalRank}, p95Micros=${report.p95LatencyMicros}, " +
                "pairOverlap=${report.pairTopKOverlap}"
        }
    }

    private fun measuredSearch(case: ProductSearchRelevanceCase): TimedProducts {
        var products = emptyList<Product>()
        var totalNanos = 0L
        repeat(measurementRuns) {
            val startedAt = System.nanoTime()
            products = searchRepository.searchByProductName(case.query, case.topK)
            totalNanos += System.nanoTime() - startedAt
        }
        return TimedProducts(
            products = products,
            latencyMicros = totalNanos / measurementRuns / 1_000
        )
    }

    private fun passesThresholds(report: ProductSearchEvaluationReport): Boolean =
        report.hitRateAtK >= minimumHitRate &&
            report.meanReciprocalRank >= minimumMrr &&
            report.p95LatencyMicros <= maximumP95Ms * 1_000 &&
            report.pairTopKOverlap.values.all { it >= minimumPairOverlap }

    private fun saveRun(report: ProductSearchEvaluationReport, passed: Boolean): Long {
        val keyHolder = GeneratedKeyHolder()
        val mysqlVersion = jdbcTemplate.queryForObject("SELECT VERSION()", String::class.java)
            ?: "unknown"
        val ngramTokenSize = jdbcTemplate.queryForObject("SELECT @@ngram_token_size", Int::class.java)
        val productDataVersion = systemConfigRepository.findById("PRODUCT_DB_VERSION")
            .map { it.configValue }
            .orElse("UNKNOWN")
        jdbcTemplate.update({ connection ->
            connection.prepareStatement(
                """
                INSERT INTO product_search_evaluation_runs
                    (dataset_version, search_mode, mysql_version, ngram_token_size,
                     case_count, hit_rate_at_k, mean_reciprocal_rank, zero_result_rate,
                     average_latency_micros, p95_latency_micros, average_result_count,
                     passed, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.trimIndent(),
                Statement.RETURN_GENERATED_KEYS
            ).apply {
                setString(1, "$productDataVersion:${ProductSearchRelevanceDataset.VERSION}".take(100))
                setString(2, searchRepository.activeSearchMode())
                setString(3, mysqlVersion.take(100))
                setObject(4, ngramTokenSize)
                setInt(5, report.results.size)
                setDouble(6, report.hitRateAtK)
                setDouble(7, report.meanReciprocalRank)
                setDouble(8, report.zeroResultRate)
                setDouble(9, report.averageLatencyMicros)
                setLong(10, report.p95LatencyMicros)
                setDouble(11, report.averageResultCount)
                setBoolean(12, passed)
                setObject(13, LocalDateTime.now())
            }
        }, keyHolder)
        return requireNotNull(keyHolder.key).toLong()
    }

    private fun saveResults(runId: Long, results: List<ProductSearchCaseEvaluation>) {
        val sql = """
            INSERT INTO product_search_evaluation_results
                (evaluation_run_id, case_id, query_text, top_k, first_relevant_rank,
                 result_count, latency_micros, passed, top_barcodes, top_product_names)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """.trimIndent()
        results.forEach { result ->
            jdbcTemplate.update(
                sql,
                runId,
                result.case.caseId,
                result.case.query,
                result.case.topK,
                result.firstRelevantRank,
                result.products.size,
                result.latencyMicros,
                result.passed,
                result.products.joinToString(",") { it.barcode },
                result.products.joinToString(" | ") { it.productName.orEmpty() }
            )
        }
    }

    private companion object {
        private val logger = LoggerFactory.getLogger(ProductSearchEvaluationRunner::class.java)
    }
}
