package org.jjikmuk.backend.domain.product.search

import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.ApplicationRunner
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.core.ResultSetExtractor

/** Fails fast when FULLTEXT mode is enabled before the MySQL index is ready. */
@Configuration(proxyBeanMethods = false)
class ProductSearchIndexVerifier(
    private val jdbcTemplate: JdbcTemplate,
    @Value("\${product.search.mode:locate}")
    private val searchMode: String
) {
    @Bean
    @Order(Ordered.HIGHEST_PRECEDENCE)
    fun verifyProductSearchIndex(): ApplicationRunner = ApplicationRunner {
        if (!searchMode.equals("fulltext", ignoreCase = true)) return@ApplicationRunner

        val databaseProductName = jdbcTemplate.dataSource
            ?.connection
            ?.use { it.metaData.databaseProductName }
            ?: error("검색 인덱스를 검증할 데이터베이스 연결이 없습니다.")
        require(databaseProductName.equals("MySQL", ignoreCase = true)) {
            "product.search.mode=fulltext requires MySQL, actual=$databaseProductName"
        }

        val tokenSize = jdbcTemplate.queryForObject(
            "SELECT @@ngram_token_size",
            Int::class.java
        )
        require(tokenSize == REQUIRED_NGRAM_TOKEN_SIZE) {
            "ngram_token_size must be $REQUIRED_NGRAM_TOKEN_SIZE, actual=$tokenSize"
        }

        val missingKeywords = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM products WHERE search_keywords IS NULL",
            Long::class.java
        ) ?: 0L
        require(missingKeywords == 0L) {
            "FULLTEXT mode cannot start while $missingKeywords search_keywords rows are null"
        }
        val unsearchableRows = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM products WHERE NULLIF(TRIM(search_keywords), '') IS NULL",
            Long::class.java
        ) ?: 0L

        val createTableSql = jdbcTemplate.query(
            "SHOW CREATE TABLE products",
            ResultSetExtractor<String?> { resultSet ->
                if (resultSet.next()) resultSet.getString(2) else null
            }
        ) ?: error("products 테이블 정의를 확인할 수 없습니다.")
        val normalizedDdl = createTableSql.lowercase()
        require(normalizedDdl.contains("ft_products_search_keywords")) {
            "FULLTEXT index ft_products_search_keywords is missing"
        }
        require(normalizedDdl.contains("with parser `ngram`") || normalizedDdl.contains("with parser ngram")) {
            "ft_products_search_keywords must use the ngram parser"
        }

        logger.info(
            "상품 FULLTEXT 검색 인덱스 검증 완료: index={}, ngram_token_size={}, unsearchableRows={}",
            INDEX_NAME,
            tokenSize,
            unsearchableRows
        )
    }

    private companion object {
        private val logger = LoggerFactory.getLogger(ProductSearchIndexVerifier::class.java)
        private const val INDEX_NAME = "ft_products_search_keywords"
        private const val REQUIRED_NGRAM_TOKEN_SIZE = 2
    }
}
