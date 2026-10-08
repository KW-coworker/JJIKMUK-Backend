package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.FoodAllergy
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.*
import org.springframework.security.core.Authentication
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.data.domain.PageRequest
import org.springframework.data.domain.Sort

@RestController
@RequestMapping("/api/products")
class ProductController(
    private val productService: ProductService
) {
    @GetMapping("/filters")
    fun getAvailableFilters(): ResponseEntity<*> = ResponseEntity.ok(
        mapOf(
            "message" to "필터 목록 조회 성공",
            "data" to ProductFilter.entries.map { it.toMetadata() }
        )
    )

    @GetMapping("/classifications")
    fun getAvailableClassifications(): ResponseEntity<*> = ResponseEntity.ok(
        mapOf(
            "message" to "상품 분류 목록 조회 성공",
            "data" to mapOf(
                "foodCategories" to ProductFoodCategory.entries.map(ProductFoodCategory::toMetadata),
                "allergens" to FoodAllergy.entries.map { allergy ->
                    mapOf("id" to allergy.id, "label" to allergy.displayName)
                },
                "allergyStates" to AllergyClassificationState.entries.map { state ->
                    mapOf("id" to state.id, "label" to state.displayName)
                }
            )
        )
    )

    @GetMapping("/filter")
    fun filterProducts(
        @RequestParam(required = false) filters: List<String>?,
        @RequestParam(defaultValue = "all") match: String,
        @RequestParam(required = false) categories: List<String>? = null,
        @RequestParam(defaultValue = "any") categoryMatch: String = "any",
        @RequestParam(required = false) containsAllergens: List<String>? = null,
        @RequestParam(defaultValue = "any") allergenMatch: String = "any",
        @RequestParam(required = false) keyword: String?,
        @RequestParam(defaultValue = "0") page: Int,
        @RequestParam(defaultValue = "20") size: Int,
        @RequestParam(required = false) userId: Long?,
        authentication: Authentication?
    ): ResponseEntity<*> {
        val requestedFilters = splitRequestValues(filters)
        val requestedCategories = splitRequestValues(categories)
        val requestedAllergens = splitRequestValues(containsAllergens)

        if (requestedFilters.isEmpty() && requestedCategories.isEmpty() && requestedAllergens.isEmpty()) {
            return ResponseEntity.badRequest().body(
                mapOf(
                    "message" to "식단 필터, 식품 카테고리, 알레르기 분류 중 하나 이상 선택해주세요.",
                    "supportedFilters" to ProductFilter.supportedKeys(),
                    "supportedCategories" to ProductFoodCategory.entries.map(ProductFoodCategory::id),
                    "supportedAllergens" to FoodAllergy.entries.map(FoodAllergy::id)
                )
            )
        }

        val unknownFilters = requestedFilters.filter { ProductFilter.fromRequest(it) == null }
        if (unknownFilters.isNotEmpty()) {
            return ResponseEntity.badRequest().body(
                mapOf(
                    "message" to "지원하지 않는 필터가 있습니다: ${unknownFilters.joinToString()}",
                    "supportedFilters" to ProductFilter.supportedKeys()
                )
            )
        }

        val unknownCategories = requestedCategories.filter { ProductFoodCategory.resolve(it) == null }
        if (unknownCategories.isNotEmpty()) {
            return ResponseEntity.badRequest().body(
                mapOf(
                    "message" to "지원하지 않는 식품 카테고리가 있습니다: ${unknownCategories.joinToString()}",
                    "supportedCategories" to ProductFoodCategory.entries.map(ProductFoodCategory::id)
                )
            )
        }

        val unknownAllergens = requestedAllergens.filter { AllergyCatalog.resolve(it) == null }
        if (unknownAllergens.isNotEmpty()) {
            return ResponseEntity.badRequest().body(
                mapOf(
                    "message" to "지원하지 않는 알레르기 분류가 있습니다: ${unknownAllergens.joinToString()}",
                    "supportedAllergens" to FoodAllergy.entries.map(FoodAllergy::id)
                )
            )
        }

        val matchMode = ProductFilterMatchMode.fromRequest(match)
            ?: return ResponseEntity.badRequest().body(
                mapOf("message" to "match는 all 또는 any만 사용할 수 있습니다.")
            )
        val categoryMatchMode = ProductFilterMatchMode.fromRequest(categoryMatch)
            ?: return ResponseEntity.badRequest().body(
                mapOf("message" to "categoryMatch는 all 또는 any만 사용할 수 있습니다.")
            )
        val allergenMatchMode = ProductFilterMatchMode.fromRequest(allergenMatch)
            ?: return ResponseEntity.badRequest().body(
                mapOf("message" to "allergenMatch는 all 또는 any만 사용할 수 있습니다.")
            )

        if (page < 0 || size !in MIN_PAGE_SIZE..MAX_PAGE_SIZE) {
            return ResponseEntity.badRequest().body(
                mapOf("message" to "page는 0 이상, size는 $MIN_PAGE_SIZE~$MAX_PAGE_SIZE 범위여야 합니다.")
            )
        }

        val normalizedKeyword = keyword?.trim()?.takeIf(String::isNotEmpty)
        if (normalizedKeyword != null && normalizedKeyword.length < MIN_KEYWORD_LENGTH) {
            return ResponseEntity.badRequest().body(
                mapOf("message" to "검색어는 ${MIN_KEYWORD_LENGTH}글자 이상 입력해주세요.")
            )
        }
        if (normalizedKeyword != null && normalizedKeyword.length > MAX_KEYWORD_LENGTH) {
            return ResponseEntity.badRequest().body(
                mapOf("message" to "검색어는 ${MAX_KEYWORD_LENGTH}글자 이하로 입력해주세요.")
            )
        }

        val parsedFilters = requestedFilters.mapNotNull(ProductFilter::fromRequest).toSet()
        val parsedCategories = requestedCategories.mapNotNull(ProductFoodCategory::resolve).toSet()
        val parsedAllergens = requestedAllergens.mapNotNull(AllergyCatalog::resolve).toSet()
        val targetUserId = getValidatedUserId(userId, authentication)
        val pageable = PageRequest.of(
            page,
            size,
            Sort.by(Sort.Order.asc("productName"), Sort.Order.asc("barcode"))
        )
        val result = productService.filterProductsAnalysis(
            filters = parsedFilters,
            matchMode = matchMode,
            categories = parsedCategories,
            categoryMatchMode = categoryMatchMode,
            allergens = parsedAllergens,
            allergenMatchMode = allergenMatchMode,
            keyword = normalizedKeyword,
            pageable = pageable,
            userId = targetUserId
        )

        val responseData = mapOf(
            "items" to result.content,
            "page" to result.number,
            "size" to result.size,
            "totalElements" to result.totalElements,
            "totalPages" to result.totalPages,
            "hasNext" to result.hasNext(),
            "appliedFilters" to parsedFilters.map { it.key },
            "appliedCategories" to parsedCategories.map { it.id },
            "containedAllergens" to parsedAllergens.map { it.id },
            "match" to matchMode.responseValue,
            "categoryMatch" to categoryMatchMode.responseValue,
            "allergenMatch" to allergenMatchMode.responseValue,
            "keyword" to normalizedKeyword
        )

        return ResponseEntity.ok(
            mapOf(
                "message" to if (result.isEmpty) "조건에 맞는 제품을 찾을 수 없습니다." else "필터 검색 성공",
                "data" to responseData
            )
        )
    }

    // 🚀 보안과 편의성을 모두 잡은 마법의 검증 함수!
    private fun getValidatedUserId(requestedUserId: Long?, authentication: Authentication?): Long? {
        // 비로그인 사용자 처리
        if (authentication == null || authentication.principal == "anonymousUser") {
            if (requestedUserId != null) {
                throw CustomException(HttpStatus.UNAUTHORIZED, "특정 사용자의 기준으로 조회하려면 로그인이 필요합니다.")
            }
            return null // 비로그인이면 그냥 범용 데이터 반환
        }

        val currentUserId = authentication.principal.toString().toLong()
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }

        // 프론트에서 userId를 안 보냈다면 내 ID로 자동 셋팅, 보냈다면 그 ID 사용
        val targetId = requestedUserId ?: currentUserId

        // 핵심 방어 로직: "요청한 ID가 내 ID도 아니고, 내가 관리자도 아니라면?" -> 차단!
        if (targetId != currentUserId && !isAdmin) {
            throw CustomException(HttpStatus.FORBIDDEN, "다른 사용자의 기준으로 검색할 수 없습니다.")
        }

        return targetId
    }

    @GetMapping("/{barcode}")
    fun getProductByBarcode(
        @PathVariable barcode: String,
        @RequestParam(required = false) userId: Long?, // 다시 부활!
        authentication: Authentication?
    ): ResponseEntity<*> {

        // 🚀 검증 함수 통과 (실패 시 여기서 에러 터지고 끝남)
        val targetUserId = getValidatedUserId(userId, authentication)

        val responseData = productService.getProductAnalysis(barcode, targetUserId)
            ?: return ResponseEntity.status(404).body(mapOf("message" to "해당 바코드(${barcode})의 제품을 찾을 수 없습니다."))

        return ResponseEntity.ok(mapOf("message" to "조회 성공", "data" to responseData))
    }

    @GetMapping("/search")
    fun searchProducts(
        @RequestParam keyword: String,
        @RequestParam(required = false) userId: Long?, // 다시 부활!
        authentication: Authentication?
    ): ResponseEntity<*> {
        if (keyword.trim().length < 2) {
            return ResponseEntity.badRequest().body(mapOf("message" to "검색어는 2글자 이상 입력해주세요."))
        }
        if (keyword.trim().length > MAX_KEYWORD_LENGTH) {
            return ResponseEntity.badRequest().body(
                mapOf("message" to "검색어는 ${MAX_KEYWORD_LENGTH}글자 이하로 입력해주세요.")
            )
        }

        // 🚀 검증 함수 통과
        val targetUserId = getValidatedUserId(userId, authentication)

        val responseData = productService.searchProductsAnalysis(keyword, targetUserId)

        if (responseData.isEmpty()) {
            return ResponseEntity.ok(
                mapOf(
                    "message" to "'$keyword'에 해당하는 제품을 찾을 수 없습니다.",
                    "data" to emptyList<Any>()
                )
            )
        }

        return ResponseEntity.ok(mapOf("message" to "검색 성공", "data" to responseData))
    }

    private companion object {
        const val MIN_PAGE_SIZE = 1
        const val MAX_PAGE_SIZE = 50
        const val MIN_KEYWORD_LENGTH = 2
        const val MAX_KEYWORD_LENGTH = 100
    }

    private fun splitRequestValues(values: List<String>?): List<String> = values.orEmpty()
        .flatMap { value -> value.split(",") }
        .map(String::trim)
        .filter(String::isNotEmpty)
}
