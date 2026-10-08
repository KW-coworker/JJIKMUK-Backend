package org.jjikmuk.backend.global.config

import org.jjikmuk.backend.domain.config.SystemConfig
import org.jjikmuk.backend.domain.config.SystemConfigRepository
import org.jjikmuk.backend.domain.recommendation.ProductNeighborSetRepository
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.CommandLineRunner
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.io.FileSystemResource
import org.springframework.core.io.Resource
import org.springframework.core.io.ResourceLoader
import org.springframework.jdbc.core.BatchPreparedStatementSetter
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.transaction.PlatformTransactionManager
import org.springframework.transaction.support.TransactionTemplate
import java.sql.PreparedStatement

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(
    prefix = "recommendation.import",
    name = ["enabled"],
    havingValue = "true"
)
class ProductNeighborInitializer(
    private val neighborRepository: ProductNeighborSetRepository,
    private val systemConfigRepository: SystemConfigRepository,
    private val jdbcTemplate: JdbcTemplate,
    transactionManager: PlatformTransactionManager,
    private val resourceLoader: ResourceLoader,
    @Value("\${recommendation.import.resource:file:src/main/resources/data/ProductNeighbors.csv}")
    private val resourceLocation: String,
    @Value("\${recommendation.import.version:V1.0-CONTENT-NEIGHBORS}")
    private val dataVersion: String,
    @Value("\${recommendation.import.batch-size:500}")
    private val batchSize: Int,
    @Value("\${recommendation.import.expected-rows:233658}")
    private val expectedRows: Long
) {
    private val transactionTemplate = TransactionTemplate(transactionManager)

    @Bean
    fun importProductNeighbors(): CommandLineRunner = CommandLineRunner {
        require(batchSize > 0) { "recommendation.import.batch-size must be greater than zero" }

        val resource = resolveDataResource()
        if (resource == null) {
            logger.warn(
                "ProductNeighbors.csv를 찾지 못해 추천 후보 적재를 건너뜁니다. resource={}",
                resourceLocation
            )
            return@CommandLineRunner
        }

        val storedVersion = systemConfigRepository.findById(VERSION_KEY)
            .map { it.configValue }
            .orElse(null)
        val storedCount = neighborRepository.count()
        if (storedCount > 0 && storedVersion == dataVersion) {
            logger.info("추천 후보가 이미 최신 버전입니다. version={}, rows={}", dataVersion, storedCount)
            return@CommandLineRunner
        }

        // 기존 테이블을 건드리기 전에 CSV 전체를 스트리밍 검증한다.
        val validatedRows = validateResource(resource)
        require(expectedRows <= 0 || validatedRows == expectedRows) {
            "ProductNeighbors.csv record count mismatch: expected $expectedRows, actual $validatedRows"
        }

        logger.info(
            "추천 후보 적재를 시작합니다. resource={}, version={}, rows={}",
            resource.description,
            dataVersion,
            validatedRows
        )

        if (isMySql()) {
            importWithMySqlStaging(resource, validatedRows)
        } else {
            importWithTransactionalReplacement(resource, validatedRows)
        }

        val config = systemConfigRepository.findById(VERSION_KEY)
            .orElse(SystemConfig(configKey = VERSION_KEY, configValue = dataVersion))
        config.updateVersion(dataVersion)
        systemConfigRepository.save(config)
        logger.info("추천 후보 적재 완료: version={}, rows={}", dataVersion, validatedRows)
    }

    private fun validateResource(resource: Resource): Long {
        val seenSources = HashSet<String>(300_000)
        var recordCount = 0L
        resource.inputStream.use { input ->
            ProductNeighborCsvReader(input).use { reader ->
                while (true) {
                    val record = reader.readRecord() ?: break
                    recordCount++
                    require(record.fieldCount == reader.headerCount) {
                        "Recommendation CSV column count mismatch at record $recordCount: " +
                            "expected ${reader.headerCount}, actual ${record.fieldCount}"
                    }
                    require(seenSources.add(record.sourceBarcode)) {
                        "Duplicate source barcode at recommendation record $recordCount: ${record.sourceBarcode}"
                    }
                    if (recordCount % PROGRESS_INTERVAL == 0L) {
                        logger.info("추천 후보 검증 중: records={}", recordCount)
                    }
                }
            }
        }
        return recordCount
    }

    private fun importWithMySqlStaging(resource: Resource, expectedCount: Long) {
        jdbcTemplate.execute("DROP TABLE IF EXISTS $STAGING_TABLE")
        jdbcTemplate.execute("CREATE TABLE $STAGING_TABLE LIKE $MAIN_TABLE")
        try {
            val imported = streamIntoTable(resource, STAGING_TABLE)
            require(imported == expectedCount) {
                "Staging import count mismatch: expected $expectedCount, actual $imported"
            }
            val databaseCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM $STAGING_TABLE",
                Long::class.java
            ) ?: 0L
            require(databaseCount == expectedCount) {
                "Staging database count mismatch: expected $expectedCount, actual $databaseCount"
            }

            jdbcTemplate.execute("DROP TABLE IF EXISTS $OLD_TABLE")
            // MySQL의 다중 RENAME은 원자적이어서 운영 중 빈 테이블이 노출되지 않는다.
            jdbcTemplate.execute(
                "RENAME TABLE $MAIN_TABLE TO $OLD_TABLE, $STAGING_TABLE TO $MAIN_TABLE"
            )
            jdbcTemplate.execute("DROP TABLE $OLD_TABLE")
        } catch (exception: Exception) {
            jdbcTemplate.execute("DROP TABLE IF EXISTS $STAGING_TABLE")
            throw exception
        }
    }

    private fun importWithTransactionalReplacement(resource: Resource, expectedCount: Long) {
        transactionTemplate.executeWithoutResult {
            jdbcTemplate.update("DELETE FROM $MAIN_TABLE")
            val imported = streamIntoTable(resource, MAIN_TABLE)
            require(imported == expectedCount) {
                "Recommendation import count mismatch: expected $expectedCount, actual $imported"
            }
        }
    }

    private fun streamIntoTable(resource: Resource, tableName: String): Long {
        var importedCount = 0L
        resource.inputStream.use { input ->
            ProductNeighborCsvReader(input).use { reader ->
                val batch = ArrayList<ProductNeighborCsvRecord>(batchSize)
                while (true) {
                    val record = reader.readRecord() ?: break
                    batch.add(record)
                    if (batch.size >= batchSize) {
                        insertBatch(tableName, batch)
                        importedCount += batch.size
                        batch.clear()
                    }
                    if ((importedCount + batch.size) % PROGRESS_INTERVAL == 0L) {
                        logger.info("추천 후보 적재 중: records={}", importedCount + batch.size)
                    }
                }
                if (batch.isNotEmpty()) {
                    insertBatch(tableName, batch)
                    importedCount += batch.size
                }
            }
        }
        return importedCount
    }

    private fun insertBatch(tableName: String, records: List<ProductNeighborCsvRecord>) {
        val sql = """
            INSERT INTO $tableName
                (source_barcode, model_version, recommendation_count, recommendations)
            VALUES (?, ?, ?, ?)
        """.trimIndent()
        jdbcTemplate.batchUpdate(
            sql,
            object : BatchPreparedStatementSetter {
                override fun setValues(statement: PreparedStatement, index: Int) {
                    val record = records[index]
                    statement.setString(1, record.sourceBarcode)
                    statement.setString(2, record.modelVersion)
                    statement.setInt(3, record.recommendationCount)
                    statement.setString(4, record.serializedRecommendations())
                }

                override fun getBatchSize(): Int = records.size
            }
        )
    }

    private fun isMySql(): Boolean =
        jdbcTemplate.dataSource?.connection?.use { connection ->
            connection.metaData.databaseProductName.contains("mysql", ignoreCase = true)
        } == true

    private fun resolveDataResource(): Resource? {
        val candidates = listOf(
            resourceLoader.getResource(resourceLocation),
            FileSystemResource("src/main/resources/data/ProductNeighbors.csv"),
            FileSystemResource("backend/src/main/resources/data/ProductNeighbors.csv")
        )
        return candidates.firstOrNull { it.exists() && it.isReadable }
    }

    private companion object {
        private val logger = LoggerFactory.getLogger(ProductNeighborInitializer::class.java)
        private const val VERSION_KEY = "PRODUCT_NEIGHBOR_DB_VERSION"
        private const val PROGRESS_INTERVAL = 50_000L
        private const val MAIN_TABLE = "product_neighbor_sets"
        private const val STAGING_TABLE = "product_neighbor_sets_staging"
        private const val OLD_TABLE = "product_neighbor_sets_old"
    }
}
