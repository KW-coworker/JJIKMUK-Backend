package org.jjikmuk.backend.domain.product.search

import org.jjikmuk.backend.domain.config.SystemConfig
import org.jjikmuk.backend.domain.config.SystemConfigRepository
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.CommandLineRunner
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.jdbc.core.BatchPreparedStatementSetter
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.transaction.PlatformTransactionManager
import org.springframework.transaction.support.TransactionTemplate
import java.sql.PreparedStatement

/**
 * One-off, resumable backfill for databases populated before search_keywords
 * was introduced. It is disabled by default and commits once per small batch.
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(
    prefix = "product.search.backfill",
    name = ["enabled"],
    havingValue = "true"
)
class ProductSearchKeywordBackfill(
    private val jdbcTemplate: JdbcTemplate,
    private val systemConfigRepository: SystemConfigRepository,
    transactionManager: PlatformTransactionManager,
    @Value("\${product.search.backfill.batch-size:3000}")
    private val batchSize: Int,
    @Value("\${product.search.backfill.delay-ms:100}")
    private val delayMs: Long,
    @Value("\${product.search.keyword-version:v1}")
    private val keywordVersion: String,
    @Value("\${product.search.backfill.rebuild-all:false}")
    private val rebuildAll: Boolean,
    @Value("\${product.search.backfill.allow-when-indexed:false}")
    private val allowWhenIndexed: Boolean
) {
    private val transactionTemplate = TransactionTemplate(transactionManager)

    @Bean
    @Order(100)
    fun backfillProductSearchKeywords(): CommandLineRunner = CommandLineRunner {
        require(batchSize in 1..10_000) {
            "product.search.backfill.batch-size must be between 1 and 10000"
        }
        require(delayMs in 0..60_000) {
            "product.search.backfill.delay-ms must be between 0 and 60000"
        }
        require(keywordVersion.isNotBlank()) { "product.search.keyword-version must not be blank" }

        withMySqlLock {
            runBackfill()
        }
    }

    private fun runBackfill() {
        val storedStatus = configValue(STATUS_KEY)
        val storedKeywordVersion = configValue(KEYWORD_VERSION_KEY)
        require(storedKeywordVersion == null || storedKeywordVersion == keywordVersion || rebuildAll) {
            "Search keyword algorithm changed from $storedKeywordVersion to $keywordVersion. " +
                "Run once with product.search.backfill.rebuild-all=true"
        }
        val mustStartOver = rebuildAll || storedStatus == "COMPLETED" ||
            storedKeywordVersion != keywordVersion

        var lastBarcode = if (mustStartOver) "" else configValue(CHECKPOINT_KEY).orEmpty()
        var updatedCount = 0L

        val missingBefore = countMissingKeywords()
        if (missingBefore == 0L && !rebuildAll) {
            transactionTemplate.executeWithoutResult {
                saveConfig(KEYWORD_VERSION_KEY, keywordVersion)
                saveConfig(STATUS_KEY, "COMPLETED")
                saveConfig(UNSEARCHABLE_COUNT_KEY, countUnsearchableRows().toString())
            }
            logger.info("검색 키워드 백필 대상이 없습니다. keywordVersion={}", keywordVersion)
            return
        }
        if (hasFullTextIndex() && !allowWhenIndexed) {
            error(
                "FULLTEXT index already exists. Backfill would maintain the index row by row; " +
                    "set product.search.backfill.allow-when-indexed=true only in a measured window"
            )
        }

        logger.info(
            "제품 검색 키워드 백필을 시작합니다. checkpoint={}, batchSize={}, rebuildAll={}, " +
                "keywordVersion={}, previousVersion={}, missingBefore={}",
            lastBarcode.ifEmpty { "<start>" },
            batchSize,
            rebuildAll,
            keywordVersion,
            storedKeywordVersion,
            missingBefore
        )

        while (true) {
            val rows = findNextBatch(lastBarcode, rebuildAll)
            if (rows.isEmpty()) break

            transactionTemplate.executeWithoutResult {
                updateBatch(rows)
                saveConfig(CHECKPOINT_KEY, rows.last().barcode)
                saveConfig(STATUS_KEY, "RUNNING")
            }

            lastBarcode = rows.last().barcode
            updatedCount += rows.size
            logger.info(
                "제품 검색 키워드 백필 중: updated={}, checkpoint={}",
                updatedCount,
                lastBarcode
            )

            if (delayMs > 0) Thread.sleep(delayMs)
        }

        val missingAfter = countMissingKeywords()
        require(missingAfter == 0L) {
            "Search keyword backfill left $missingAfter null rows; clear the checkpoint and retry"
        }
        val unsearchableRows = countUnsearchableRows()
        transactionTemplate.executeWithoutResult {
            saveConfig(KEYWORD_VERSION_KEY, keywordVersion)
            saveConfig(STATUS_KEY, "COMPLETED")
            saveConfig(UNSEARCHABLE_COUNT_KEY, unsearchableRows.toString())
        }
        logger.info(
            "제품 검색 키워드 백필을 완료했습니다. updated={}, unsearchable={}",
            updatedCount,
            unsearchableRows
        )
    }

    private fun findNextBatch(
        lastBarcode: String,
        includePopulatedRows: Boolean
    ): List<SearchKeywordSource> = jdbcTemplate.query(
        """
            SELECT barcode, product_name, clean_product_name, manufacturer
            FROM products
            WHERE (? = TRUE OR search_keywords IS NULL)
              AND barcode > ?
            ORDER BY barcode
            LIMIT ?
        """.trimIndent(),
        { resultSet, _ ->
            SearchKeywordSource(
                barcode = resultSet.getString("barcode"),
                productName = resultSet.getString("product_name"),
                cleanProductName = resultSet.getString("clean_product_name"),
                manufacturer = resultSet.getString("manufacturer")
            )
        },
        includePopulatedRows,
        lastBarcode,
        batchSize
    )

    private fun updateBatch(rows: List<SearchKeywordSource>) {
        jdbcTemplate.batchUpdate(
            if (rebuildAll) {
                "UPDATE products SET search_keywords = ? WHERE barcode = ?"
            } else {
                "UPDATE products SET search_keywords = ? WHERE barcode = ? AND search_keywords IS NULL"
            },
            object : BatchPreparedStatementSetter {
                override fun setValues(statement: PreparedStatement, index: Int) {
                    val row = rows[index]
                    statement.setString(
                        1,
                        ProductSearchKeywordBuilder.build(
                            productName = row.productName,
                            cleanProductName = row.cleanProductName,
                            manufacturer = row.manufacturer
                        )
                    )
                    statement.setString(2, row.barcode)
                }

                override fun getBatchSize(): Int = rows.size
            }
        )
    }

    private fun saveConfig(key: String, value: String) {
        val config = systemConfigRepository.findById(key)
            .orElse(SystemConfig(configKey = key, configValue = value))
        config.updateVersion(value)
        systemConfigRepository.save(config)
    }

    private fun configValue(key: String): String? =
        systemConfigRepository.findById(key).map { it.configValue }.orElse(null)

    private fun countMissingKeywords(): Long = jdbcTemplate.queryForObject(
        "SELECT COUNT(*) FROM products WHERE search_keywords IS NULL",
        Long::class.java
    ) ?: 0L

    private fun countUnsearchableRows(): Long = jdbcTemplate.queryForObject(
        "SELECT COUNT(*) FROM products WHERE NULLIF(TRIM(search_keywords), '') IS NULL",
        Long::class.java
    ) ?: 0L

    private fun hasFullTextIndex(): Boolean = (jdbcTemplate.queryForObject(
        """
        SELECT COUNT(*)
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'products'
          AND index_name = 'ft_products_search_keywords'
          AND index_type = 'FULLTEXT'
        """.trimIndent(),
        Long::class.java
    ) ?: 0L) > 0L

    private fun <T> withMySqlLock(block: () -> T): T {
        val dataSource = requireNotNull(jdbcTemplate.dataSource) { "DataSource is unavailable" }
        dataSource.connection.use { connection ->
            require(connection.metaData.databaseProductName.contains("mysql", ignoreCase = true)) {
                "Search keyword backfill currently requires MySQL"
            }
            val acquired = connection.prepareStatement("SELECT GET_LOCK(?, 0)").use { statement ->
                statement.setString(1, MYSQL_LOCK_NAME)
                statement.executeQuery().use { result -> result.next() && result.getInt(1) == 1 }
            }
            require(acquired) { "Another product search maintenance job is already running" }
            try {
                return block()
            } finally {
                runCatching {
                    connection.prepareStatement("SELECT RELEASE_LOCK(?)").use { statement ->
                        statement.setString(1, MYSQL_LOCK_NAME)
                        statement.executeQuery().close()
                    }
                }
            }
        }
    }

    private data class SearchKeywordSource(
        val barcode: String,
        val productName: String?,
        val cleanProductName: String?,
        val manufacturer: String?
    )

    private companion object {
        private val logger = LoggerFactory.getLogger(ProductSearchKeywordBackfill::class.java)
        private const val CHECKPOINT_KEY = "PRODUCT_SEARCH_BACKFILL_LAST_BARCODE"
        private const val STATUS_KEY = "PRODUCT_SEARCH_BACKFILL_STATUS"
        private const val KEYWORD_VERSION_KEY = "PRODUCT_SEARCH_KEYWORD_VERSION"
        private const val UNSEARCHABLE_COUNT_KEY = "PRODUCT_SEARCH_UNSEARCHABLE_ROWS"
        private const val MYSQL_LOCK_NAME = "jjikmuk.products.search-maintenance"
    }
}
