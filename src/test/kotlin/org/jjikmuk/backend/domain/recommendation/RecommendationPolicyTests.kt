package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.product.ProductFilter
import kotlin.test.Test
import kotlin.test.assertEquals

class RecommendationPolicyTests {
    private val policy = RecommendationPolicy()

    @Test
    fun `single-character wheat allergen does not match milk transliteration`() {
        val milkChocolate = Product(
            barcode = "8800000200001",
            productName = "밀크초콜릿",
            rawMaterials = "코코아매스, 밀크초콜릿",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val wheatProduct = Product(
            barcode = "8800000200002",
            productName = "밀 과자",
            allergyWarning = "밀 함유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )

        assertEquals(SafetyStatus.PASS, policy.evaluateSafety(milkChocolate, listOf("밀")).status)
        assertEquals(SafetyStatus.DANGER, policy.evaluateSafety(wheatProduct, listOf("밀")).status)
    }

    @Test
    fun `missing evidence is unknown when user has allergies`() {
        val product = Product(barcode = "8800000200003", productName = "정보 없음")
        assertEquals(SafetyStatus.UNKNOWN, policy.evaluateSafety(product, listOf("우유")).status)
    }

    @Test
    fun `unverified evidence can detect danger but cannot establish pass`() {
        val matching = Product(
            barcode = "8800000200004",
            rawMaterials = "우유, 설탕",
            allergyEvidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED
        )
        val nonMatching = Product(
            barcode = "8800000200005",
            rawMaterials = "대두, 설탕",
            allergyEvidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED
        )

        assertEquals(SafetyStatus.DANGER, policy.evaluateSafety(matching, listOf("우유")).status)
        assertEquals(SafetyStatus.UNKNOWN, policy.evaluateSafety(nonMatching, listOf("우유")).status)
    }

    @Test
    fun `wheat allergen does not match buckwheat flour`() {
        val buckwheat = Product(
            barcode = "8800000200006",
            rawMaterials = "메밀가루, 정제소금",
            allergyWarning = "메밀 함유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )

        assertEquals(SafetyStatus.PASS, policy.evaluateSafety(buckwheat, listOf("밀")).status)
        assertEquals(SafetyStatus.DANGER, policy.evaluateSafety(buckwheat, listOf("메밀")).status)
    }

    @Test
    fun `diet hard constraint distinguishes mismatch unknown and pass`() {
        val mismatch = Product(barcode = "D-1", vegan = false, rawMaterials = "쌀")
        val unknown = Product(
            barcode = "D-2",
            vegan = true,
            dietaryDataOrigin = ProductDataOrigin.INFERRED
        )
        val pass = Product(
            barcode = "D-3",
            vegan = true,
            rawMaterials = "쌀, 소금",
            dietaryDataOrigin = ProductDataOrigin.INFERRED,
            dietaryDataConfidence = 0.8
        )
        val filters = setOf(ProductFilter.VEGAN)

        assertEquals(DietConstraintStatus.MISMATCH, policy.evaluateDietConstraints(mismatch, filters).status)
        assertEquals(DietConstraintStatus.UNKNOWN, policy.evaluateDietConstraints(unknown, filters).status)
        assertEquals(DietConstraintStatus.PASS, policy.evaluateDietConstraints(pass, filters).status)
    }

    @Test
    fun `nutrition hard constraint needs the source nutrient value`() {
        val missingSugar = Product(
            barcode = "N-1",
            lowSugar = true,
            rawMaterials = "대두",
            dietaryDataConfidence = 0.8
        )
        val measuredSugar = Product(
            barcode = "N-2",
            lowSugar = true,
            sugarG = 1.0,
            dietaryDataConfidence = 0.8
        )

        assertEquals(
            DietConstraintStatus.UNKNOWN,
            policy.evaluateDietConstraints(missingSugar, setOf(ProductFilter.LOW_SUGAR)).status
        )
        assertEquals(
            DietConstraintStatus.PASS,
            policy.evaluateDietConstraints(measuredSugar, setOf(ProductFilter.LOW_SUGAR)).status
        )
    }
}
