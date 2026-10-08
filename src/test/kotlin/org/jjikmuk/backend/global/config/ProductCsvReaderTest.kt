package org.jjikmuk.backend.global.config

import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.nio.file.Path
import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.junit.jupiter.api.Assumptions.assumeTrue
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ProductCsvReaderTest {
    @Test
    fun `full Product csv has the expected logical records and duplicate barcodes`() {
        assumeTrue(System.getenv("FULL_PRODUCT_CSV_TEST") == "true")
        val csvPath = Path.of("src/main/resources/data/Product.csv")
        assumeTrue(Files.exists(csvPath))

        var recordCount = 0L
        var duplicateBarcodeCount = 0L
        val seenBarcodes = HashSet<String>(300_000)

        ProductCsvReader(Files.newInputStream(csvPath)).use { reader ->
            while (true) {
                val record = reader.readRecord() ?: break
                recordCount++
                assertEquals(reader.headerCount, record.fieldCount, "record $recordCount")
                record.text(ProductCsvColumn.BARCODE)?.let { barcode ->
                    if (!seenBarcodes.add(barcode)) duplicateBarcodeCount++
                }
            }
        }

        assertEquals(1_348_436L, recordCount)
        assertEquals(11L, duplicateBarcodeCount)
    }

    @Test
    fun `reads selected columns across commas quotes and embedded newlines`() {
        val headers = ProductCsvColumn.entries.map { it.header } + listOf("unused_extra")
        val values = ProductCsvColumn.entries.associateWith { "" }.toMutableMap().apply {
            this[ProductCsvColumn.BARCODE] = "8801234567890"
            this[ProductCsvColumn.PRODUCT_NAME] = "테스트, 스낵"
            this[ProductCsvColumn.CLEAN_PRODUCT_NAME] = "테스트 스낵"
            this[ProductCsvColumn.MANUFACTURER] = "테스트 제조사"
            this[ProductCsvColumn.RAW_MATERIALS] = "정제수\r\n식물성 원료 \"A\""
            this[ProductCsvColumn.ENERGY_KCAL] = "120.5"
            this[ProductCsvColumn.VEGAN] = "✓"
            this[ProductCsvColumn.LOW_SODIUM] = "false"
            this[ProductCsvColumn.FOOD_SUBCATEGORY] = "스낵과자"
            this[ProductCsvColumn.NUTRITION_MATCH_METHOD] = "report_exact"
            this[ProductCsvColumn.NUTRITION_MATCH_SCORE] = "100"
            this[ProductCsvColumn.RAW_MATERIAL_MATCH_SCORE] = "95"
            this[ProductCsvColumn.FOOD_CATEGORIES] = "과자·스낵|디저트·빙과"
            this[ProductCsvColumn.ALLERGY_CLASSIFICATION] = "우유|밀"
        }
        val csv = buildString {
            append('\uFEFF')
            append(headers.joinToString(",") { csvField(it) })
            append("\r\n")
            append(ProductCsvColumn.entries.joinToString(",") { csvField(values.getValue(it)) })
            append(",ignored\r\n")
        }

        ProductCsvReader(ByteArrayInputStream(csv.toByteArray(Charsets.UTF_8))).use { reader ->
            val record = requireNotNull(reader.readRecord())

            assertEquals(headers.size, reader.headerCount)
            assertEquals(headers.size, record.fieldCount)
            assertEquals("8801234567890", record.text(ProductCsvColumn.BARCODE))
            assertEquals("테스트, 스낵", record.text(ProductCsvColumn.PRODUCT_NAME))
            assertEquals("정제수\r\n식물성 원료 \"A\"", record.text(ProductCsvColumn.RAW_MATERIALS))
            assertEquals(120.5, record.number(ProductCsvColumn.ENERGY_KCAL))
            assertTrue(record.flag(ProductCsvColumn.VEGAN))
            assertFalse(record.flag(ProductCsvColumn.LOW_SODIUM))
            val product = record.toProduct("8801234567890")
            assertEquals(64, product.productGroupKey?.length)
            assertEquals(AllergyEvidenceLevel.INGREDIENT_DERIVED, product.allergyEvidenceLevel)
            assertEquals("스낵과자", product.foodType)
            assertEquals("과자·스낵|디저트·빙과", product.foodCategories)
            assertEquals(listOf("snack", "dessert"), product.foodCategoryIds)
            assertEquals("우유|밀", product.allergyClassification)
            assertEquals(listOf("milk", "wheat"), product.allergyClassificationIds)
            assertEquals("detected", product.allergyClassificationState)
            assertEquals(0.9, product.allergyDataConfidence)
            assertEquals(ProductDataOrigin.SOURCE, product.nutritionDataOrigin)
            assertEquals(1.0, product.nutritionDataConfidence)
            assertEquals(0.7, product.dietaryDataConfidence)
            assertNull(reader.readRecord())
        }
    }

    @Test
    fun `generated classification sentinels do not make an otherwise empty row non-empty`() {
        val values = arrayOfNulls<String>(ProductCsvColumn.entries.size)
        values[ProductCsvColumn.FOOD_CATEGORIES.ordinal] = "미분류"
        values[ProductCsvColumn.ALLERGY_CLASSIFICATION.ordinal] = "정보없음"

        assertTrue(ProductCsvRecord(values, ProductCsvColumn.entries.size).isEmpty())
    }

    @Test
    fun `rejects a file missing a required Product csv column`() {
        val incompleteHeader = ProductCsvColumn.entries
            .filterNot { it == ProductCsvColumn.HIGH_PROTEIN }
            .joinToString(",") { it.header }

        val error = kotlin.runCatching {
            ProductCsvReader(
                ByteArrayInputStream("$incompleteHeader\n".toByteArray(Charsets.UTF_8))
            )
        }.exceptionOrNull()

        assertTrue(error is IllegalArgumentException)
        assertTrue(error?.message?.contains("is_high_protein") == true)
    }

    private fun csvField(value: String): String =
        if (value.any { it == ',' || it == '"' || it == '\r' || it == '\n' }) {
            "\"${value.replace("\"", "\"\"")}\""
        } else {
            value
        }
}
