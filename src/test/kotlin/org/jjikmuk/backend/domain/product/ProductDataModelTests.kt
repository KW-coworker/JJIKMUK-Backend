package org.jjikmuk.backend.domain.product

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals

class ProductDataModelTests {
    @Test
    fun `display group key is stable across case and whitespace differences`() {
        val first = ProductGroupKeyBuilder.build(
            productName = " 포키 ",
            manufacturer = "해태 제과",
            rawMaterials = "밀, 우유",
            imageUrl = " https://example.test/pocky.jpg "
        )
        val sameDisplay = ProductGroupKeyBuilder.build(
            productName = "포키",
            manufacturer = "해태   제과",
            rawMaterials = "밀,우유",
            imageUrl = "https://example.test/pocky.jpg"
        )
        val differentManufacturer = ProductGroupKeyBuilder.build(
            productName = "포키",
            manufacturer = "다른 제조사",
            rawMaterials = "밀,우유",
            imageUrl = "https://example.test/pocky.jpg"
        )

        assertEquals(first, sameDisplay)
        assertEquals(64, first.length)
        assertNotEquals(first, differentManufacturer)
    }

    @Test
    fun `legacy allergy evidence is classified conservatively`() {
        assertEquals(
            AllergyEvidenceLevel.DECLARED_LABEL,
            ProductDataQualityClassifier.classifyAllergyEvidence("우유 함유", null, null)
        )
        assertEquals(
            AllergyEvidenceLevel.INGREDIENT_DERIVED,
            ProductDataQualityClassifier.classifyAllergyEvidence(null, "우유, 설탕", null)
        )
        assertEquals(
            AllergyEvidenceLevel.INFERRED,
            ProductDataQualityClassifier.classifyAllergyEvidence(null, null, "우유")
        )
        assertEquals(
            AllergyEvidenceLevel.UNKNOWN,
            ProductDataQualityClassifier.classifyAllergyEvidence(null, null, null)
        )
    }

    @Test
    fun `confidence metadata is constrained to zero through one`() {
        assertFailsWith<IllegalArgumentException> {
            Product(
                barcode = "CONFIDENCE-INVALID",
                allergyDataConfidence = 1.1
            )
        }
    }

    @Test
    fun `csv provenance values become bounded recommendation confidence`() {
        assertEquals(
            ProductDataOrigin.NORMALIZED,
            ProductDataQualityClassifier.nutritionOrigin(
                hasNutrition = true,
                mergeBasis = "barcode",
                matchMethod = "barcode_text_parsed",
                parsedItemCount = 5
            )
        )
        assertEquals(
            0.98,
            ProductDataQualityClassifier.nutritionConfidence(
                ProductDataOrigin.SOURCE,
                matchScore = 98.0,
                parsedItemCount = null
            )
        )
        assertEquals(0.8, ProductDataQualityClassifier.dietaryConfidence(true, 4))
    }
}
