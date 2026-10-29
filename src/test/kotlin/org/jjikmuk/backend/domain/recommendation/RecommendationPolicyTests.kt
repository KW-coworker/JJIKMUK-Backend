package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.product.ProductFilter
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import org.jjikmuk.backend.domain.user.User

class RecommendationPolicyTests {
    private val policy = RecommendationPolicy()

    @Test
    fun `explicit animal ingredients override either vegan flag and unreliable confidence`() {
        for (raw in listOf("젓갈", "멸치액젓", "염장새우", "돼지고기", "계란", "전지분유", "버터", "젤라틴", "벌꿀", "굴 5%")) {
            for (flag in listOf(true, false)) {
                for (origin in ProductDataOrigin.entries) {
                    val product = Product(barcode = "ANIMAL", rawMaterials = "정제수, $raw", vegan = flag,
                        dietaryDataOrigin = origin, dietaryDataConfidence = null)
                    val verdict = policy.evaluateDietaryAttribute(product, ProductFilter.VEGAN)
                    assertEquals(DietaryAttributeStatus.NOT_MET, verdict.status, "$raw / $origin / $flag")
                    assertEquals(DietaryAttributeReason.EXPLICIT_INGREDIENT_CONFLICT, verdict.reason)
                    assertTrue(verdict.ingredientEvidence.isNotEmpty())
                    assertEquals(flag, product.vegan) // Runtime decision does not rewrite source data.
                    assertEquals(DietConstraintStatus.MISMATCH,
                        policy.evaluateDietConstraints(product, setOf(ProductFilter.VEGAN)).status)
                }
            }
        }
    }

    @Test
    fun `real fermented seafood kimchi overrides inferred vegan classification`() {
        val product = Product(barcode = "8809579000297", vegan = true,
            rawMaterials = "L-글루타민산나트륨, 파, 생강, 젓갈, 설탕, 고춧가루, 소금, 마늘, 정제수, 열무, 합성감미료",
            dietaryDataOrigin = ProductDataOrigin.INFERRED, dietaryDataConfidence = 0.7)
        val decision = policy.evaluateDietaryAttribute(product, ProductFilter.VEGAN)
        assertEquals(DietaryAttributeStatus.NOT_MET, decision.status)
        assertEquals(listOf("젓갈"), decision.ingredientEvidence)
        assertTrue(decision.storedValue)
    }

    @Test
    fun `plant ingredient names and shared facility warnings are not explicit vegan conflicts`() {
        for (raw in listOf("코코아버터, 카카오버터", "땅콩버터, 아몬드버터, 캐슈넛버터", "코코넛우유", "둥굴레, 쌀, 분, 유")) {
            val product = Product(barcode = "PLANT", vegan = true, rawMaterials = raw,
                allergyWarning = "우유, 계란과 같은 제조 시설 사용", dietaryDataConfidence = 0.8)
            assertEquals(DietaryAttributeStatus.MET, policy.evaluateDietaryAttribute(product, ProductFilter.VEGAN).status, raw)
        }
        val mixed = Product(barcode = "MIXED-BUTTER", vegan = true, rawMaterials = "코코아버터, 버터, 우유", dietaryDataConfidence = 0.8)
        assertEquals(setOf("버터", "우유"), policy.evaluateDietaryAttribute(mixed, ProductFilter.VEGAN).ingredientEvidence.toSet())
    }

    @Test
    fun `flavor and free from wording cannot establish an explicit conflict or reliable vegan pass`() {
        for (raw in listOf("합성버터향", "젓갈 무첨가", "식물성치즈", "비건버터")) {
            val product = Product(barcode = "AMBIGUOUS", vegan = true, rawMaterials = raw, dietaryDataConfidence = 0.9)
            val decision = policy.evaluateDietaryAttribute(product, ProductFilter.VEGAN)
            assertEquals(DietaryAttributeStatus.UNKNOWN, decision.status, raw)
            assertEquals(DietaryAttributeReason.AMBIGUOUS_INGREDIENT_EVIDENCE, decision.reason)
        }
        val mixed = Product(barcode = "DECLARATION-AND-ANIMAL", vegan = true,
            rawMaterials = "식물성치즈, 젓갈", dietaryDataConfidence = null)
        assertEquals(DietaryAttributeStatus.NOT_MET, policy.evaluateDietaryAttribute(mixed, ProductFilter.VEGAN).status)
    }

    @Test
    fun `vegan contradiction check does not change other diet definitions`() {
        val product = Product(barcode = "LACTO", rawMaterials = "우유", lactoVegetarian = true,
            pescatarian = true, dietaryDataConfidence = 0.8)
        assertEquals(DietaryAttributeStatus.MET, policy.evaluateDietaryAttribute(product, ProductFilter.LACTO_VEGETARIAN).status)
        assertEquals(DietaryAttributeStatus.MET, policy.evaluateDietaryAttribute(product, ProductFilter.PESCATARIAN).status)
    }

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
        val mismatch = Product(barcode = "D-1", vegan = false, rawMaterials = "우유", dietaryDataConfidence = 0.8)
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
            nutritionDataOrigin = ProductDataOrigin.SOURCE,
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

