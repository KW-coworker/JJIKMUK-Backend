package org.jjikmuk.backend.domain.product.search

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.global.config.ProductCsvColumn
import org.jjikmuk.backend.global.config.ProductCsvReader
import org.junit.jupiter.api.Assumptions.assumeTrue
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.Test
import kotlin.test.assertTrue

class ProductSearchRelevanceDatasetTest {
    @Test
    fun `every seed judgment has a matching visible name in Product csv`() {
        assumeTrue(System.getenv("FULL_PRODUCT_CSV_SEARCH_DATASET_VALIDATION") == "true")
        val csvPath = Path.of("src/main/resources/data/Product.csv")
        assumeTrue(Files.exists(csvPath))

        val remaining = ProductSearchRelevanceDataset.cases
            .associateBy(ProductSearchRelevanceCase::caseId)
            .toMutableMap()
        ProductCsvReader(Files.newInputStream(csvPath)).use { reader ->
            while (remaining.isNotEmpty()) {
                val record = reader.readRecord() ?: break
                val product = Product(
                    barcode = record.text(ProductCsvColumn.BARCODE) ?: "MISSING",
                    productName = record.text(ProductCsvColumn.PRODUCT_NAME),
                    cleanProductName = record.text(ProductCsvColumn.CLEAN_PRODUCT_NAME)
                )
                remaining.entries.removeIf { (_, case) ->
                    ProductSearchRelevanceDataset.isRelevant(case, product)
                }
            }
        }

        assertTrue(remaining.isEmpty(), "No Product.csv evidence for: ${remaining.keys}")
    }
}
