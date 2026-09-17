package org.jjikmuk.backend

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductController
import org.jjikmuk.backend.domain.product.ProductGroupKeyBuilder
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.product.DistinctProductSearchRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.test.context.ActiveProfiles
import org.springframework.jdbc.core.JdbcTemplate

@ActiveProfiles("test")
@SpringBootTest
class BackendApplicationTests @Autowired constructor(
    private val productController: ProductController,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository,
    private val jdbcTemplate: JdbcTemplate
) {
    @Test
    fun contextLoads() {
    }

    @Test
    fun `product scan api looks up a Product csv shaped product`() {
        val barcode = "8801234567890"
        productRepository.save(
            Product(
                barcode = barcode,
                reportNo = "REPORT-1",
                productName = "Test Snack",
                manufacturer = "Test Maker",
                vegan = true,
                lowSugar = true
            )
        )

        val response = productController.getProductByBarcode(barcode, null, null)

        assertEquals(200, response.statusCode.value())
        val body = response.body as Map<*, *>
        val data = body["data"] as Map<*, *>
        val product = data["product"] as Product
        assertEquals(barcode, product.barcode)
        assertEquals("Test Snack", product.productName)
        assertEquals(true, product.vegan)
        assertEquals(true, product.lowSugar)
    }

    @Test
    fun `product lookup keeps optional user allergy analysis`() {
        val barcode = "8801234567891"
        val user = userRepository.save(
            User(
                email = "allergy-test@example.com",
                nickname = "allergy-test",
                allergies = "Milk",
                password = "test-password"
            )
        )
        productRepository.save(
            Product(
                barcode = barcode,
                reportNo = "REPORT-2",
                productName = "Milk Snack",
                manufacturer = "Test Maker",
                allergy = "Milk"
            )
        )

        val authentication = UsernamePasswordAuthenticationToken(
            user.id.toString(),
            null,
            emptyList()
        )
        val response = productController.getProductByBarcode(barcode, user.id, authentication)

        assertEquals(200, response.statusCode.value())
        val body = response.body as Map<*, *>
        val data = body["data"] as Map<*, *>
        val analysis = data["analysis"] as Map<*, *>
        assertEquals(true, analysis["isDangerous"])
    }

    @Test
    fun `filter api supports all and any matching with Korean aliases`() {
        productRepository.saveAll(
            listOf(
                Product(
                    barcode = "FILTER-0001",
                    productName = "필터대상 비건 글루텐프리",
                    vegan = true,
                    glutenFree = true
                ),
                Product(
                    barcode = "FILTER-0002",
                    productName = "필터대상 비건",
                    vegan = true
                ),
                Product(
                    barcode = "FILTER-0003",
                    productName = "필터대상 글루텐프리",
                    glutenFree = true
                )
            )
        )

        val allResponse = productController.filterProducts(
            filters = listOf("비건,gluten-free"),
            match = "all",
            keyword = "필터대상",
            page = 0,
            size = 20,
            userId = null,
            authentication = null
        )
        assertEquals(200, allResponse.statusCode.value())
        val allBody = allResponse.body as Map<*, *>
        val allData = allBody["data"] as Map<*, *>
        val allItems = allData["items"] as List<*>
        assertEquals(1, allItems.size)
        assertEquals(1L, allData["totalElements"])
        val allProduct = (allItems.first() as Map<*, *>)["product"] as Product
        assertEquals("FILTER-0001", allProduct.barcode)

        val anyResponse = productController.filterProducts(
            filters = listOf("vegan", "글루텐프리"),
            match = "any",
            keyword = "필터대상",
            page = 0,
            size = 2,
            userId = null,
            authentication = null
        )
        assertEquals(200, anyResponse.statusCode.value())
        val anyData = (anyResponse.body as Map<*, *>)["data"] as Map<*, *>
        assertEquals(3L, anyData["totalElements"])
        assertEquals(2, (anyData["items"] as List<*>).size)
        assertEquals(true, anyData["hasNext"])
        assertEquals("any", anyData["match"])
    }

    @Test
    fun `filter api exposes metadata and rejects unknown filters`() {
        val metadataResponse = productController.getAvailableFilters()
        val metadata = (metadataResponse.body as Map<*, *>)["data"] as List<*>
        assertEquals(12, metadata.size)

        val response = productController.filterProducts(
            filters = listOf("unknown-filter"),
            match = "all",
            keyword = null,
            page = 0,
            size = 20,
            userId = null,
            authentication = null
        )
        assertEquals(400, response.statusCode.value())
    }

    @Test
    fun `all product search APIs collapse cards with identical displayed information`() {
        productRepository.saveAll(
            listOf(
                Product(
                    barcode = "DEDUP-0001",
                    productName = "중복상품 포키",
                    manufacturer = "동일 제조사",
                    allergy = "밀, 우유",
                    imageUrl = null,
                    rawMaterials = "밀, 우유",
                    energyKcal = 100.0,
                    vegan = true
                ),
                Product(
                    barcode = "DEDUP-0002",
                    productName = " 중복상품 포키 ",
                    manufacturer = "동일 제조사",
                    allergy = "다른 알레르기 원본",
                    imageUrl = "",
                    rawMaterials = " 밀,우유 ",
                    energyKcal = 250.0,
                    vegan = true
                ),
                Product(
                    barcode = "DEDUP-0003",
                    productName = "중복상품 포키",
                    manufacturer = "동일 제조사",
                    allergy = "밀, 우유",
                    imageUrl = null,
                    rawMaterials = "우유",
                    energyKcal = 180.0,
                    vegan = true
                )
            )
        )

        val keywordResponse = productController.searchProducts(
            keyword = "중복상품",
            userId = null,
            authentication = null
        )
        assertEquals(200, keywordResponse.statusCode.value())
        val keywordItems = (keywordResponse.body as Map<*, *>)["data"] as List<*>
        assertEquals(2, keywordItems.size)

        val filterResponse = productController.filterProducts(
            filters = listOf("vegan"),
            match = "all",
            keyword = "중복상품",
            page = 0,
            size = 20,
            userId = null,
            authentication = null
        )
        assertEquals(200, filterResponse.statusCode.value())
        val filterData = (filterResponse.body as Map<*, *>)["data"] as Map<*, *>
        assertEquals(2L, filterData["totalElements"])
        assertEquals(2, (filterData["items"] as List<*>).size)
    }

    @Test
    fun `product group key mode uses the deterministic display identity`() {
        val firstKey = ProductGroupKeyBuilder.build(
            productName = "그룹키테스트 포키",
            manufacturer = "동일 제조사",
            rawMaterials = "밀, 우유",
            imageUrl = null
        )
        val sameKey = ProductGroupKeyBuilder.build(
            productName = " 그룹키테스트 포키 ",
            manufacturer = "동일   제조사",
            rawMaterials = "밀,우유",
            imageUrl = ""
        )
        val differentKey = ProductGroupKeyBuilder.build(
            productName = "그룹키테스트 포키",
            manufacturer = "동일 제조사",
            rawMaterials = "우유",
            imageUrl = null
        )
        productRepository.saveAll(
            listOf(
                Product(
                    barcode = "GROUP-KEY-0001",
                    productName = "그룹키테스트 포키",
                    manufacturer = "동일 제조사",
                    rawMaterials = "밀, 우유",
                    productGroupKey = firstKey
                ),
                Product(
                    barcode = "GROUP-KEY-0002",
                    productName = " 그룹키테스트 포키 ",
                    manufacturer = "동일 제조사",
                    rawMaterials = "밀,우유",
                    productGroupKey = sameKey
                ),
                Product(
                    barcode = "GROUP-KEY-0003",
                    productName = "그룹키테스트 포키",
                    manufacturer = "동일 제조사",
                    rawMaterials = "우유",
                    productGroupKey = differentKey
                )
            )
        )

        val keyRepository = DistinctProductSearchRepository(
            jdbcTemplate = jdbcTemplate,
            productRepository = productRepository,
            configuredSearchMode = "locate",
            configuredGroupingMode = "key"
        )

        assertEquals(2, keyRepository.searchByProductName("그룹키테스트", 10).size)
    }

    @Test
    fun `locate fallback treats spaced and compact product queries equally`() {
        productRepository.saveAll(
            listOf(
                Product(
                    barcode = "SPACE-SEARCH-1",
                    productName = "두유 바",
                    cleanProductName = "두유 바",
                    manufacturer = "테스트 식품"
                ),
                Product(
                    barcode = "SPACE-SEARCH-2",
                    productName = "진한 두유 바 초콜릿",
                    cleanProductName = "진한 두유 바 초콜릿",
                    manufacturer = "다른 제조사"
                )
            )
        )

        val compactResults = productController.searchProducts("두유바", null, null)
        val spacedResults = productController.searchProducts("두유 바", null, null)
        val compactBarcodes = ((compactResults.body as Map<*, *>)["data"] as List<*>)
            .map { ((it as Map<*, *>)["product"] as Product).barcode }
        val spacedBarcodes = ((spacedResults.body as Map<*, *>)["data"] as List<*>)
            .map { ((it as Map<*, *>)["product"] as Product).barcode }

        assertEquals(compactBarcodes, spacedBarcodes)
        assertEquals("SPACE-SEARCH-1", compactBarcodes.first())
    }
}
