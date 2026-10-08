package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.product.ProductFoodCategory
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.test.context.ActiveProfiles
import org.springframework.transaction.annotation.Transactional

@ActiveProfiles("test")
@SpringBootTest
@Transactional
class SafeProductRecommendationServiceTest @Autowired constructor(
    private val service: SafeProductRecommendationService,
    private val controller: SafeProductRecommendationController,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository
) {
    @Test
    fun `home recommendations keep safety constraints and relax preferences only when needed`() {
        val category = ProductFoodCategory.SPECIAL.displayName
        val delivered = safeProduct("SAFE-HOME-000", "이미 노출된 상품", category, vegan = true, group = "group-delivered")
        val duplicate = safeProduct("SAFE-HOME-001", "이미 노출된 상품", category, vegan = true, group = "group-delivered")
        val strict = safeProduct("SAFE-HOME-002", "비건 안심 상품", category, vegan = true, group = "group-strict")
        val relaxed = safeProduct("SAFE-HOME-003", "일반 안심 상품", category, vegan = false, group = "group-relaxed")
        val danger = safeProduct(
            "SAFE-HOME-004",
            "우유 위험 상품",
            category,
            vegan = true,
            group = "group-danger",
            rawMaterials = "우유, 설탕"
        )
        val unknown = Product(
            barcode = "SAFE-HOME-005",
            productName = "근거 부족 상품",
            rawMaterials = "쌀, 소금",
            foodCategories = category,
            vegan = true,
            productGroupKey = "group-unknown",
            allergyEvidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED,
            dietaryDataOrigin = ProductDataOrigin.INFERRED,
            dietaryDataConfidence = 0.8
        )
        val disliked = safeProduct(
            "SAFE-HOME-006",
            "땅콩 기피 상품",
            category,
            vegan = true,
            group = "group-disliked",
            rawMaterials = "땅콩, 쌀"
        )
        productRepository.saveAll(listOf(delivered, duplicate, strict, relaxed, danger, unknown, disliked))
        val user = userRepository.save(
            User(
                email = "safe-home@example.com",
                nickname = "안심 홈 추천 테스트",
                allergies = "milk",
                specialDiet = "비건",
                dislikedIngredients = "땅콩",
                password = "test-password"
            )
        )

        val result = service.recommend(
            userId = requireNotNull(user.id),
            limit = 10,
            cursor = null,
            seed = 42L,
            excludedBarcodes = setOf(delivered.barcode),
            requestedCategories = setOf(ProductFoodCategory.SPECIAL)
        )

        assertEquals(SafeRecommendationMode.MIXED, result.recommendationMode)
        assertEquals(listOf(strict.barcode, relaxed.barcode), result.returnedBarcodes)
        assertTrue(result.categories.single().items.all { it.safety.status == SafetyStatus.PASS })
        assertFalse(result.returnedBarcodes.contains(duplicate.barcode))
        assertFalse(result.returnedBarcodes.contains(danger.barcode))
        assertFalse(result.returnedBarcodes.contains(unknown.barcode))
        assertFalse(result.returnedBarcodes.contains(disliked.barcode))
        assertFalse(result.categories.single().items.first().preferenceRelaxed)
        assertTrue(result.categories.single().items.last().preferenceRelaxed)
        assertTrue(result.exclusions.danger >= 1)
        assertTrue(result.exclusions.unknownSafety >= 1)
        assertTrue(result.exclusions.dislikedIngredient >= 1)
        assertTrue(result.exclusions.alreadyDeliveredOrDuplicate >= 2)

        val authentication = UsernamePasswordAuthenticationToken(user.id.toString(), null, emptyList())
        val response = controller.getSafeRecommendations(
            limit = 2,
            cursor = null,
            seed = 42L,
            excludeBarcodes = listOf(delivered.barcode),
            categories = listOf(ProductFoodCategory.SPECIAL.id),
            userId = null,
            authentication = authentication
        )
        assertEquals(200, response.statusCode.value())
    }

    @Test
    fun `cursor continuation does not return the same barcode again`() {
        val category = ProductFoodCategory.SEAFOOD.displayName
        val products = (1..6).map { index ->
            safeProduct(
                barcode = "SAFE-CURSOR-00$index",
                name = "커서 안심 상품 $index",
                category = category,
                vegan = true,
                group = "cursor-group-$index"
            )
        }
        productRepository.saveAll(products)
        val user = userRepository.save(
            User(
                email = "safe-cursor@example.com",
                nickname = "커서 테스트",
                password = "test-password"
            )
        )

        val first = service.recommend(
            userId = requireNotNull(user.id),
            limit = 1,
            cursor = null,
            seed = 7L,
            excludedBarcodes = emptySet(),
            requestedCategories = setOf(ProductFoodCategory.SEAFOOD)
        )
        assertEquals(1, first.returnedItemCount)
        assertNotNull(first.nextCursor)

        val second = service.recommend(
            userId = requireNotNull(user.id),
            limit = 1,
            cursor = first.nextCursor,
            seed = first.seed,
            excludedBarcodes = first.returnedBarcodes.toSet(),
            requestedCategories = setOf(ProductFoodCategory.SEAFOOD)
        )
        assertEquals(1, second.returnedItemCount)
        assertTrue(first.returnedBarcodes.toSet().intersect(second.returnedBarcodes.toSet()).isEmpty())
    }

    private fun safeProduct(
        barcode: String,
        name: String,
        category: String,
        vegan: Boolean,
        group: String,
        rawMaterials: String = "쌀, 대두, 소금"
    ) = Product(
        barcode = barcode,
        productName = name,
        manufacturer = "안심 제조사",
        rawMaterials = rawMaterials,
        allergyWarning = "대두 함유",
        foodCategories = category,
        vegan = vegan,
        productGroupKey = group,
        allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL,
        dietaryDataOrigin = ProductDataOrigin.INFERRED,
        dietaryDataConfidence = 0.8
    )
}
