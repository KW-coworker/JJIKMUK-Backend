package org.jjikmuk.backend.domain.recommendation

import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.context.event.EventListener
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.scheduling.annotation.Async
import org.springframework.scheduling.annotation.EnableAsync
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor
import org.springframework.stereotype.Component
import java.time.LocalDateTime
import java.util.concurrent.Executor
import java.util.concurrent.ThreadPoolExecutor

data class RecommendationCompletedEvent(
    val requestId: String,
    val userId: Long,
    val referenceBarcode: String,
    val policyVersion: String,
    val modelVersion: String,
    val precomputedCandidateCount: Int,
    val eligibleCandidateCount: Int,
    val resultCount: Int,
    val resultMode: RecommendationResultMode,
    val fallbackCandidateCount: Int,
    val fallbackResultCount: Int,
    val verificationRequiredResultCount: Int,
    val fallbackReason: RecommendationFallbackReason?,
    val exclusions: RecommendationExclusionSummary,
    val timing: RecommendationTiming,
    val resultBarcodes: String,
    val fallbackBarcodes: String,
    val createdAt: LocalDateTime = LocalDateTime.now()
) {
    companion object {
        fun from(response: ProductRecommendationResponse, userId: Long) = RecommendationCompletedEvent(
            requestId = response.requestId,
            userId = userId,
            referenceBarcode = response.referenceProduct.barcode,
            policyVersion = response.policyVersion,
            modelVersion = response.modelVersion,
            precomputedCandidateCount = response.precomputedCandidateCount,
            eligibleCandidateCount = response.eligibleCandidateCount,
            resultCount = response.items.size,
            resultMode = response.resultMode,
            fallbackCandidateCount = response.fallbackCandidateCount,
            fallbackResultCount = response.fallbackItems.size,
            verificationRequiredResultCount = response.fallbackItems.count(RecommendedProduct::verificationRequired),
            fallbackReason = response.fallbackReason,
            exclusions = response.excluded,
            timing = response.timing,
            resultBarcodes = response.items.joinToString(",") { it.product.barcode },
            fallbackBarcodes = response.fallbackItems.joinToString(",") { it.product.barcode }
        )
    }
}

@Configuration(proxyBeanMethods = false)
@EnableAsync
@ConditionalOnProperty(
    prefix = "recommendation.logging",
    name = ["enabled"],
    havingValue = "true",
    matchIfMissing = true
)
class RecommendationTelemetryConfiguration {
    @Bean("recommendationLogExecutor")
    fun recommendationLogExecutor(): Executor = ThreadPoolTaskExecutor().apply {
        corePoolSize = 1
        maxPoolSize = 2
        queueCapacity = 1_000
        setThreadNamePrefix("recommendation-log-")
        setRejectedExecutionHandler(ThreadPoolExecutor.DiscardPolicy())
        setWaitForTasksToCompleteOnShutdown(true)
        setAwaitTerminationSeconds(5)
        initialize()
    }
}

@Component
@ConditionalOnProperty(
    prefix = "recommendation.logging",
    name = ["enabled"],
    havingValue = "true",
    matchIfMissing = true
)
class RecommendationLogListener(
    private val jdbcTemplate: JdbcTemplate,
    @Value("\${recommendation.logging.store-user-id:false}")
    private val storeUserId: Boolean
) {
    @Async("recommendationLogExecutor")
    @EventListener
    fun record(event: RecommendationCompletedEvent) {
        runCatching {
            jdbcTemplate.update(
                """
                INSERT INTO product_recommendation_logs
                    (request_id, user_id, reference_barcode, policy_version, model_version,
                     precomputed_candidate_count, eligible_candidate_count, result_count,
                     result_mode, fallback_candidate_count, fallback_result_count,
                     verification_required_result_count, fallback_reason,
                     danger_excluded, unknown_safety_excluded, diet_mismatch_excluded,
                     diet_unknown_excluded, disliked_ingredient_excluded,
                     neighbor_lookup_micros, product_fetch_micros, history_fetch_micros,
                     ranking_micros, total_latency_micros, result_barcodes, fallback_barcodes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.trimIndent(),
                event.requestId,
                event.userId.takeIf { storeUserId },
                event.referenceBarcode,
                event.policyVersion,
                event.modelVersion,
                event.precomputedCandidateCount,
                event.eligibleCandidateCount,
                event.resultCount,
                event.resultMode.name,
                event.fallbackCandidateCount,
                event.fallbackResultCount,
                event.verificationRequiredResultCount,
                event.fallbackReason?.name,
                event.exclusions.danger,
                event.exclusions.unknownSafety,
                event.exclusions.dietMismatch,
                event.exclusions.dietUnknown,
                event.exclusions.dislikedIngredient,
                event.timing.neighborLookupMicros,
                event.timing.productFetchMicros,
                event.timing.historyFetchMicros,
                event.timing.rankingMicros,
                event.timing.totalMicros,
                event.resultBarcodes,
                event.fallbackBarcodes,
                event.createdAt
            )
        }.onFailure { exception ->
            logger.warn("추천 실행 로그 저장에 실패했습니다: {}", exception.message)
        }
    }

    private companion object {
        private val logger = LoggerFactory.getLogger(RecommendationLogListener::class.java)
    }
}
