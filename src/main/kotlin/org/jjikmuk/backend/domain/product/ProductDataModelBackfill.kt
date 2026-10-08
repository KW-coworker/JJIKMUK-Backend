package org.jjikmuk.backend.domain.product

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

/** Resumable one-off backfill for the deterministic product display group key. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(
    prefix = "product.data-model.backfill",
    name = ["enabled"],
    havingValue = "true"
)
class ProductDataModelBackfill(
    private val jdbcTemplate: JdbcTemplate,
    private val systemConfigRepository: SystemConfigRepository,
    transactionManager: PlatformTransactionManager,
    @Value("\${product.data-model.backfill.batch-size:1000}")
    private val batchSize: Int,
    @Value("\${product.data-model.backfill.delay-ms:100}")
    private val delayMs: Long
) {
    private val transactionTemplate = TransactionTemplate(transactionManager)

    @Bean
    @Order(110)
    fun backfillProductDataModel(): CommandLineRunner = CommandLineRunner {
        require(batchSize in 1..5_000) {
            "product.data-model.backfill.batch-size must be between 1 and 5000"
        }
        require(delayMs in 0..60_000) {
            "product.data-model.backfill.delay-ms must be between 0 and 60000"
        }

        var lastBarcode = systemConfigRepository.findById(CHECKPOINT_KEY)
            .map { it.configValue }
            .orElse("")
        var updatedCount = 0L

        saveStatus("RUNNING")
        logger.info(
            "상품 데이터 모델 백필을 시작합니다. checkpoint={}, batchSize={}",
            lastBarcode.ifEmpty { "<start>" },
            batchSize
        )

        while (true) {
            val rows = findNextBatch(lastBarcode)
            if (rows.isEmpty()) break

            transactionTemplate.executeWithoutResult {
                updateBatch(rows)
                saveConfig(CHECKPOINT_KEY, rows.last().barcode)
            }

            lastBarcode = rows.last().barcode
            updatedCount += rows.size
            logger.info(
                "상품 데이터 모델 백필 중: updated={}, checkpoint={}",
                updatedCount,
                lastBarcode
            )
            if (delayMs > 0) Thread.sleep(delayMs)
        }

        transactionTemplate.executeWithoutResult {
            saveConfig(STATUS_KEY, "COMPLETED")
            saveConfig(GROUP_KEY_VERSION_KEY, GROUP_KEY_VERSION)
        }
        logger.info("상품 데이터 모델 백필을 완료했습니다. updated={}", updatedCount)
    }

    private fun findNextBatch(lastBarcode: String): List<GroupKeySource> = jdbcTemplate.query(
        """
            SELECT barcode, product_name, manufacturer, raw_materials, image_url,
                   allergy, allergy_warning
            FROM products
            WHERE product_group_key IS NULL
              AND barcode > ?
            ORDER BY barcode
            LIMIT ?
        """.trimIndent(),
        { resultSet, _ ->
            GroupKeySource(
                barcode = resultSet.getString("barcode"),
                productName = resultSet.getString("product_name"),
                manufacturer = resultSet.getString("manufacturer"),
                rawMaterials = resultSet.getString("raw_materials"),
                imageUrl = resultSet.getString("image_url"),
                allergy = resultSet.getString("allergy"),
                allergyWarning = resultSet.getString("allergy_warning")
            )
        },
        lastBarcode,
        batchSize
    )

    private fun updateBatch(rows: List<GroupKeySource>) {
        jdbcTemplate.batchUpdate(
            """
                UPDATE products
                SET product_group_key = ?, allergy_evidence_level = ?
                WHERE barcode = ? AND product_group_key IS NULL
            """.trimIndent(),
            object : BatchPreparedStatementSetter {
                override fun setValues(statement: PreparedStatement, index: Int) {
                    val row = rows[index]
                    statement.setString(
                        1,
                        ProductGroupKeyBuilder.build(
                            productName = row.productName,
                            manufacturer = row.manufacturer,
                            rawMaterials = row.rawMaterials,
                            imageUrl = row.imageUrl
                        )
                    )
                    statement.setString(
                        2,
                        ProductDataQualityClassifier.classifyAllergyEvidence(
                            allergyWarning = row.allergyWarning,
                            rawMaterials = row.rawMaterials,
                            normalizedAllergy = row.allergy
                        ).name
                    )
                    statement.setString(3, row.barcode)
                }

                override fun getBatchSize(): Int = rows.size
            }
        )
    }

    private fun saveStatus(status: String) {
        transactionTemplate.executeWithoutResult { saveConfig(STATUS_KEY, status) }
    }

    private fun saveConfig(key: String, value: String) {
        val config = systemConfigRepository.findById(key)
            .orElse(SystemConfig(configKey = key, configValue = value))
        config.updateVersion(value)
        systemConfigRepository.save(config)
    }

    private data class GroupKeySource(
        val barcode: String,
        val productName: String?,
        val manufacturer: String?,
        val rawMaterials: String?,
        val imageUrl: String?,
        val allergy: String?,
        val allergyWarning: String?
    )

    private companion object {
        private val logger = LoggerFactory.getLogger(ProductDataModelBackfill::class.java)
        private const val CHECKPOINT_KEY = "PRODUCT_DATA_MODEL_BACKFILL_LAST_BARCODE"
        private const val STATUS_KEY = "PRODUCT_DATA_MODEL_BACKFILL_STATUS"
        private const val GROUP_KEY_VERSION_KEY = "PRODUCT_GROUP_KEY_VERSION"
        private const val GROUP_KEY_VERSION = "V1-SHA256-DISPLAY-IDENTITY"
    }
}
