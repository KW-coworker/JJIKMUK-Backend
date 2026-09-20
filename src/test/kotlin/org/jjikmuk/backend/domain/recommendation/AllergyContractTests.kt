package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.AllergySafetyService
import org.jjikmuk.backend.domain.allergy.FoodAllergy
import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class AllergyContractTests {
    private val safety = AllergySafetyService()

    @Test
    fun `the public allergen contract contains exactly 26 stable IDs`() {
        val expected = setOf(
            "egg", "milk", "soy", "wheat", "pork", "chicken", "shrimp", "crab", "squid",
            "mackerel", "shellfish", "oyster", "mussel", "abalone", "peach", "tomato",
            "peanut", "walnut", "buckwheat", "pine_nut", "sulfites", "sesame", "almond",
            "mustard", "celery", "beef"
        )

        assertEquals(expected, FoodAllergy.entries.map(FoodAllergy::id).toSet())
        assertEquals(expected.size, FoodAllergy.entries.size)
        FoodAllergy.entries.forEach { allergy ->
            assertEquals(allergy, AllergyCatalog.resolve(allergy.id))
            assertTrue(allergy.displayName.isNotBlank())
        }
    }

    @Test
    fun `legacy Korean names are resolved to canonical IDs`() {
        assertEquals(FoodAllergy.EGG, AllergyCatalog.resolve("난류"))
        assertEquals(FoodAllergy.EGG, AllergyCatalog.resolve("계란"))
        assertEquals(FoodAllergy.WHEAT, AllergyCatalog.resolve("밀가루"))
        assertEquals(FoodAllergy.BEEF, AllergyCatalog.resolve("쇠고기"))
        assertEquals(FoodAllergy.SHELLFISH, AllergyCatalog.resolve("조개류"))

        val profile = AllergyCatalog.parse("우유, 밀가루; almond | 호두")
        assertEquals(
            listOf(FoodAllergy.MILK, FoodAllergy.WHEAT, FoodAllergy.ALMOND, FoodAllergy.WALNUT),
            profile.ids
        )
        assertTrue(profile.unknownTerms.isEmpty())
        assertEquals("milk,wheat,almond,walnut", AllergyCatalog.normalizeForStorage("우유, 밀가루; almond | 호두"))
        assertEquals("wheat", AllergyCatalog.normalizeForStorage("밀, wheat, 밀가루"))
        assertEquals(
            listOf(FoodAllergy.WALNUT, FoodAllergy.PINE_NUT, FoodAllergy.ALMOND),
            AllergyCatalog.parse("견과류").ids
        )
    }

    @Test
    fun `all 26 IDs detect their corresponding Korean label`() {
        FoodAllergy.entries.forEach { allergy ->
            val product = Product(
                barcode = "TEST-${allergy.id}",
                allergyWarning = "${allergy.displayName} 함유",
                allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
            )

            val decision = safety.evaluate(product, listOf(allergy.id))

            assertEquals(SafetyStatus.DANGER, decision.status, allergy.id)
            assertEquals(listOf(allergy.id), decision.conflictingAllergens, allergy.id)
            assertTrue("allergy_warning" in decision.evidenceSources, allergy.id)
        }
    }

    @Test
    fun `wheat does not match buckwheat or Korean milk transliteration`() {
        val buckwheat = Product(
            barcode = "BUCKWHEAT",
            rawMaterials = "메밀가루, 정제소금",
            allergyWarning = "메밀 함유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val milkChocolate = Product(
            barcode = "MILK-CHOCOLATE",
            rawMaterials = "코코아매스, 밀크초콜릿",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )

        assertEquals(SafetyStatus.PASS, safety.evaluate(buckwheat, listOf("wheat")).status)
        assertEquals(SafetyStatus.PASS, safety.evaluate(milkChocolate, listOf("wheat")).status)
        assertEquals(SafetyStatus.DANGER, safety.evaluate(buckwheat, listOf("buckwheat")).status)
    }

    @Test
    fun `shellfish parent conflicts with children but generic evidence cannot clear subtype`() {
        val oyster = Product(
            barcode = "OYSTER",
            rawMaterials = "굴, 소금",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val genericShellfish = Product(
            barcode = "GENERIC-SHELLFISH",
            rawMaterials = "정제수, 소금",
            allergyWarning = "조개류 함유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )

        assertEquals(listOf("shellfish"), safety.evaluate(oyster, listOf("shellfish")).conflictingAllergens)
        assertEquals(SafetyStatus.DANGER, safety.evaluate(genericShellfish, listOf("shellfish")).status)
        assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(genericShellfish, listOf("oyster")).status)
    }

    @Test
    fun `broad ingredient groups cannot establish safety for an individual allergen`() {
        val cases = listOf(
            "견과류" to "almond",
            "갑각류" to "shrimp",
            "어류" to "mackerel",
            "콩류" to "soy"
        )
        cases.forEach { (ingredientGroup, allergyId) ->
            val product = Product(
                barcode = "GROUP-$allergyId",
                rawMaterials = "정제수, $ingredientGroup",
                allergyEvidenceLevel = AllergyEvidenceLevel.VERIFIED_SOURCE
            )
            assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(product, listOf(allergyId)).status)
        }
    }

    @Test
    fun `walnut pine nut and almond remain separate allergens`() {
        val almond = Product(
            barcode = "ALMOND",
            rawMaterials = "아몬드, 정제수",
            allergyEvidenceLevel = AllergyEvidenceLevel.VERIFIED_SOURCE
        )

        assertEquals(SafetyStatus.DANGER, safety.evaluate(almond, listOf("almond")).status)
        assertEquals(SafetyStatus.PASS, safety.evaluate(almond, listOf("walnut")).status)
        assertEquals(SafetyStatus.PASS, safety.evaluate(almond, listOf("pine_nut")).status)
    }

    @Test
    fun `common ingredient compounds must not be classified as safe`() {
        val cases = listOf(
            "콩가루" to "soy",
            "잣가루" to "pine_nut",
            "조개육수" to "shellfish"
        )

        cases.forEach { (ingredient, allergyId) ->
            val product = Product(
                barcode = "COMPOUND-$allergyId",
                rawMaterials = "$ingredient, 정제수",
                allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
            )
            assertEquals(SafetyStatus.DANGER, safety.evaluate(product, listOf(allergyId)).status, ingredient)
        }
    }

    @Test
    fun `warning alone can prove danger but cannot prove absence`() {
        val warning = Product(
            barcode = "WARNING-ONLY",
            allergyWarning = "우유가 포함된 제품과 같은 시설에서 제조",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )

        assertEquals(SafetyStatus.DANGER, safety.evaluate(warning, listOf("milk")).status)
        assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(warning, listOf("wheat")).status)
    }

    @Test
    fun `classification can prove presence but its negative sentinels never prove safety`() {
        val classified = Product(
            barcode = "CLASSIFIED",
            allergyClassification = "우유|밀"
        )
        val notDetected = Product(
            barcode = "NOT-DETECTED",
            allergyClassification = "미검출"
        )
        val noInformation = Product(
            barcode = "NO-INFORMATION",
            allergyClassification = "정보없음"
        )

        val danger = safety.evaluate(classified, listOf("milk"))
        assertEquals(SafetyStatus.DANGER, danger.status)
        assertEquals(listOf("milk"), danger.conflictingAllergens)
        assertTrue("allergy_classification" in danger.evidenceSources)
        assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(notDetected, listOf("milk")).status)
        assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(noInformation, listOf("milk")).status)
    }

    @Test
    fun `missing evidence and unsupported profile terms never silently pass`() {
        val noEvidence = Product(barcode = "NO-EVIDENCE")
        val completeEvidence = Product(
            barcode = "COMPLETE-EVIDENCE",
            rawMaterials = "정제수, 설탕",
            allergyEvidenceLevel = AllergyEvidenceLevel.VERIFIED_SOURCE
        )

        assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(noEvidence, listOf("milk")).status)
        assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(completeEvidence, listOf("unknown-allergen")).status)
        assertEquals(listOf("unknown-allergen"), AllergyCatalog.parse("unknown-allergen").unknownTerms)
        assertFailsWith<IllegalArgumentException> {
            AllergyCatalog.normalizeForStorage("unknown-allergen")
        }
    }

    @Test
    fun `extended allergens need verified source to pass`() {
        val declaredOnly = Product(
            barcode = "EXTENDED-DECLARED",
            rawMaterials = "쌀, 소금",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val verified = Product(
            barcode = "EXTENDED-VERIFIED",
            rawMaterials = "쌀, 소금",
            allergyEvidenceLevel = AllergyEvidenceLevel.VERIFIED_SOURCE
        )

        listOf("sesame", "almond", "mustard", "celery").forEach { allergyId ->
            assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(declaredOnly, listOf(allergyId)).status, allergyId)
            assertEquals(SafetyStatus.PASS, safety.evaluate(verified, listOf(allergyId)).status, allergyId)
        }
    }
}
