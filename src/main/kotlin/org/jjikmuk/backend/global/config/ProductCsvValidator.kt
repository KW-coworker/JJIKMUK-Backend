package org.jjikmuk.backend.global.config

import org.jjikmuk.backend.domain.allergy.FoodAllergy
import org.jjikmuk.backend.domain.product.AllergyClassificationState
import org.jjikmuk.backend.domain.product.ProductFoodCategory
import org.slf4j.LoggerFactory
import org.springframework.core.io.Resource
import java.security.DigestInputStream
import java.security.MessageDigest

internal data class ProductCsvValidationReport(
    val recordCount: Long,
    val nonEmptyRecordCount: Long,
    val emptyRecordCount: Long,
    val missingBarcodeCount: Long,
    val missingProductNameCount: Long,
    val sha256: String
)

/** Performs a complete parse before the live table is touched. */
internal object ProductCsvValidator {
    private val logger = LoggerFactory.getLogger(ProductCsvValidator::class.java)
    private val numericColumns = listOf(
        ProductCsvColumn.ENERGY_KCAL,
        ProductCsvColumn.CARBS_G,
        ProductCsvColumn.PROTEIN_G,
        ProductCsvColumn.FAT_G,
        ProductCsvColumn.SUGAR_G,
        ProductCsvColumn.SODIUM_MG,
        ProductCsvColumn.CHOLESTEROL_MG,
        ProductCsvColumn.CARBS_PERCENT,
        ProductCsvColumn.PROTEIN_PERCENT,
        ProductCsvColumn.FAT_PERCENT,
        ProductCsvColumn.SODIUM_G,
        ProductCsvColumn.CHOLESTEROL_G
    )
    private val flagColumns = listOf(
        ProductCsvColumn.VEGAN,
        ProductCsvColumn.LACTO_VEGETARIAN,
        ProductCsvColumn.OVO_VEGETARIAN,
        ProductCsvColumn.LACTO_OVO_VEGETARIAN,
        ProductCsvColumn.PESCATARIAN,
        ProductCsvColumn.POLLOTARIAN,
        ProductCsvColumn.LOW_SUGAR,
        ProductCsvColumn.LOW_SODIUM,
        ProductCsvColumn.GLUTEN_FREE,
        ProductCsvColumn.LOW_CALORIE,
        ProductCsvColumn.LOW_FAT,
        ProductCsvColumn.HIGH_PROTEIN
    )

    fun validate(resource: Resource, progressInterval: Long = 50_000L): ProductCsvValidationReport {
        val digest = MessageDigest.getInstance("SHA-256")
        var recordCount = 0L
        var nonEmptyRecordCount = 0L
        var emptyRecordCount = 0L
        var missingBarcodeCount = 0L
        var missingProductNameCount = 0L

        resource.inputStream.use { rawInput ->
            DigestInputStream(rawInput, digest).use { digestInput ->
                ProductCsvReader(digestInput).use { reader ->
                    while (true) {
                        val record = reader.readRecord() ?: break
                        recordCount++
                        require(record.fieldCount == reader.headerCount) {
                            "CSV column count mismatch at record $recordCount: " +
                                "expected ${reader.headerCount}, actual ${record.fieldCount}"
                        }
                        if (record.isEmpty()) {
                            emptyRecordCount++
                            continue
                        }
                        nonEmptyRecordCount++
                        validateTypedValues(record, recordCount)
                        val barcode = record.text(ProductCsvColumn.BARCODE)
                        require(barcode?.startsWith("NO_BARCODE_ROW_") != true) {
                            "Reserved synthetic barcode prefix at record $recordCount: $barcode"
                        }
                        if (barcode == null) missingBarcodeCount++
                        if (
                            record.text(ProductCsvColumn.PRODUCT_NAME) == null &&
                            record.text(ProductCsvColumn.CLEAN_PRODUCT_NAME) == null
                        ) {
                            missingProductNameCount++
                        }
                        if (progressInterval > 0 && recordCount % progressInterval == 0L) {
                            logger.info("제품 CSV 검증 중: records={}", recordCount)
                        }
                    }
                }
            }
        }

        val report = ProductCsvValidationReport(
            recordCount = recordCount,
            nonEmptyRecordCount = nonEmptyRecordCount,
            emptyRecordCount = emptyRecordCount,
            missingBarcodeCount = missingBarcodeCount,
            missingProductNameCount = missingProductNameCount,
            sha256 = digest.digest().joinToString("") { byte -> "%02x".format(byte) }
        )
        logger.info(
            "제품 CSV 검증 완료: records={}, nonEmpty={}, empty={}, missingBarcode={}, " +
                "missingProductName={}, sha256={}",
            report.recordCount,
            report.nonEmptyRecordCount,
            report.emptyRecordCount,
            report.missingBarcodeCount,
            report.missingProductNameCount,
            report.sha256
        )
        return report
    }

    private fun validateTypedValues(record: ProductCsvRecord, recordNumber: Long) {
        numericColumns.forEach { column ->
            val rawValue = record.text(column) ?: return@forEach
            require(record.number(column) != null) {
                "Invalid numeric value at record $recordNumber, column ${column.header}: $rawValue"
            }
        }
        flagColumns.forEach { column ->
            val rawValue = record.text(column) ?: return@forEach
            require(record.isRecognizedFlag(column)) {
                "Invalid flag value at record $recordNumber, column ${column.header}: $rawValue"
            }
        }
        validateClassification(
            record = record,
            recordNumber = recordNumber,
            column = ProductCsvColumn.FOOD_CATEGORIES,
            allowed = FOOD_CATEGORY_LABELS,
            sentinels = setOf(ProductFoodCategory.UNCLASSIFIED.displayName)
        )
        validateClassification(
            record = record,
            recordNumber = recordNumber,
            column = ProductCsvColumn.ALLERGY_CLASSIFICATION,
            allowed = ALLERGY_CLASSIFICATION_LABELS,
            sentinels = ALLERGY_SENTINELS
        )
    }

    private fun validateClassification(
        record: ProductCsvRecord,
        recordNumber: Long,
        column: ProductCsvColumn,
        allowed: Set<String>,
        sentinels: Set<String>
    ) {
        val rawValue = record.text(column)
        require(rawValue != null) {
            "Missing classification value at record $recordNumber, column ${column.header}"
        }
        val tokens = rawValue.split('|').map(String::trim)
        require(tokens.none(String::isBlank)) {
            "Empty classification token at record $recordNumber, column ${column.header}: $rawValue"
        }
        require(tokens.size == tokens.distinct().size) {
            "Duplicate classification token at record $recordNumber, column ${column.header}: $rawValue"
        }
        val unsupported = tokens.filterNot(allowed::contains)
        require(unsupported.isEmpty()) {
            "Unsupported classification at record $recordNumber, column ${column.header}: ${unsupported.joinToString()}"
        }
        require(tokens.size == 1 || tokens.none(sentinels::contains)) {
            "Classification sentinel cannot be combined at record $recordNumber, column ${column.header}: $rawValue"
        }
    }

    private val FOOD_CATEGORY_LABELS = ProductFoodCategory.entries.map(ProductFoodCategory::displayName).toSet()
    private val ALLERGY_SENTINELS = setOf(
        AllergyClassificationState.NOT_DETECTED.displayName,
        AllergyClassificationState.NO_INFORMATION.displayName
    )
    private val ALLERGY_CLASSIFICATION_LABELS =
        FoodAllergy.entries.map(FoodAllergy::displayName).toSet() + ALLERGY_SENTINELS
}
