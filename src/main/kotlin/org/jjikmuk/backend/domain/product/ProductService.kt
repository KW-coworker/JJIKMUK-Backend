package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.AllergySafetyService
import org.jjikmuk.backend.domain.allergy.FoodAllergy
import org.jjikmuk.backend.domain.recommendation.SafetyStatus
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.jjikmuk.backend.domain.history.History
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.history.UserActionType
import org.springframework.data.domain.Page
import org.springframework.data.domain.Pageable
import org.springframework.context.ApplicationEventPublisher
import org.jjikmuk.backend.domain.product.search.ProductSearchPerformedEvent

@Service // 💡 스프링에게 이 클래스가 비즈니스 로직을 담당하는 Service임을 알려줍니다.
@Transactional(readOnly = true) // 💡 데이터 조회만 하므로 성능 최적화를 위해 붙여줍니다.
class ProductService(
    private val productRepository: ProductRepository,
    private val distinctProductSearchRepository: DistinctProductSearchRepository,
    private val userRepository: UserRepository,
    private val historyRepository: HistoryRepository,
    private val eventPublisher: ApplicationEventPublisher,
    private val allergySafetyService: AllergySafetyService
) {
    @Transactional
    // 1. 단건 조회 비즈니스 로직
    fun getProductAnalysis(barcode: String, userId: Long?): Map<String, Any>? {
        val product = productRepository.findFirstByBarcode(barcode)
            ?: throw CustomException(HttpStatus.NOT_FOUND, "해당 바코드(${barcode})의 제품을 찾을 수 없습니다.")
        val user = userId?.let { userRepository.findById(it).orElse(null) }
        // 💡 3. 유저가 로그인 상태(userId 존재)라면 스캔 히스토리를 저장합니다!
        if (user != null) {
            val history = History(
                user = user,
                barcode = barcode,
                actionType = UserActionType.SCAN
            )
            historyRepository.save(history)
        }
        return analyzeProductAllergy(product, user)
    }

    // 2. 다건 검색 비즈니스 로직
    fun searchProductsAnalysis(keyword: String, userId: Long?): List<Map<String, Any>> {
        val startedAt = System.nanoTime()
        val products = distinctProductSearchRepository.searchByProductName(
            keyword = keyword,
            limit = MAX_SEARCH_RESULTS
        )
        publishSearchEvent(
            endpoint = "SEARCH",
            keyword = keyword,
            filters = emptySet(),
            matchMode = null,
            userId = userId,
            resultCount = products.size.toLong(),
            startedAt = startedAt
        )
        if (products.isEmpty()) return emptyList()

        val user = userId?.let { userRepository.findById(it).orElse(null) }

        return products.map { product -> analyzeProductAllergy(product, user) }
    }

    fun filterProductsAnalysis(
        filters: Set<ProductFilter>,
        matchMode: ProductFilterMatchMode,
        categories: Set<ProductFoodCategory>,
        categoryMatchMode: ProductFilterMatchMode,
        allergens: Set<FoodAllergy>,
        allergenMatchMode: ProductFilterMatchMode,
        keyword: String?,
        pageable: Pageable,
        userId: Long?
    ): Page<Map<String, Any>> {
        val user = userId?.let { userRepository.findById(it).orElse(null) }
        val startedAt = System.nanoTime()
        val products = distinctProductSearchRepository.searchByFilters(
            filters = filters,
            matchMode = matchMode,
            categories = categories,
            categoryMatchMode = categoryMatchMode,
            allergens = allergens,
            allergenMatchMode = allergenMatchMode,
            keyword = keyword,
            pageable = pageable
        )
        publishSearchEvent(
            endpoint = "FILTER",
            keyword = keyword,
            filters = buildSet {
                addAll(filters.map(ProductFilter::key))
                addAll(categories.map { "category:${it.id}" })
                addAll(allergens.map { "containsAllergen:${it.id}" })
            },
            matchMode = matchMode.responseValue,
            userId = userId,
            resultCount = products.totalElements,
            startedAt = startedAt
        )
        return products
            .map { product -> analyzeProductAllergy(product, user) }
    }

    private fun publishSearchEvent(
        endpoint: String,
        keyword: String?,
        filters: Set<String>,
        matchMode: String?,
        userId: Long?,
        resultCount: Long,
        startedAt: Long
    ) {
        eventPublisher.publishEvent(
            ProductSearchPerformedEvent.create(
                userId = userId,
                endpoint = endpoint,
                query = keyword,
                filters = filters,
                matchMode = matchMode,
                searchMode = distinctProductSearchRepository.activeSearchMode(),
                resultCount = resultCount,
                latencyNanos = System.nanoTime() - startedAt
            )
        )
    }

    private fun analyzeProductAllergy(product: Product, user: User?): Map<String, Any> {
        val safety = allergySafetyService.evaluate(
            product = product,
            allergies = user?.allergies?.let { AllergyCatalog.parse(it) }
                ?.let { profile -> profile.ids.map { it.id } + profile.unknownTerms }
                .orEmpty(),
            profileKnown = user != null
        )
        val dangerousIngredients = safety.conflictingAllergens.mapNotNull { id ->
            AllergyCatalog.resolve(id)?.displayName
        }

        // 💡 1일 영양성분 기준치 대비 퍼센트 계산 (식약처 고시 2,000kcal 기준)
        val nutrientPercents = mapOf(
            "energyPercent" to (product.energyKcal?.let { Math.round((it / 2000.0) * 100) } ?: 0),
            "carbsPercent" to (product.carbsG?.let { Math.round((it / 324.0) * 100) } ?: 0),
            "proteinPercent" to (product.proteinG?.let { Math.round((it / 55.0) * 100) } ?: 0),
            "fatPercent" to (product.fatG?.let { Math.round((it / 54.0) * 100) } ?: 0),
            "sugarPercent" to (product.sugarG?.let { Math.round((it / 100.0) * 100) } ?: 0),
            "sodiumPercent" to (product.sodiumMg?.let { Math.round((it / 2000.0) * 100) } ?: 0),
            "cholesterolPercent" to (product.cholesterolMg?.let { Math.round((it / 300.0) * 100) } ?: 0),
            // 🚀 프론트엔드 탄단지 원그래프용 (전체 칼로리 중 해당 영양소의 퍼센트)
            "carbsMacroPercent" to (product.carbsPercent ?: 0.0),
            "proteinMacroPercent" to (product.proteinPercent ?: 0.0),
            "fatMacroPercent" to (product.fatPercent ?: 0.0)
        )

        return mapOf(
            "product" to product,
            "nutrientPercents" to nutrientPercents, // 🚀 프론트엔드 원그래프용 데이터 추가!
            "analysis" to mapOf(
                "status" to safety.status.name,
                "isDangerous" to (safety.status == SafetyStatus.DANGER),
                "dangerousIngredients" to dangerousIngredients,
                "conflictingAllergenIds" to safety.conflictingAllergens,
                "evidenceSources" to safety.evidenceSources,
                "evidenceLevel" to safety.evidenceLevel.name,
                "verificationRequired" to (safety.status == SafetyStatus.UNKNOWN),
                "message" to safety.message
            )
        )
    }

    private companion object {
        const val MAX_SEARCH_RESULTS = 50
    }
}
