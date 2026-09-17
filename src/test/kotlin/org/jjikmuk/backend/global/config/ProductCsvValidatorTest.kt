package org.jjikmuk.backend.global.config

import org.springframework.core.io.ByteArrayResource
import org.springframework.core.io.FileSystemResource
import org.junit.jupiter.api.Assumptions.assumeTrue
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ProductCsvValidatorTest {
    @Test
    fun `full Product csv passes the complete read-only preflight`() {
        assumeTrue(System.getenv("FULL_PRODUCT_CSV_VALIDATION") == "true")
        val csvPath = Path.of("src/main/resources/data/Product.csv")
        assumeTrue(Files.exists(csvPath))

        val report = ProductCsvValidator.validate(FileSystemResource(csvPath), 50_000)

        assertEquals(1_348_436, report.recordCount)
        assertTrue(report.nonEmptyRecordCount > 0)
        assertTrue(report.emptyRecordCount <= 100)
        assertEquals(64, report.sha256.length)
    }

    @Test
    fun `fully validates records and creates a stable source fingerprint`() {
        val csv = csvWithRows(
            row(barcode = "8801234567890", productName = "테스트 상품", energy = "120.5", vegan = "✓"),
            row(barcode = "", productName = "", cleanProductName = "", energy = "", vegan = "false")
        )

        val report = ProductCsvValidator.validate(ByteArrayResource(csv.toByteArray()), 0)

        assertEquals(2, report.recordCount)
        assertEquals(2, report.nonEmptyRecordCount)
        assertEquals(0, report.emptyRecordCount)
        assertEquals(1, report.missingBarcodeCount)
        assertEquals(1, report.missingProductNameCount)
        assertEquals(sha256(csv.toByteArray()), report.sha256)
    }

    @Test
    fun `rejects malformed numeric and dietary flag values`() {
        val invalidNumber = csvWithRows(
            row(barcode = "1", productName = "상품", energy = "one hundred", vegan = "true")
        )
        val numberError = assertFailsWith<IllegalArgumentException> {
            ProductCsvValidator.validate(ByteArrayResource(invalidNumber.toByteArray()), 0)
        }
        assertTrue(numberError.message.orEmpty().contains("energy_kcal"))

        val invalidFlag = csvWithRows(
            row(barcode = "1", productName = "상품", energy = "100", vegan = "maybe")
        )
        val flagError = assertFailsWith<IllegalArgumentException> {
            ProductCsvValidator.validate(ByteArrayResource(invalidFlag.toByteArray()), 0)
        }
        assertTrue(flagError.message.orEmpty().contains("is_vegan"))
    }

    @Test
    fun `rejects a source barcode that collides with generated identifiers`() {
        val csv = csvWithRows(
            row(
                barcode = "NO_BARCODE_ROW_12",
                productName = "상품",
                energy = "100",
                vegan = "true"
            )
        )

        val error = assertFailsWith<IllegalArgumentException> {
            ProductCsvValidator.validate(ByteArrayResource(csv.toByteArray()), 0)
        }

        assertTrue(error.message.orEmpty().contains("Reserved synthetic barcode"))
    }

    private fun row(
        barcode: String,
        productName: String,
        cleanProductName: String = productName,
        energy: String,
        vegan: String
    ): Map<ProductCsvColumn, String> = ProductCsvColumn.entries.associateWith { "" }
        .toMutableMap()
        .apply {
            this[ProductCsvColumn.BARCODE] = barcode
            this[ProductCsvColumn.PRODUCT_NAME] = productName
            this[ProductCsvColumn.CLEAN_PRODUCT_NAME] = cleanProductName
            this[ProductCsvColumn.ENERGY_KCAL] = energy
            this[ProductCsvColumn.VEGAN] = vegan
        }

    private fun csvWithRows(vararg rows: Map<ProductCsvColumn, String>): String = buildString {
        append(ProductCsvColumn.entries.joinToString(",") { it.header })
        append('\n')
        rows.forEach { values ->
            append(ProductCsvColumn.entries.joinToString(",") { values.getValue(it) })
            append('\n')
        }
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes)
        .joinToString("") { byte -> "%02x".format(byte) }
}
