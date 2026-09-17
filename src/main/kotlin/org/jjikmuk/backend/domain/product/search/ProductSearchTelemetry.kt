package org.jjikmuk.backend.domain.product.search

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
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.LocalDateTime
import java.util.concurrent.Executor
import java.util.concurrent.ThreadPoolExecutor

data class ProductSearchPerformedEvent(
    val userId: Long?,
    val endpoint: String,
    val normalizedQuery: String?,
    val compactQueryHash: String?,
    val appliedFilters: String?,
    val matchMode: String?,
    val searchMode: String,
    val resultCount: Long,
    val latencyMicros: Long,
    val createdAt: LocalDateTime = LocalDateTime.now()
) {
    companion object {
        fun create(
            userId: Long?,
            endpoint: String,
            query: String?,
            filters: Collection<String>,
            matchMode: String?,
            searchMode: String,
            resultCount: Long,
            latencyNanos: Long
        ): ProductSearchPerformedEvent {
            val normalizedQuery = query
                ?.let(ProductSearchKeywordBuilder::normalizeForLog)
                ?.takeIf(String::isNotBlank)
                ?.take(MAX_QUERY_LENGTH)
            val compactQuery = normalizedQuery
                ?.let(ProductSearchKeywordBuilder::normalizeQuery)
                ?.takeIf(String::isNotBlank)
            return ProductSearchPerformedEvent(
                userId = userId,
                endpoint = endpoint.take(20),
                normalizedQuery = normalizedQuery,
                compactQueryHash = compactQuery?.let(::sha256),
                appliedFilters = filters.sorted().joinToString(",")
                    .takeIf(String::isNotEmpty)
                    ?.take(500),
                matchMode = matchMode?.take(10),
                searchMode = searchMode.take(20),
                resultCount = resultCount.coerceAtLeast(0),
                latencyMicros = (latencyNanos / 1_000).coerceAtLeast(0)
            )
        }

        private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(StandardCharsets.UTF_8))
            .joinToString("") { byte -> "%02x".format(byte) }

        private const val MAX_QUERY_LENGTH = 200
    }
}

@Configuration(proxyBeanMethods = false)
@EnableAsync
@ConditionalOnProperty(
    prefix = "product.search.logging",
    name = ["enabled"],
    havingValue = "true",
    matchIfMissing = true
)
class ProductSearchTelemetryConfiguration {
    @Bean("productSearchLogExecutor")
    fun productSearchLogExecutor(): Executor = ThreadPoolTaskExecutor().apply {
        corePoolSize = 1
        maxPoolSize = 2
        queueCapacity = 1_000
        setThreadNamePrefix("product-search-log-")
        setRejectedExecutionHandler(ThreadPoolExecutor.DiscardPolicy())
        setWaitForTasksToCompleteOnShutdown(true)
        setAwaitTerminationSeconds(5)
        initialize()
    }
}

@Component
@ConditionalOnProperty(
    prefix = "product.search.logging",
    name = ["enabled"],
    havingValue = "true",
    matchIfMissing = true
)
class ProductSearchLogListener(
    private val jdbcTemplate: JdbcTemplate,
    @Value("\${product.search.logging.store-query-text:true}")
    private val storeQueryText: Boolean,
    @Value("\${product.search.logging.store-user-id:false}")
    private val storeUserId: Boolean
) {
    @Async("productSearchLogExecutor")
    @EventListener
    fun record(event: ProductSearchPerformedEvent) {
        runCatching {
            jdbcTemplate.update(
                """
                INSERT INTO product_search_logs
                    (user_id, endpoint, normalized_query, compact_query_hash,
                     applied_filters, match_mode, search_mode, result_count,
                     latency_micros, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.trimIndent(),
                event.userId.takeIf { storeUserId },
                event.endpoint,
                event.normalizedQuery.takeIf { storeQueryText },
                event.compactQueryHash,
                event.appliedFilters,
                event.matchMode,
                event.searchMode,
                event.resultCount,
                event.latencyMicros,
                event.createdAt
            )
        }.onFailure { exception ->
            logger.warn("상품 검색 로그 저장에 실패했습니다: {}", exception.message)
        }
    }

    private companion object {
        private val logger = LoggerFactory.getLogger(ProductSearchLogListener::class.java)
    }
}
