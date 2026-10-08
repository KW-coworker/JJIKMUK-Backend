package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.history.History
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.history.UserActionType
import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.test.context.ActiveProfiles

@ActiveProfiles("test")
@SpringBootTest
class RecommendationServiceTests @Autowired constructor(
    private val recommendationService: RecommendationService,
    private val recommendationController: RecommendationController,
    private val productRepository: ProductRepository,
    private val neighborRepository: ProductNeighborSetRepository,
    private val userRepository: UserRepository,
    private val historyRepository: HistoryRepository
) {
    @Test
    fun `recommendation applies allergy unknown diet dislike history and diversity stages`() {
        val reference = Product(
            barcode = "8800000100000",
            productName = "우유가 들어간 기준 과자",
            manufacturer = "기준 제조사",
            rawMaterials = "밀, 우유",
            vegan = false,
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val danger = Product(
            barcode = "8800000100001",
            productName = "우유 쿠키",
            manufacturer = "위험 제조사",
            rawMaterials = "밀, 우유",
            vegan = true,
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val unknown = Product(
            barcode = "8800000100002",
            productName = "정보 없는 과자",
            manufacturer = "미상 제조사",
            vegan = true
        )
        val dietMismatch = Product(
            barcode = "8800000100003",
            productName = "육류 스낵",
            manufacturer = "육류 제조사",
            rawMaterials = "돼지고기, 정제소금",
            vegan = false,
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val dietUnknown = Product(
            barcode = "8800000100007",
            productName = "식단 근거 없는 스낵",
            manufacturer = "미상 제조사",
            allergyWarning = "밀 함유",
            rawMaterials = "쌀, 정제소금",
            vegan = true,
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL,
            dietaryDataOrigin = ProductDataOrigin.UNKNOWN
        )
        val disliked = Product(
            barcode = "8800000100004",
            productName = "땅콩 과자",
            manufacturer = "땅콩 제조사",
            rawMaterials = "땅콩, 쌀",
            vegan = true,
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val safeTofu = Product(
            barcode = "8800000100005",
            productName = "두부 스낵",
            cleanProductName = "두부스낵",
            manufacturer = "안전 제조사 A",
            rawMaterials = "대두, 쌀, 소금",
            proteinG = 10.0,
            vegan = true,
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val preferredOat = Product(
            barcode = "8800000100006",
            productName = "오트 스낵",
            cleanProductName = "오트스낵",
            manufacturer = "안전 제조사 B",
            rawMaterials = "귀리, 쌀, 소금",
            proteinG = 8.0,
            vegan = true,
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        productRepository.saveAll(
            listOf(reference, danger, unknown, dietMismatch, dietUnknown, disliked, safeTofu, preferredOat)
        )

        val user = userRepository.save(
            User(
                email = "recommendation-test@example.com",
                nickname = "추천 테스트",
                allergies = "milk",
                specialDiet = "비건",
                dislikedIngredients = "땅콩",
                password = "test-password"
            )
        )
        historyRepository.save(
            History(
                user = user,
                barcode = preferredOat.barcode,
                actionType = UserActionType.EAT
            )
        )
        neighborRepository.save(
            ProductNeighborSet(
                sourceBarcode = reference.barcode,
                modelVersion = "test-model-v1",
                recommendationCount = 7,
                recommendations = listOf(
                    "${danger.barcode}|0.99",
                    "${unknown.barcode}|0.98",
                    "${dietMismatch.barcode}|0.97",
                    "${dietUnknown.barcode}|0.96",
                    "${disliked.barcode}|0.95",
                    "${safeTofu.barcode}|0.90",
                    "${preferredOat.barcode}|0.85"
                ).joinToString(",")
            )
        )

        val result = recommendationService.recommendAlternatives(
            referenceBarcode = reference.barcode,
            userId = requireNotNull(user.id),
            limit = 2,
            minSimilarityScore = 0.0
        )

        assertEquals(SafetyStatus.DANGER, result.referenceSafety.status)
        assertEquals(listOf("milk"), result.userContext.allergies)
        assertEquals(listOf("vegan"), result.userContext.requiredDietFilters)
        assertEquals(1, result.excluded.danger)
        assertEquals(1, result.excluded.unknownSafety)
        assertEquals(1, result.excluded.dietMismatch)
        assertEquals(1, result.excluded.dietUnknown)
        assertEquals(1, result.excluded.dislikedIngredient)
        assertEquals(2, result.items.size)
        assertEquals(RecommendationResultMode.VERIFIED, result.resultMode)
        assertTrue(result.fallbackItems.isEmpty())
        assertEquals(preferredOat.barcode, result.items.first().product.barcode)
        assertTrue(result.items.all { it.safety.status == SafetyStatus.PASS })
        assertTrue(result.items.all { it.dietConstraints.status == DietConstraintStatus.PASS })
        assertTrue(result.items.all { !it.verificationRequired })
        assertTrue(result.items.all { it.scoreBreakdown.similarityContribution > 0.0 })
        assertTrue(result.timing.totalMicros >= result.timing.rankingMicros)
        assertTrue(result.items.first().preferenceScore!! > result.items.last().preferenceScore!!)

        val authentication = UsernamePasswordAuthenticationToken(user.id.toString(), null, emptyList())
        val apiResponse = recommendationController.recommendAlternatives(
            barcode = reference.barcode,
            userId = null,
            limit = 2,
            minScore = 0.0,
            authentication = authentication
        )
        assertEquals(200, apiResponse.statusCode.value())
        val apiData = (apiResponse.body as Map<*, *>)["data"] as ProductRecommendationResponse
        assertEquals(preferredOat.barcode, apiData.items.first().product.barcode)
    }

    @Test
    fun `returns highest original rank unknown candidate as verification-required fallback`() {
        val reference = Product(
            barcode = "8800000200000",
            productName = "기준 스낵",
            rawMaterials = "밀, 우유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val danger = Product(
            barcode = "8800000200001",
            productName = "우유 위험 스낵",
            rawMaterials = "쌀, 우유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val firstUnknown = Product(
            barcode = "8800000200002",
            productName = "첫 번째 확인 필요 스낵",
            manufacturer = "동일 제조사",
            rawMaterials = "쌀, 소금",
            allergyEvidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED
        )
        val secondUnknown = Product(
            barcode = "8800000200003",
            productName = "두 번째 확인 필요 스낵",
            manufacturer = "동일 제조사",
            rawMaterials = "옥수수, 소금",
            allergyEvidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED
        )
        productRepository.saveAll(listOf(reference, danger, firstUnknown, secondUnknown))
        val user = userRepository.save(
            User(
                email = "recommendation-fallback@example.com",
                nickname = "fallback 테스트",
                allergies = "우유",
                password = "test-password"
            )
        )
        neighborRepository.save(
            ProductNeighborSet(
                sourceBarcode = reference.barcode,
                modelVersion = "test-model-fallback",
                recommendationCount = 3,
                recommendations = listOf(
                    "${danger.barcode}|0.99",
                    "${firstUnknown.barcode}|0.90",
                    "${secondUnknown.barcode}|0.90"
                ).joinToString(",")
            )
        )

        val result = recommendationService.recommendAlternatives(
            referenceBarcode = reference.barcode,
            userId = requireNotNull(user.id),
            limit = 10,
            minSimilarityScore = 0.2
        )

        assertTrue(result.items.isEmpty())
        assertEquals(RecommendationResultMode.VERIFICATION_REQUIRED, result.resultMode)
        assertEquals(RecommendationFallbackReason.INSUFFICIENT_VERIFICATION_DATA, result.fallbackReason)
        assertEquals(2, result.fallbackCandidateCount)
        assertEquals(1, result.fallbackItems.size)
        assertEquals(firstUnknown.barcode, result.fallbackItems.single().product.barcode)
        assertEquals(2, result.fallbackItems.single().originalRank)
        assertEquals(SafetyStatus.UNKNOWN, result.fallbackItems.single().safety.status)
        assertEquals(DietConstraintStatus.PASS, result.fallbackItems.single().dietConstraints.status)
        assertTrue(result.fallbackItems.single().verificationRequired)
        assertTrue(result.fallbackItems.single().warnings.isNotEmpty())
        assertTrue(result.fallbackItems.single().requiredActions.isNotEmpty())
        assertEquals(1, result.excluded.danger)

        val authentication = UsernamePasswordAuthenticationToken(user.id.toString(), null, emptyList())
        val apiResponse = recommendationController.recommendAlternatives(
            barcode = reference.barcode,
            userId = null,
            limit = 10,
            minScore = 0.2,
            authentication = authentication
        )
        val body = apiResponse.body as Map<*, *>
        assertEquals(
            "안전성을 확정할 수 없어 제품 라벨 확인이 필요한 대안을 표시합니다.",
            body["message"]
        )
    }

    @Test
    fun `prefers safe candidate below similarity threshold over unknown candidate`() {
        val reference = Product(barcode = "8800000300000", productName = "기준 상품")
        val highSimilarityUnknown = Product(
            barcode = "8800000300001",
            productName = "고유사도 확인 필요 상품",
            rawMaterials = "쌀, 소금",
            allergyEvidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED
        )
        val lowSimilaritySafe = Product(
            barcode = "8800000300002",
            productName = "저유사도 안전 상품",
            rawMaterials = "옥수수, 소금",
            allergyWarning = "대두 함유",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        productRepository.saveAll(listOf(reference, highSimilarityUnknown, lowSimilaritySafe))
        val user = userRepository.save(
            User(
                email = "recommendation-relaxed@example.com",
                nickname = "relaxed 테스트",
                allergies = "우유",
                password = "test-password"
            )
        )
        neighborRepository.save(
            ProductNeighborSet(
                sourceBarcode = reference.barcode,
                modelVersion = "test-model-relaxed",
                recommendationCount = 2,
                recommendations = listOf(
                    "${highSimilarityUnknown.barcode}|0.90",
                    "${lowSimilaritySafe.barcode}|0.19"
                ).joinToString(",")
            )
        )

        val result = recommendationService.recommendAlternatives(
            referenceBarcode = reference.barcode,
            userId = requireNotNull(user.id),
            limit = 10,
            minSimilarityScore = 0.2
        )

        assertEquals(RecommendationResultMode.RELAXED_SAFE, result.resultMode)
        assertTrue(result.items.isEmpty())
        assertEquals(lowSimilaritySafe.barcode, result.fallbackItems.single().product.barcode)
        assertEquals(SafetyStatus.PASS, result.fallbackItems.single().safety.status)
        assertEquals(DietConstraintStatus.PASS, result.fallbackItems.single().dietConstraints.status)
        assertTrue(!result.fallbackItems.single().verificationRequired)
        assertEquals(RecommendationFallbackReason.MINIMUM_SIMILARITY_RELAXED, result.fallbackReason)
    }

    @Test
    fun `never returns danger or diet mismatch just to avoid an empty product result`() {
        val reference = Product(barcode = "8800000400000", productName = "기준 상품")
        val danger = Product(
            barcode = "8800000400001",
            productName = "우유 함유 상품",
            rawMaterials = "우유, 설탕",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
        )
        val dietMismatch = Product(
            barcode = "8800000400002",
            productName = "식단 불일치 상품",
            rawMaterials = "쌀, 소금",
            vegan = false,
            allergyEvidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED
        )
        productRepository.saveAll(listOf(reference, danger, dietMismatch))
        val user = userRepository.save(
            User(
                email = "recommendation-danger-only@example.com",
                nickname = "danger-only 테스트",
                allergies = "우유",
                specialDiet = "비건",
                password = "test-password"
            )
        )
        neighborRepository.save(
            ProductNeighborSet(
                sourceBarcode = reference.barcode,
                modelVersion = "test-model-danger-only",
                recommendationCount = 2,
                recommendations = listOf(
                    "${danger.barcode}|0.99",
                    "${dietMismatch.barcode}|0.98"
                ).joinToString(",")
            )
        )

        val result = recommendationService.recommendAlternatives(
            referenceBarcode = reference.barcode,
            userId = requireNotNull(user.id),
            limit = 10,
            minSimilarityScore = 0.0
        )

        assertEquals(RecommendationResultMode.ACTION_REQUIRED, result.resultMode)
        assertTrue(result.items.isEmpty())
        assertTrue(result.fallbackItems.isEmpty())
        assertEquals(RecommendationFallbackReason.NO_RETURNABLE_CANDIDATE, result.fallbackReason)
        assertTrue(result.requiredActions.isNotEmpty())
        assertEquals(1, result.excluded.danger)
        assertEquals(1, result.excluded.dietMismatch)

        val authentication = UsernamePasswordAuthenticationToken(user.id.toString(), null, emptyList())
        val apiResponse = recommendationController.recommendAlternatives(
            barcode = reference.barcode,
            userId = null,
            limit = 10,
            minScore = 0.0,
            authentication = authentication
        )
        val body = apiResponse.body as Map<*, *>
        assertEquals(
            "위험 상품을 대신 표시하지 않았습니다. 제품 라벨 확인 또는 다른 상품 선택이 필요합니다.",
            body["message"]
        )
    }
}