    @Test
    fun `all twelve attributes preserve unknown false and known true separately`() {
        ProductFilter.entries.forEach { filter ->
            val missing = Product(barcode = "MISSING-${filter.key}")
            assertEquals(DietaryAttributeStatus.UNKNOWN, policy.evaluateDietaryAttribute(missing, filter).status)
            val supported = supportedProduct()
            assertEquals(DietaryAttributeStatus.NOT_MET, policy.evaluateDietaryAttribute(supported, filter).status)
            val allTrue = supportedProduct(true)
            assertEquals(DietaryAttributeStatus.MET, policy.evaluateDietaryAttribute(allTrue, filter).status)
        }
    }

    @Test
    fun `unknown attributes are retained even alongside a definite mismatch`() {
        val product = Product(barcode = "MIXED", vegan = false, lowSugar = true,
            rawMaterials = "우유", dietaryDataConfidence = 0.8)
        val decision = policy.evaluateDietConstraints(product, setOf(ProductFilter.VEGAN, ProductFilter.LOW_SUGAR))
        assertEquals(DietConstraintStatus.MISMATCH, decision.status)
        assertEquals(listOf("vegan"), decision.failedFilters)
        assertEquals(listOf("lowSugar"), decision.uncertainFilters)
        assertEquals(2, decision.attributes.size)
    }

    @Test
    fun `confidence is not invented from ingredient presence and both boolean values need evidence`() {
        for (value in listOf(false, true)) {
            val noConfidence = Product(barcode = "NO-CONFIDENCE", vegan = value, rawMaterials = "쌀")
            assertEquals(DietaryAttributeReason.INSUFFICIENT_CONFIDENCE,
                policy.evaluateDietaryAttribute(noConfidence, ProductFilter.VEGAN).reason)
            for (raw in listOf(null, "", "  ", "null", "정보 없음", "N/A", "-")) {
                val noEvidence = Product(barcode = "EMPTY", vegan = value, rawMaterials = raw, dietaryDataConfidence = 0.8)
                assertEquals(DietaryAttributeStatus.UNKNOWN, policy.evaluateDietaryAttribute(noEvidence, ProductFilter.VEGAN).status)
            }
            for (sugar in listOf(null, -1.0, Double.NaN, Double.POSITIVE_INFINITY)) {
                val invalid = Product(barcode = "INVALID", lowSugar = value, sugarG = sugar,
                    nutritionDataOrigin = ProductDataOrigin.SOURCE, dietaryDataConfidence = 0.8)
                assertEquals(DietaryAttributeStatus.UNKNOWN, policy.evaluateDietaryAttribute(invalid, ProductFilter.LOW_SUGAR).status)
            }
        }
    }

    @Test
    fun `imputed or unknown nutrient provenance cannot establish dietary eligibility`() {
        for (origin in listOf(ProductDataOrigin.UNKNOWN, ProductDataOrigin.IMPUTED, ProductDataOrigin.INFERRED)) {
            val product = Product(barcode = "IMPUTED", lowSugar = true, sugarG = 0.0,
                nutritionDataOrigin = origin, dietaryDataConfidence = 0.99)
            assertEquals(DietaryAttributeStatus.UNKNOWN, policy.evaluateDietaryAttribute(product, ProductFilter.LOW_SUGAR).status)
        }
    }

    @Test
    fun `selected diet and disease filters form a single mandatory union`() {
        val user = User(email = "policy@example.com", nickname = "policy", password = "unused",
            specialDiet = "vegan,lowSugar", diseases = "고혈압,당뇨")
        assertEquals(setOf(ProductFilter.VEGAN, ProductFilter.LOW_SUGAR, ProductFilter.LOW_SODIUM), policy.requiredFilters(user))
        assertTrue(policy.evaluateDietConstraints(Product(barcode = "NONE"), emptySet()).attributes.isEmpty())
    }

    private fun supportedProduct(value: Boolean = false) = Product(
        barcode = "SUPPORTED", rawMaterials = "검수된 원재료", dietaryDataConfidence = 0.8,
        nutritionDataOrigin = ProductDataOrigin.SOURCE,
        sugarG = 1.0, sodiumMg = 1.0, energyKcal = 1.0, fatG = 1.0, proteinG = 1.0,
        vegan = value, lactoVegetarian = value, ovoVegetarian = value, lactoOvoVegetarian = value,
        pescatarian = value, pollotarian = value, glutenFree = value,
        lowSugar = value, lowSodium = value, lowCalorie = value, lowFat = value, highProtein = value
    )
}
