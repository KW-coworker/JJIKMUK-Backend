package org.jjikmuk.backend.global.config

import org.jjikmuk.backend.domain.product.Product
import org.junit.jupiter.api.Assumptions.assumeTrue
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.*

class NutritionBasisImportTest {
    @Test fun `legacy CSV without optional basis remains readable and unknown`() {
        val columns = ProductCsvColumn.entries.filterNot { it == ProductCsvColumn.NUTRITION_BASIS_RAW }
        val csv = columns.joinToString(",") { it.header } + "\n" +
            columns.joinToString(",") { if (it == ProductCsvColumn.ENERGY_KCAL) "500" else if (it == ProductCsvColumn.TOTAL_WEIGHT) "44g" else "" } + "\n"
        ProductCsvReader(csv.byteInputStream()).use { reader ->
            val product = requireNotNull(reader.readRecord()).toProduct("legacy")
            assertNull(product.nutritionBasisRaw)
            assertEquals(500.0, product.energyKcal)
            assertEquals("UNKNOWN", product.nutrition.sourceBasis.status)
            assertNull(product.nutrition.perPackage)
        }
    }

    @Test fun `CSV basis survives import and repair refuses identity or numeric mismatches`() {
        val values = arrayOfNulls<String>(ProductCsvColumn.entries.size)
        values[ProductCsvColumn.NUTRITION_BASIS_RAW.ordinal] = "100g"
        values[ProductCsvColumn.PRODUCT_NAME.ordinal] = "포키 녹차"
        values[ProductCsvColumn.ENERGY_KCAL.ordinal] = "500"
        values[ProductCsvColumn.TOTAL_WEIGHT.ordinal] = "44g"
        val row = ProductCsvRecord(values, values.size)
        assertEquals(220.0, row.toProduct("1").nutrition.perPackage!!.values.energyKcal)
        assertEquals("100g", ProductNutritionBasisRepair.basisIfMatching(Product("1", productName = "포키 녹차", energyKcal = 500.0, totalWeight = "44g"), row))
        assertNull(ProductNutritionBasisRepair.basisIfMatching(Product("1", productName = "다른 상품", energyKcal = 500.0, totalWeight = "44g"), row))
        assertNull(ProductNutritionBasisRepair.basisIfMatching(Product("1", productName = "포키 녹차", energyKcal = 220.0, totalWeight = "44g"), row))
        assertNull(ProductNutritionBasisRepair.basisIfMatching(Product("1", productName = "포키 녹차", energyKcal = 500.0, totalWeight = "44g", nutritionBasisRaw = "44g"), row))
    }

    @Test fun `real CSV Pocky barcodes both produce 44g 220kcal`() {
        val path = System.getenv("NUTRITION_TEST_CSV")?.let(Path::of)
        assumeTrue(path != null && Files.exists(path))
        val wanted = setOf("8801019311673", "8801019312137")
        val found = mutableSetOf<String>()
        ProductCsvReader(Files.newInputStream(path!!)).use { reader ->
            while (found.size < wanted.size) {
                val row = reader.readRecord() ?: break
                val barcode = row.text(ProductCsvColumn.BARCODE) ?: continue
                if (barcode !in wanted) continue
                val product = row.toProduct(barcode)
                assertEquals("100g", product.nutritionBasisRaw)
                assertEquals("44g", product.totalWeight)
                assertEquals(500.0, product.energyKcal)
                assertEquals(220.0, product.nutrition.perPackage!!.values.energyKcal)
                found += barcode
            }
        }
        assertEquals(wanted, found)
    }
}
