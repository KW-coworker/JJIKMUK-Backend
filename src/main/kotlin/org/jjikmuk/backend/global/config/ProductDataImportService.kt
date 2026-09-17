package org.jjikmuk.backend.global.config

import org.jjikmuk.backend.domain.config.SystemConfig
import org.jjikmuk.backend.domain.config.SystemConfigRepository
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.search.ProductSearchKeywordBuilder
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.core.io.FileSystemResource
import org.springframework.core.io.Resource
import org.springframework.core.io.ResourceLoader
import org.springframework.jdbc.core.BatchPreparedStatementSetter
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.support.GeneratedKeyHolder
import org.springframework.stereotype.Service
import org.springframework.transaction.PlatformTransactionManager
import org.springframework.transaction.support.TransactionTemplate
import java.security.DigestInputStream
import java.security.MessageDigest
import java.sql.Connection
import java.sql.PreparedStatement
import java.sql.Statement
import java.sql.Types
import java.time.LocalDateTime

@Service
class ProductDataImportService(
    private val systemConfigRepository: SystemConfigRepository,
    private val jdbcTemplate: JdbcTemplate,
    transactionManager: PlatformTransactionManager,
    private val resourceLoader: ResourceLoader,
    @Value("\${product.import.enabled:false}")
    private val importEnabled: Boolean,
    @Value("\${product.import.rollback.enabled:false}")
    private val rollbackEnabled: Boolean,
    @Value("\${product.import.resource:file:src/main/resources/data/Product.csv}")
    private val resourceLocation: String,
    @Value("\${product.import.version:V4.0-PRODUCTCSV-RECOMMENDATION-METADATA}")
    private val dataVersion: String,
    @Value("\${product.import.batch-size:500}")
    private val batchSize: Int,
    @Value("\${product.import.expected-rows:1348436}")
    private val expectedRows: Long,
    @Value("\${product.import.validation.max-empty-rows:0}")
    private val maxEmptyRows: Long,
    @Value("\${product.import.validation.max-duplicate-barcodes:20}")
    private val maxDuplicateBarcodes: Long,
    @Value("\${product.import.validation.minimum-named-ratio:0.99}")
    private val minimumNamedRatio: Double
) {
    private val transactionTemplate = TransactionTemplate(transactionManager)

    fun importProducts() {
        validateExclusiveAction(requestingImport = true)
        validateSettings()
        requireMySql()
        withMySqlImportLock {
            reconcileCompletedSwapIfNeeded()

            val currentVersion = configValue(VERSION_KEY)
            val currentCount = tableRowCount(MAIN_TABLE)
            if (currentVersion == dataVersion && currentCount > 0) {
                val recordedCount = configValue(ROW_COUNT_KEY)?.toLongOrNull()
                require(recordedCount == null || recordedCount == currentCount) {
                    "Product version is current but row count differs: recorded=$recordedCount, actual=$currentCount"
                }
                logger.info("제품 데이터가 이미 최신 버전입니다. version={}, rows={}", dataVersion, currentCount)
                return@withMySqlImportLock
            }

            val resource = resolveDataResource()
                ?: error("Product.csv를 찾을 수 없습니다: product.import.resource=$resourceLocation")
            val configSnapshot = snapshotManagedConfigs()
            val runId = startRun("IMPORT", dataVersion, currentVersion, resource.description)
            var swapped = false

            try {
                updateRunStatus(runId, "VALIDATING")
                val report = ProductCsvValidator.validate(resource, PROGRESS_INTERVAL)
                validateReport(report)
                updateValidatedRun(runId, report)

                assertSwapCompatibleSchema()
                prepareStagingTable()
                updateRunStatus(runId, "STAGING")
                val loadReport = streamIntoStaging(resource)
                require(loadReport.attemptedRows == report.nonEmptyRecordCount) {
                    "Staging input count mismatch: validated=${report.nonEmptyRecordCount}, " +
                        "attempted=${loadReport.attemptedRows}"
                }
                require(loadReport.sha256 == report.sha256) {
                    "Product.csv changed between validation and staging load"
                }

                preserveExistingProductIdsIfPresent()
                val stagedCount = validateStagingTable(report)
                val duplicateCount = report.nonEmptyRecordCount - stagedCount
                require(duplicateCount <= maxDuplicateBarcodes) {
                    "Too many duplicate barcodes: maximum=$maxDuplicateBarcodes, actual=$duplicateCount"
                }

                val marker = ProductDatasetMarker(dataVersion, report.sha256, stagedCount)
                writeTableMarker(STAGING_TABLE, marker)
                updateReadyRun(runId, stagedCount, duplicateCount)
                saveConfigs(
                    mapOf(
                        IMPORT_STATUS_KEY to "READY_TO_SWAP",
                        PENDING_VERSION_KEY to dataVersion,
                        PENDING_SHA256_KEY to report.sha256,
                        PENDING_ROW_COUNT_KEY to stagedCount.toString()
                    )
                )

                updateRunStatus(runId, "SWAPPING")
                dropTableIfExists(ROLLBACK_TABLE)
                jdbcTemplate.execute(
                    "RENAME TABLE `$MAIN_TABLE` TO `$ROLLBACK_TABLE`, " +
                        "`$STAGING_TABLE` TO `$MAIN_TABLE`"
                )
                swapped = true

                val rollbackMarker = readTableMarker(ROLLBACK_TABLE)
                saveActivatedDataset(marker, rollbackMarker, currentVersion, currentCount)
                completeRun(runId, stagedCount)
                logger.info(
                    "제품 적재 완료: version={}, sourceRecords={}, activeRows={}, duplicates={}, sha256={}",
                    dataVersion,
                    report.recordCount,
                    stagedCount,
                    duplicateCount,
                    report.sha256
                )
            } catch (exception: Exception) {
                val tableRestored = if (swapped) {
                    restoreLiveTableAfterFailedActivation(exception)
                } else {
                    dropTableIfExists(STAGING_TABLE)
                    true
                }
                if (tableRestored) {
                    runCatching {
                        restoreConfigSnapshot(
                            configSnapshot,
                            if (swapped) "FAILED_ROLLED_BACK" else "FAILED"
                        )
                    }.onFailure(exception::addSuppressed)
                } else {
                    runCatching { saveConfigs(mapOf(IMPORT_STATUS_KEY to "RECOVERY_REQUIRED")) }
                        .onFailure(exception::addSuppressed)
                }
                failRun(runId, exception)
                throw exception
            }
        }
    }

    fun rollbackProducts() {
        validateExclusiveAction(requestingImport = false)
        requireMySql()
        withMySqlImportLock {
            require(tableExists(ROLLBACK_TABLE)) {
                "Rollback table '$ROLLBACK_TABLE' does not exist"
            }
            assertSwapCompatibleSchema()

            val currentVersion = readTableMarker(MAIN_TABLE)?.version ?: configValue(VERSION_KEY)
            val targetMarker = readTableMarker(ROLLBACK_TABLE)
            val targetVersion = targetMarker?.version ?: configValue(ROLLBACK_VERSION_KEY)
                ?: error("Rollback dataset version cannot be determined")
            val configSnapshot = snapshotManagedConfigs()
            val runId = startRun("ROLLBACK", targetVersion, currentVersion, ROLLBACK_TABLE)
            var swapped = false

            try {
                dropTableIfExists(SWAP_TABLE)
                updateRunStatus(runId, "SWAPPING")
                swapMainAndRollbackTables()
                swapped = true

                val activeMarker = readTableMarker(MAIN_TABLE)
                val newRollbackMarker = readTableMarker(ROLLBACK_TABLE)
                val activeCount = tableRowCount(MAIN_TABLE)
                saveActivatedDataset(
                    activeMarker ?: ProductDatasetMarker(
                        version = targetVersion,
                        sha256 = configValue(ROLLBACK_SHA256_KEY) ?: UNKNOWN_SHA256,
                        rowCount = activeCount
                    ),
                    newRollbackMarker,
                    currentVersion,
                    tableRowCount(ROLLBACK_TABLE)
                )
                completeRun(runId, activeCount)
                logger.info(
                    "제품 데이터 롤백 완료: activeVersion={}, activeRows={}, rollbackVersion={}",
                    targetVersion,
                    activeCount,
                    currentVersion
                )
            } catch (exception: Exception) {
                val tableRestored = if (swapped) {
                    runCatching { swapMainAndRollbackTables() }
                        .onFailure(exception::addSuppressed)
                        .isSuccess
                } else {
                    true
                }
                if (tableRestored) {
                    runCatching { restoreConfigSnapshot(configSnapshot, "ROLLBACK_FAILED") }
                        .onFailure(exception::addSuppressed)
                } else {
                    runCatching { saveConfigs(mapOf(IMPORT_STATUS_KEY to "RECOVERY_REQUIRED")) }
                        .onFailure(exception::addSuppressed)
                }
                failRun(runId, exception)
                throw exception
            }
        }
    }

    private fun validateExclusiveAction(requestingImport: Boolean) {
        require(importEnabled.xor(rollbackEnabled)) {
            "Exactly one product data action must be enabled: import=$importEnabled, rollback=$rollbackEnabled"
        }
        require(if (requestingImport) importEnabled else rollbackEnabled) {
            "Requested product data action is not enabled"
        }
    }

    private fun validateSettings() {
        require(batchSize > 0) { "product.import.batch-size must be greater than zero" }
        require(expectedRows > 0) { "product.import.expected-rows must be greater than zero" }
        require(maxEmptyRows >= 0) { "max-empty-rows must not be negative" }
        require(maxDuplicateBarcodes >= 0) { "max-duplicate-barcodes must not be negative" }
        require(minimumNamedRatio in 0.0..1.0) { "minimum-named-ratio must be between 0 and 1" }
        require(dataVersion.isNotBlank()) { "product.import.version must not be blank" }
    }

    private fun validateReport(report: ProductCsvValidationReport) {
        require(report.recordCount == expectedRows) {
            "Product.csv record count mismatch: expected $expectedRows, actual ${report.recordCount}"
        }
        require(report.nonEmptyRecordCount > 0) { "Product.csv has no importable records" }
        require(report.emptyRecordCount <= maxEmptyRows) {
            "Too many empty records: maximum=$maxEmptyRows, actual=${report.emptyRecordCount}"
        }
        val namedCount = report.nonEmptyRecordCount - report.missingProductNameCount
        val namedRatio = namedCount.toDouble() / report.nonEmptyRecordCount.toDouble()
        require(namedRatio >= minimumNamedRatio) {
            "Product-name coverage is too low: minimum=$minimumNamedRatio, actual=$namedRatio"
        }
    }

    private fun prepareStagingTable() {
        dropTableIfExists(STAGING_TABLE)
        jdbcTemplate.execute("CREATE TABLE `$STAGING_TABLE` LIKE `$MAIN_TABLE`")
        if (columnExists(MAIN_TABLE, PRODUCT_ID_COLUMN)) {
            val currentMaxId = jdbcTemplate.queryForObject(
                "SELECT COALESCE(MAX(`$PRODUCT_ID_COLUMN`), 0) FROM `$MAIN_TABLE`",
                Long::class.java
            ) ?: 0L
            require(currentMaxId < Long.MAX_VALUE) { "product_id sequence is exhausted" }
            jdbcTemplate.execute(
                "ALTER TABLE `$STAGING_TABLE` AUTO_INCREMENT = ${currentMaxId + 1}"
            )
        }
    }

    private fun streamIntoStaging(resource: Resource): StagingLoadReport {
        val digest = MessageDigest.getInstance("SHA-256")
        var recordCount = 0L
        var attemptedCount = 0L
        resource.inputStream.use { rawInput ->
            DigestInputStream(rawInput, digest).use { digestInput ->
                ProductCsvReader(digestInput).use { reader ->
                    val batch = ArrayList<Product>(batchSize)
                    while (true) {
                        val record = reader.readRecord() ?: break
                        recordCount++
                        require(record.fieldCount == reader.headerCount) {
                            "CSV column count changed during staging at record $recordCount"
                        }
                        if (record.isEmpty()) continue

                        val sourceBarcode = record.text(ProductCsvColumn.BARCODE)
                        require(sourceBarcode?.startsWith(SYNTHETIC_BARCODE_PREFIX) != true) {
                            "Source barcode uses reserved prefix at record $recordCount: $sourceBarcode"
                        }
                        val barcode = sourceBarcode ?: "$SYNTHETIC_BARCODE_PREFIX$recordCount"
                        batch.add(record.toProduct(barcode))

                        if (batch.size >= batchSize) {
                            insertBatch(batch)
                            attemptedCount += batch.size
                            batch.clear()
                        }
                        if ((attemptedCount + batch.size) % PROGRESS_INTERVAL == 0L) {
                            logger.info("제품 스테이징 적재 중: records={}", attemptedCount + batch.size)
                        }
                    }
                    if (batch.isNotEmpty()) {
                        insertBatch(batch)
                        attemptedCount += batch.size
                    }
                }
            }
        }
        return StagingLoadReport(
            attemptedRows = attemptedCount,
            sha256 = digest.digest().joinToString("") { byte -> "%02x".format(byte) }
        )
    }

    private fun insertBatch(products: List<Product>) {
        transactionTemplate.executeWithoutResult {
            jdbcTemplate.batchUpdate(
                INSERT_STAGING_SQL,
                object : BatchPreparedStatementSetter {
                    override fun setValues(statement: PreparedStatement, index: Int) {
                        bindProduct(statement, products[index])
                    }

                    override fun getBatchSize(): Int = products.size
                }
            )
        }
    }

    private fun preserveExistingProductIdsIfPresent() {
        if (!columnExists(MAIN_TABLE, PRODUCT_ID_COLUMN)) return
        val currentMaxId = jdbcTemplate.queryForObject(
            "SELECT COALESCE(MAX(`$PRODUCT_ID_COLUMN`), 0) FROM `$MAIN_TABLE`",
            Long::class.java
        ) ?: 0L
        val barcodeMatches = jdbcTemplate.update(
            """
            UPDATE `$STAGING_TABLE` staged
            INNER JOIN `$MAIN_TABLE` live ON live.barcode = staged.barcode
            SET staged.`$PRODUCT_ID_COLUMN` = live.`$PRODUCT_ID_COLUMN`
            WHERE LEFT(staged.barcode, ${SYNTHETIC_BARCODE_PREFIX.length}) <> '$SYNTHETIC_BARCODE_PREFIX'
            """.trimIndent()
        )
        dropTableIfExists(PRODUCT_ID_MAP_TABLE)
        try {
            jdbcTemplate.execute(
                """
                CREATE TABLE `$PRODUCT_ID_MAP_TABLE` (
                    product_group_key CHAR(64) NOT NULL,
                    product_id BIGINT UNSIGNED NOT NULL,
                    PRIMARY KEY (product_group_key),
                    UNIQUE KEY uk_product_id_preservation_map_id (product_id)
                )
                """.trimIndent()
            )
            jdbcTemplate.update(
                """
                INSERT INTO `$PRODUCT_ID_MAP_TABLE` (product_group_key, product_id)
                SELECT live.product_group_key, MIN(live.`$PRODUCT_ID_COLUMN`)
                FROM `$MAIN_TABLE` live
                INNER JOIN (
                    SELECT product_group_key
                    FROM `$MAIN_TABLE`
                    WHERE product_group_key IS NOT NULL
                    GROUP BY product_group_key
                    HAVING COUNT(*) = 1
                ) live_unique ON live_unique.product_group_key = live.product_group_key
                INNER JOIN (
                    SELECT product_group_key
                    FROM `$STAGING_TABLE`
                    WHERE product_group_key IS NOT NULL
                      AND `$PRODUCT_ID_COLUMN` > $currentMaxId
                    GROUP BY product_group_key
                    HAVING COUNT(*) = 1
                ) staged_unique ON staged_unique.product_group_key = live.product_group_key
                LEFT JOIN `$STAGING_TABLE` already_used
                    ON already_used.`$PRODUCT_ID_COLUMN` = live.`$PRODUCT_ID_COLUMN`
                WHERE already_used.`$PRODUCT_ID_COLUMN` IS NULL
                GROUP BY live.product_group_key
                """.trimIndent()
            )
            val groupMatches = jdbcTemplate.update(
                """
                UPDATE `$STAGING_TABLE` staged
                INNER JOIN `$PRODUCT_ID_MAP_TABLE` identity_map
                    ON identity_map.product_group_key = staged.product_group_key
                SET staged.`$PRODUCT_ID_COLUMN` = identity_map.product_id
                WHERE staged.`$PRODUCT_ID_COLUMN` > $currentMaxId
                """.trimIndent()
            )
            logger.info(
                "기존 내부 product_id 보존 완료: barcodeMatches={}, uniqueGroupMatches={}",
                barcodeMatches,
                groupMatches
            )
        } finally {
            dropTableIfExists(PRODUCT_ID_MAP_TABLE)
        }
    }

    private fun validateStagingTable(report: ProductCsvValidationReport): Long {
        val stagedCount = tableRowCount(STAGING_TABLE)
        require(stagedCount in 1..report.nonEmptyRecordCount) {
            "Invalid staging row count: source=${report.nonEmptyRecordCount}, staged=$stagedCount"
        }
        val invalidBarcodeCount = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM `$STAGING_TABLE` WHERE barcode IS NULL OR TRIM(barcode) = ''",
            Long::class.java
        ) ?: 0L
        require(invalidBarcodeCount == 0L) {
            "Staging contains $invalidBarcodeCount rows without an effective barcode"
        }
        val missingNameCount = jdbcTemplate.queryForObject(
            """
            SELECT COUNT(*) FROM `$STAGING_TABLE`
            WHERE NULLIF(TRIM(product_name), '') IS NULL
              AND NULLIF(TRIM(clean_product_name), '') IS NULL
            """.trimIndent(),
            Long::class.java
        ) ?: 0L
        require(missingNameCount <= report.missingProductNameCount) {
            "Staging lost product names: sourceMissing=${report.missingProductNameCount}, stagedMissing=$missingNameCount"
        }
        if (columnExists(STAGING_TABLE, PRODUCT_ID_COLUMN)) {
            val distinctIds = jdbcTemplate.queryForObject(
                "SELECT COUNT(DISTINCT `$PRODUCT_ID_COLUMN`) FROM `$STAGING_TABLE`",
                Long::class.java
            ) ?: 0L
            require(distinctIds == stagedCount) {
                "Staging product_id uniqueness check failed: rows=$stagedCount, ids=$distinctIds"
            }
        }
        return stagedCount
    }

    private fun assertSwapCompatibleSchema() {
        require(tableExists(MAIN_TABLE)) { "The products table does not exist" }
        val actualColumns = jdbcTemplate.queryForList(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = ?
            """.trimIndent(),
            String::class.java,
            MAIN_TABLE
        ).toSet()
        val missingColumns = DATABASE_COLUMNS.filterNot(actualColumns::contains)
        require(missingColumns.isEmpty()) {
            "Products schema is missing importer columns: ${missingColumns.joinToString()}"
        }

        val incomingForeignKeys = jdbcTemplate.queryForObject(
            """
            SELECT COUNT(*)
            FROM information_schema.key_column_usage
            WHERE referenced_table_schema = DATABASE()
              AND referenced_table_name = ?
            """.trimIndent(),
            Long::class.java,
            MAIN_TABLE
        ) ?: 0L
        require(incomingForeignKeys == 0L) {
            "Atomic table replacement is unsafe: $incomingForeignKeys foreign keys reference products"
        }
        val outgoingForeignKeys = jdbcTemplate.queryForObject(
            """
            SELECT COUNT(*)
            FROM information_schema.key_column_usage
            WHERE table_schema = DATABASE()
              AND table_name = ?
              AND referenced_table_name IS NOT NULL
            """.trimIndent(),
            Long::class.java,
            MAIN_TABLE
        ) ?: 0L
        require(outgoingForeignKeys == 0L) {
            "CREATE TABLE LIKE would omit $outgoingForeignKeys outgoing product foreign keys"
        }
        val triggerCount = jdbcTemplate.queryForObject(
            """
            SELECT COUNT(*)
            FROM information_schema.triggers
            WHERE trigger_schema = DATABASE() AND event_object_table = ?
            """.trimIndent(),
            Long::class.java,
            MAIN_TABLE
        ) ?: 0L
        require(triggerCount == 0L) {
            "CREATE TABLE LIKE would omit $triggerCount product triggers"
        }
    }

    private fun saveActivatedDataset(
        activeMarker: ProductDatasetMarker,
        rollbackMarker: ProductDatasetMarker?,
        fallbackRollbackVersion: String?,
        fallbackRollbackRows: Long
    ) {
        val values = linkedMapOf(
            VERSION_KEY to activeMarker.version,
            SHA256_KEY to activeMarker.sha256,
            ROW_COUNT_KEY to activeMarker.rowCount.toString(),
            IMPORT_STATUS_KEY to "COMPLETED"
        )
        val rollbackVersion = rollbackMarker?.version
            ?: fallbackRollbackVersion
            ?: UNVERSIONED_DATASET.takeIf { fallbackRollbackRows > 0 }
        if (rollbackVersion != null) values[ROLLBACK_VERSION_KEY] = rollbackVersion
        values[ROLLBACK_SHA256_KEY] = rollbackMarker?.sha256 ?: UNKNOWN_SHA256
        values[ROLLBACK_ROW_COUNT_KEY] = (rollbackMarker?.rowCount ?: fallbackRollbackRows).toString()
        saveConfigs(values, PENDING_CONFIG_KEYS)
    }

    private fun reconcileCompletedSwapIfNeeded() {
        val marker = readTableMarker(MAIN_TABLE) ?: return
        if (marker.version != dataVersion || configValue(VERSION_KEY) == dataVersion) return
        val actualCount = tableRowCount(MAIN_TABLE)
        require(actualCount == marker.rowCount) {
            "Active product table marker does not match its row count: marker=${marker.rowCount}, actual=$actualCount"
        }
        val rollbackMarker = readTableMarker(ROLLBACK_TABLE)
        saveActivatedDataset(
            marker,
            rollbackMarker,
            configValue(VERSION_KEY),
            if (tableExists(ROLLBACK_TABLE)) tableRowCount(ROLLBACK_TABLE) else 0L
        )
        logger.warn("완료된 테이블 교체의 버전 메타데이터를 복구했습니다. version={}", marker.version)
    }

    private fun restoreLiveTableAfterFailedActivation(originalFailure: Exception): Boolean =
        runCatching {
            require(tableExists(ROLLBACK_TABLE)) { "Rollback table disappeared after activation" }
            dropTableIfExists(STAGING_TABLE)
            jdbcTemplate.execute(
                "RENAME TABLE `$MAIN_TABLE` TO `$STAGING_TABLE`, `$ROLLBACK_TABLE` TO `$MAIN_TABLE`"
            )
            dropTableIfExists(STAGING_TABLE)
        }.onFailure(originalFailure::addSuppressed).isSuccess

    private fun swapMainAndRollbackTables() {
        jdbcTemplate.execute(
            "RENAME TABLE `$MAIN_TABLE` TO `$SWAP_TABLE`, " +
                "`$ROLLBACK_TABLE` TO `$MAIN_TABLE`, `$SWAP_TABLE` TO `$ROLLBACK_TABLE`"
        )
    }

    private fun writeTableMarker(tableName: String, marker: ProductDatasetMarker) {
        val encoded = marker.encode()
        require(encoded.length <= 1024) { "Dataset marker is too long for a table comment" }
        jdbcTemplate.execute(
            "ALTER TABLE `$tableName` COMMENT = '${encoded.replace("'", "''")}'"
        )
    }

    private fun readTableMarker(tableName: String): ProductDatasetMarker? {
        if (!tableExists(tableName)) return null
        val comment = jdbcTemplate.queryForObject(
            """
            SELECT table_comment
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = ?
            """.trimIndent(),
            String::class.java,
            tableName
        )
        return ProductDatasetMarker.decode(comment)
    }

    private fun startRun(
        action: String,
        version: String,
        previousVersion: String?,
        resourceDescription: String
    ): Long {
        val keyHolder = GeneratedKeyHolder()
        jdbcTemplate.update({ connection ->
            connection.prepareStatement(
                """
                INSERT INTO product_data_import_runs
                    (import_action, dataset_version, previous_dataset_version,
                     resource_description, status, started_at)
                VALUES (?, ?, ?, ?, 'STARTED', ?)
                """.trimIndent(),
                Statement.RETURN_GENERATED_KEYS
            ).apply {
                setString(1, action)
                setString(2, version.take(100))
                setString(3, previousVersion?.take(100))
                setString(4, resourceDescription.take(1000))
                setObject(5, LocalDateTime.now())
            }
        }, keyHolder)
        return requireNotNull(keyHolder.key).toLong()
    }

    private fun updateRunStatus(runId: Long, status: String) {
        jdbcTemplate.update(
            "UPDATE product_data_import_runs SET status = ? WHERE import_id = ?",
            status,
            runId
        )
    }

    private fun updateValidatedRun(runId: Long, report: ProductCsvValidationReport) {
        jdbcTemplate.update(
            """
            UPDATE product_data_import_runs
            SET status = 'VALIDATED', source_sha256 = ?, source_record_count = ?,
                non_empty_record_count = ?, empty_record_count = ?,
                missing_barcode_count = ?, missing_product_name_count = ?
            WHERE import_id = ?
            """.trimIndent(),
            report.sha256,
            report.recordCount,
            report.nonEmptyRecordCount,
            report.emptyRecordCount,
            report.missingBarcodeCount,
            report.missingProductNameCount,
            runId
        )
    }

    private fun updateReadyRun(runId: Long, stagedCount: Long, duplicateCount: Long) {
        jdbcTemplate.update(
            """
            UPDATE product_data_import_runs
            SET status = 'READY_TO_SWAP', staged_row_count = ?, duplicate_barcode_count = ?
            WHERE import_id = ?
            """.trimIndent(),
            stagedCount,
            duplicateCount,
            runId
        )
    }

    private fun completeRun(runId: Long, activeCount: Long) {
        jdbcTemplate.update(
            """
            UPDATE product_data_import_runs
            SET status = 'COMPLETED', active_row_count = ?, finished_at = ?
            WHERE import_id = ?
            """.trimIndent(),
            activeCount,
            LocalDateTime.now(),
            runId
        )
    }

    private fun failRun(runId: Long, exception: Exception) {
        runCatching {
            jdbcTemplate.update(
                """
                UPDATE product_data_import_runs
                SET status = 'FAILED', error_message = ?, finished_at = ?
                WHERE import_id = ?
                """.trimIndent(),
                (exception.message ?: exception::class.java.simpleName).take(4000),
                LocalDateTime.now(),
                runId
            )
        }.onFailure { auditFailure -> exception.addSuppressed(auditFailure) }
    }

    private fun saveConfigs(values: Map<String, String>, keysToDelete: Set<String> = emptySet()) {
        transactionTemplate.executeWithoutResult {
            if (keysToDelete.isNotEmpty()) {
                systemConfigRepository.deleteAllById(keysToDelete)
            }
            val existing = systemConfigRepository.findAllById(values.keys)
                .associateBy(SystemConfig::configKey)
            val configs = values.map { (key, value) ->
                existing[key]?.apply { updateVersion(value) }
                    ?: SystemConfig(configKey = key, configValue = value)
            }
            systemConfigRepository.saveAll(configs)
        }
    }

    private fun configValue(key: String): String? =
        systemConfigRepository.findById(key).map(SystemConfig::configValue).orElse(null)

    private fun snapshotManagedConfigs(): Map<String, String> =
        systemConfigRepository.findAllById(MANAGED_CONFIG_KEYS)
            .associate { config -> config.configKey to config.configValue }

    private fun restoreConfigSnapshot(snapshot: Map<String, String>, status: String) {
        val restored = snapshot.toMutableMap().apply { put(IMPORT_STATUS_KEY, status) }
        saveConfigs(restored, MANAGED_CONFIG_KEYS - restored.keys)
    }

    private fun tableExists(tableName: String): Boolean =
        (jdbcTemplate.queryForObject(
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = ?
            """.trimIndent(),
            Long::class.java,
            tableName
        ) ?: 0L) > 0L

    private fun columnExists(tableName: String, columnName: String): Boolean =
        (jdbcTemplate.queryForObject(
            """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = ? AND column_name = ?
            """.trimIndent(),
            Long::class.java,
            tableName,
            columnName
        ) ?: 0L) > 0L

    private fun tableRowCount(tableName: String): Long =
        jdbcTemplate.queryForObject("SELECT COUNT(*) FROM `$tableName`", Long::class.java) ?: 0L

    private fun dropTableIfExists(tableName: String) {
        jdbcTemplate.execute("DROP TABLE IF EXISTS `$tableName`")
    }

    private fun requireMySql() {
        require(databaseProductName().contains("mysql", ignoreCase = true)) {
            "Safe product table replacement currently requires MySQL; database=${databaseProductName()}"
        }
    }

    private fun databaseProductName(): String =
        jdbcTemplate.dataSource?.connection?.use(Connection::getMetaData)?.databaseProductName
            ?: "unknown"

    private fun <T> withMySqlImportLock(block: () -> T): T {
        val dataSource = requireNotNull(jdbcTemplate.dataSource) { "DataSource is unavailable" }
        dataSource.connection.use { lockConnection ->
            val acquired = lockConnection.prepareStatement("SELECT GET_LOCK(?, 0)").use { statement ->
                statement.setString(1, MYSQL_IMPORT_LOCK)
                statement.executeQuery().use { result -> result.next() && result.getInt(1) == 1 }
            }
            require(acquired) { "Another product import or rollback is already running" }
            try {
                return block()
            } finally {
                runCatching {
                    lockConnection.prepareStatement("SELECT RELEASE_LOCK(?)").use { statement ->
                        statement.setString(1, MYSQL_IMPORT_LOCK)
                        statement.executeQuery().close()
                    }
                }
            }
        }
    }

    private fun resolveDataResource(): Resource? {
        val candidates = listOf(
            resourceLoader.getResource(resourceLocation),
            FileSystemResource("src/main/resources/data/Product.csv"),
            FileSystemResource("backend/src/main/resources/data/Product.csv")
        )
        return candidates.firstOrNull { it.exists() && it.isReadable }
    }

    private fun bindProduct(statement: PreparedStatement, product: Product) {
        var index = 1
        statement.setString(index++, product.barcode)
        statement.setString(index++, product.productName)
        statement.setString(index++, product.manufacturer)
        statement.setString(index++, product.reportNo)
        statement.setString(index++, product.allergy)
        statement.setString(index++, product.nutrientText)
        statement.setString(index++, product.imageUrl)
        statement.setString(index++, product.source)
        statement.setString(index++, product.rawMaterials)
        statement.setNullableDouble(index++, product.energyKcal)
        statement.setNullableDouble(index++, product.carbsG)
        statement.setNullableDouble(index++, product.proteinG)
        statement.setNullableDouble(index++, product.fatG)
        statement.setNullableDouble(index++, product.sugarG)
        statement.setNullableDouble(index++, product.sodiumMg)
        statement.setNullableDouble(index++, product.cholesterolMg)
        statement.setString(index++, product.allergyWarning)
        statement.setString(index++, product.cleanProductName)
        statement.setString(index++, product.totalWeight)
        statement.setString(index++, product.foodType)
        statement.setNullableDouble(index++, product.carbsPercent)
        statement.setNullableDouble(index++, product.proteinPercent)
        statement.setNullableDouble(index++, product.fatPercent)
        statement.setNullableDouble(index++, product.sodiumG)
        statement.setNullableDouble(index++, product.cholesterolG)
        statement.setBoolean(index++, product.vegan)
        statement.setBoolean(index++, product.lactoVegetarian)
        statement.setBoolean(index++, product.ovoVegetarian)
        statement.setBoolean(index++, product.lactoOvoVegetarian)
        statement.setBoolean(index++, product.pescatarian)
        statement.setBoolean(index++, product.pollotarian)
        statement.setBoolean(index++, product.lowSugar)
        statement.setBoolean(index++, product.lowSodium)
        statement.setBoolean(index++, product.glutenFree)
        statement.setBoolean(index++, product.lowCalorie)
        statement.setBoolean(index++, product.lowFat)
        statement.setBoolean(index++, product.highProtein)
        statement.setString(
            index++,
            ProductSearchKeywordBuilder.build(
                productName = product.productName,
                cleanProductName = product.cleanProductName,
                manufacturer = product.manufacturer
            )
        )
        statement.setString(index++, product.productGroupKey)
        statement.setString(index++, product.allergyEvidenceLevel.name)
        statement.setNullableDouble(index++, product.allergyDataConfidence)
        statement.setString(index++, product.nutritionDataOrigin.name)
        statement.setNullableDouble(index++, product.nutritionDataConfidence)
        statement.setString(index++, product.dietaryDataOrigin.name)
        statement.setNullableDouble(index, product.dietaryDataConfidence)
    }

    private fun PreparedStatement.setNullableDouble(index: Int, value: Double?) {
        if (value == null) setNull(index, Types.DOUBLE) else setDouble(index, value)
    }

    private companion object {
        private val logger = LoggerFactory.getLogger(ProductDataImportService::class.java)
        private const val PROGRESS_INTERVAL = 50_000L
        private const val MAIN_TABLE = "products"
        private const val STAGING_TABLE = "products_staging"
        private const val ROLLBACK_TABLE = "products_rollback"
        private const val SWAP_TABLE = "products_swap"
        private const val PRODUCT_ID_MAP_TABLE = "products_id_preservation_map"
        private const val PRODUCT_ID_COLUMN = "product_id"
        private const val SYNTHETIC_BARCODE_PREFIX = "NO_BARCODE_ROW_"
        private const val MYSQL_IMPORT_LOCK = "jjikmuk.products.data-import"
        private const val UNVERSIONED_DATASET = "UNVERSIONED"
        private const val UNKNOWN_SHA256 =
            "0000000000000000000000000000000000000000000000000000000000000000"

        private const val VERSION_KEY = "PRODUCT_DB_VERSION"
        private const val SHA256_KEY = "PRODUCT_DB_SHA256"
        private const val ROW_COUNT_KEY = "PRODUCT_DB_ROW_COUNT"
        private const val ROLLBACK_VERSION_KEY = "PRODUCT_DB_ROLLBACK_VERSION"
        private const val ROLLBACK_SHA256_KEY = "PRODUCT_DB_ROLLBACK_SHA256"
        private const val ROLLBACK_ROW_COUNT_KEY = "PRODUCT_DB_ROLLBACK_ROW_COUNT"
        private const val IMPORT_STATUS_KEY = "PRODUCT_DB_IMPORT_STATUS"
        private const val PENDING_VERSION_KEY = "PRODUCT_DB_PENDING_VERSION"
        private const val PENDING_SHA256_KEY = "PRODUCT_DB_PENDING_SHA256"
        private const val PENDING_ROW_COUNT_KEY = "PRODUCT_DB_PENDING_ROW_COUNT"
        private val PENDING_CONFIG_KEYS = setOf(
            PENDING_VERSION_KEY,
            PENDING_SHA256_KEY,
            PENDING_ROW_COUNT_KEY
        )
        private val MANAGED_CONFIG_KEYS = setOf(
            VERSION_KEY,
            SHA256_KEY,
            ROW_COUNT_KEY,
            ROLLBACK_VERSION_KEY,
            ROLLBACK_SHA256_KEY,
            ROLLBACK_ROW_COUNT_KEY,
            IMPORT_STATUS_KEY
        ) + PENDING_CONFIG_KEYS

        private val DATABASE_COLUMNS = listOf(
            "barcode", "product_name", "manufacturer", "report_no", "allergy",
            "nutrient_text", "image_url", "source", "raw_materials", "energy_kcal",
            "carbs_g", "protein_g", "fat_g", "sugar_g", "sodium_mg",
            "cholesterol_mg", "allergy_warning", "clean_product_name", "total_weight", "food_type",
            "carbs_percent", "protein_percent", "fat_percent", "sodium_g", "cholesterol_g",
            "is_vegan", "is_lacto_vegetarian", "is_ovo_vegetarian",
            "is_lacto_ovo_vegetarian", "is_pescatarian", "is_pollotarian",
            "is_low_sugar", "is_low_sodium", "is_gluten_free", "is_low_calorie",
            "is_low_fat", "is_high_protein", "search_keywords", "product_group_key",
            "allergy_evidence_level", "allergy_data_confidence", "nutrition_data_origin",
            "nutrition_data_confidence", "dietary_data_origin", "dietary_data_confidence"
        )

        private val INSERT_STAGING_SQL = """
            INSERT INTO `$STAGING_TABLE` (${DATABASE_COLUMNS.joinToString { "`$it`" }})
            VALUES (${DATABASE_COLUMNS.joinToString { "?" }})
            ON DUPLICATE KEY UPDATE barcode = barcode
        """.trimIndent()
    }

    private data class StagingLoadReport(
        val attemptedRows: Long,
        val sha256: String
    )
}
