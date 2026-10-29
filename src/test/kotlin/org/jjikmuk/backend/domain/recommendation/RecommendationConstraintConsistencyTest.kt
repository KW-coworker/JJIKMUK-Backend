package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.*
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.test.context.ActiveProfiles
import org.springframework.transaction.annotation.Transactional
import kotlin.test.*

@ActiveProfiles("test")
@SpringBootTest
@Transactional
class RecommendationConstraintConsistencyTest @Autowired constructor(
    private val home: SafeProductRecommendationService,
    private val alternatives: RecommendationService,
    private val products: ProductRepository,
    private val neighbors: ProductNeighborSetRepository,
    private val users: UserRepository
) {
    @Test
    fun `soy synonyms and false positive vegan flags are excluded by both APIs and fallback`() {
        val rejected = listOf(candidate("BLACK-SOY", raw = "검정콩분말"),
            candidate("FERMENTED-FISH", raw = "열무, 젓갈", confidence = null))
        val user = setup(rejected, allergies = "soy")
        val h = home.recommend(user.id!!, 10, null, 42, emptySet(), setOf(ProductFoodCategory.SPECIAL))
        val a = alternatives.recommendAlternatives("CONSISTENCY-REFERENCE", user.id!!, 10, 0.0)
        assertTrue(h.returnedBarcodes.isEmpty())
        assertTrue(a.items.isEmpty())
        assertTrue(a.fallbackItems.isEmpty())
        assertEquals(RecommendationResultMode.ACTION_REQUIRED, a.resultMode)
        assertEquals(1, h.exclusions.danger)
        assertEquals(1, a.excluded.danger)
        assertEquals(1, h.exclusions.dietMismatch)
        assertEquals(1, a.excluded.dietMismatch)
    }

    @Test
    fun `both APIs enforce the same allergy diet health and disliked ingredient constraints`() {
        val candidates = listOf(
            candidate("PASS"), candidate("VEGAN-FAIL", vegan = false),
            candidate("SUGAR-FAIL", lowSugar = false), candidate("SODIUM-FAIL", lowSodium = false),
            candidate("UNKNOWN", confidence = null), candidate("DANGER", raw = "쌀, 우유"),
            candidate("DISLIKE", raw = "쌀, 고수")
        )
        val user = setup(candidates)
        val h = home.recommend(user.id!!, 50, null, 42, emptySet(), setOf(ProductFoodCategory.SPECIAL))
        val a = alternatives.recommendAlternatives("CONSISTENCY-REFERENCE", user.id!!, 20, 0.0)
        assertEquals(listOf("CONSISTENCY-PASS"), h.returnedBarcodes)
        assertEquals(h.returnedBarcodes, a.items.map { it.product.barcode })
        assertEquals(a.userContext.requiredDietFilters, h.requiredDietFilterIds)
        assertEquals(listOf("lowSodium", "lowSugar", "vegan"), h.requiredDietFilterIds)
        assertEquals(3, h.exclusions.dietMismatch)
        assertEquals(3, a.excluded.dietMismatch)
        assertEquals(1, h.exclusions.dietUnknown)
        assertEquals(1, a.excluded.dietUnknown)
        assertEquals(1, h.exclusions.danger)
        assertEquals(1, a.excluded.danger)
        assertEquals(1, h.exclusions.dislikedIngredient)
        assertEquals(1, a.excluded.dislikedIngredient)
        assertEquals(h.policyVersion, a.policyVersion)
    }

    @Test
    fun `all unknown candidates never become verified even when stored flags are false`() {
        val user = setup(listOf(candidate("UNKNOWN", vegan = false, confidence = null)))
        val h = home.recommend(user.id!!, 10, null, 42, emptySet(), setOf(ProductFoodCategory.SPECIAL))
        val a = alternatives.recommendAlternatives("CONSISTENCY-REFERENCE", user.id!!, 10, 0.0)
        assertEquals(SafeRecommendationMode.EMPTY, h.recommendationMode)
        assertTrue(h.returnedBarcodes.isEmpty())
        assertTrue(a.items.isEmpty())
        assertEquals(RecommendationResultMode.VERIFICATION_REQUIRED, a.resultMode)
        assertEquals(DietConstraintStatus.UNKNOWN, a.fallbackItems.single().dietConstraints.status)
        assertTrue(a.fallbackItems.single().verificationRequired)
        assertTrue(a.fallbackItems.single().warnings.isNotEmpty())
        assertTrue(a.fallbackItems.single().requiredActions.isNotEmpty())
    }

    @Test
    fun `only definite mismatch or danger produces correct empty responses in both APIs`() {
        val user = setup(listOf(candidate("FAIL", vegan = false), candidate("DANGER", raw = "우유")))
        val h = home.recommend(user.id!!, 10, null, 42, emptySet(), setOf(ProductFoodCategory.SPECIAL))
        val a = alternatives.recommendAlternatives("CONSISTENCY-REFERENCE", user.id!!, 10, 0.0)
        assertTrue(h.returnedBarcodes.isEmpty())
        assertTrue(a.items.isEmpty())
        assertTrue(a.fallbackItems.isEmpty())
        assertEquals(RecommendationResultMode.ACTION_REQUIRED, a.resultMode)
        assertTrue(a.requiredActions.isNotEmpty())
    }

    private fun setup(candidates: List<Product>, allergies: String = "milk"): User {
        products.saveAll(candidates + Product(barcode = "CONSISTENCY-REFERENCE"))
        neighbors.save(ProductNeighborSet(sourceBarcode = "CONSISTENCY-REFERENCE", modelVersion = "test",
            recommendationCount = candidates.size, recommendations = candidates.joinToString(",") { "${it.barcode}|0.9" }))
        return users.save(User(email = "consistency@example.com", nickname = "consistency", password = "unused",
            allergies = allergies, specialDiet = "vegan,lowSugar", diseases = "고혈압", dislikedIngredients = "고수"))
    }

    private fun candidate(id: String, vegan: Boolean = true, lowSugar: Boolean = true,
        lowSodium: Boolean = true, confidence: Double? = 0.8, raw: String = "쌀, 소금") = Product(
        barcode = "CONSISTENCY-$id", productName = id, productGroupKey = "consistency-$id",
        rawMaterials = raw, allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL,
        foodCategories = ProductFoodCategory.SPECIAL.displayName,
        vegan = vegan, lowSugar = lowSugar, lowSodium = lowSodium, sugarG = 1.0, sodiumMg = 5.0,
        nutritionDataOrigin = ProductDataOrigin.SOURCE, dietaryDataConfidence = confidence
    )
}
