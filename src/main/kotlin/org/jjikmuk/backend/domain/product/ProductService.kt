package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.AllergySafetyService
import org.jjikmuk.backend.domain.allergy.FoodAllergy
import org.jjikmuk.backend.domain.recommendation.SafetyStatus
import org.jjikmuk.backend.domain.recommendation.SafetyDecision
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.domain.user.EffectiveAnalysis
import org.jjikmuk.backend.domain.user.notEvaluatedSafety
import org.jjikmuk.backend.domain.user.withoutAnalysis
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
    private val allergySafetyService: AllergySafetyService,
    private val recommendationPolicy: org.jjikmuk.backend.domain.recommendation.RecommendationPolicy
) {
    fun barcodeForProductId(productId: Long): String = productRepository.findByProductId(productId)?.barcode
        ?: throw CustomException(HttpStatus.NOT_FOUND, "현재 데이터셋에서 해당 상품 ID를 찾을 수 없습니다.")

    @Transactional
    fun getProductAnalysisById(productId: Long, userId: Long?, analysis: EffectiveAnalysis? = null): Map<String, Any> {
        val product = productRepository.findByProductId(productId)
            ?: throw CustomException(HttpStatus.NOT_FOUND, "현재 데이터셋에서 해당 상품 ID를 찾을 수 없습니다.")
        return analyzeAndRecord(product, userId, analysis)
    }

    @Transactional
    // 1. 단건 조회 비즈니스 로직
    fun getProductAnalysis(barcode: String, userId: Long?, analysis: EffectiveAnalysis? = null): Map<String, Any>? {
        val product = productRepository.findFirstByBarcode(barcode)
            ?: throw CustomException(HttpStatus.NOT_FOUND, "해당 바코드(${barcode})의 제품을 찾을 수 없습니다.")
        return analyzeAndRecord(product, userId, analysis)
    }

    private fun analyzeAndRecord(product: Product, userId: Long?, analysis: EffectiveAnalysis?): Map<String, Any> {
        val user = userId?.let { userRepository.findById(it).orElse(null) }
        // 💡 3. 유저가 로그인 상태(userId 존재)라면 스캔 히스토리를 저장합니다!
        // Family/general browsing must not become the account holder's personal taste signal.
        if (user != null && analysis?.personalHistoryAllowed != false) {
            val history = History(
                user = user,
                barcode = product.barcode,
                actionType = UserActionType.SCAN,
                productId = product.productId,
                attributeSnapshotId = product.attributeSnapshotId
            )
            historyRepository.save(history)
        }
        return analyzeProductAllergy(product, user, analysis = analysis)
    }

    // 2. 다건 검색 비즈니스 로직
    fun searchProductsAnalysis(keyword: String, userId: Long?, analysis: EffectiveAnalysis? = null): List<Map<String, Any>> {
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

        return products.map { product -> analyzeProductAllergy(product, user, analysis = analysis) }
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
        userId: Long?,
        analysis: EffectiveAnalysis? = null
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
            .map { product -> analyzeProductAllergy(product, user, analysis = analysis) }
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

    /** Read-only projection, also used by capacity options without generating SCAN history. */
    internal fun analyzeProductAllergy(
        product: Product,
        user: User?,
        safetyOverride: SafetyDecision? = null,
        analysis: EffectiveAnalysis? = null,
        dietOverride: org.jjikmuk.backend.domain.recommendation.DietConstraintDecision? = null
    ): Map<String, Any> {
        val decision = evaluateProductConditions(product, user, safetyOverride, analysis, dietOverride)

        return mapOf(
            "product" to product,
            "nutrientPercents" to nutrientPercents(product),
            "analysis" to decision
        )
    }

    /** Shared by product/variant projections and chat. No SCAN write or external request. */
    internal fun evaluateProductConditions(
        product: Product,
        user: User?,
        safetyOverride: SafetyDecision? = null,
        analysis: EffectiveAnalysis? = null,
        dietOverride: org.jjikmuk.backend.domain.recommendation.DietConstraintDecision? = null
    ): Map<String, Any> {
        val effective = analysis?.profile ?: user
        val safety = if (analysis?.applied == false) notEvaluatedSafety() else safetyOverride ?: allergySafetyService.evaluate(
            product = product,
            allergies = effective?.allergies?.let { AllergyCatalog.parse(it) }
                ?.let { profile -> profile.ids.map { it.id } + profile.unknownTerms }
                .orEmpty(),
            profileKnown = effective != null
        )
        val dangerousIngredients = safety.conflictingAllergens.mapNotNull { id ->
            AllergyCatalog.resolve(id)?.displayName
        }
        val diet = dietOverride ?: recommendationPolicy.evaluateDietConstraints(product,
            effective?.let(recommendationPolicy::requiredFilters).orEmpty())

        return mapOf(
            "status" to safety.status.name,
            "dietConstraints" to if (analysis?.applied == false || effective == null) diet.withoutAnalysis() else diet,
            "analysisApplied" to (analysis?.applied ?: (user != null)),
            "selection" to (analysis?.selection ?: org.jjikmuk.backend.domain.user.AnalysisSelectionResponse(
                if (user == null) "none" else "self", user != null, user != null, emptyList())),
            "isDangerous" to (safety.status == SafetyStatus.DANGER),
            "dangerousIngredients" to dangerousIngredients,
            "conflictingAllergenIds" to safety.conflictingAllergens,
            "evidenceSources" to safety.evidenceSources,
            "evidenceLevel" to safety.evidenceLevel.name,
            "verificationRequired" to (safety.status == SafetyStatus.UNKNOWN),
            "message" to safety.message
        )
    }

    private fun nutrientPercents(product: Product): Map<String, Number> {
        // 💡 1일 영양성분 기준치 대비 퍼센트 계산 (식약처 고시 2,000kcal 기준)
        return mapOf(
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

    }

    private companion object {
        const val MAX_SEARCH_RESULTS = 50
    }
}
