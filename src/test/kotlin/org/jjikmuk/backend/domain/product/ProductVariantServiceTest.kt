package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.status
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.transaction.annotation.Transactional
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.assertFailsWith

@ActiveProfiles("test")
@SpringBootTest
@Transactional
class ProductVariantServiceTest @Autowired constructor(
    private val service: ProductVariantService,
    private val controller: ProductController,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository,
    private val historyRepository: HistoryRepository,
    private val jdbcTemplate: JdbcTemplate,
    private val searchRepository: DistinctProductSearchRepository
) {
    @Test
    fun `capacity alone creates options and duplicate detail fields do not`() {
        save(
            product("CAP-01", "1kg"),
            product("CAP-02", "1000.0 g", energy = 400.0),
            product("CAP-03", "500g"),
            product("CAP-04", "1L"),
            product("CAP-05", null),
            product("CAP-06", "알수없음"),
            product("CAP-07", "1kg", name = "다른 상품"),
            product("CAP-08", "2kg", manufacturer = "다른 제조사"),
            product("CAP-09", "3kg", materials = "다른 원재료"),
            product("CAP-10", "4kg", image = "https://example.test/other.jpg")
        )
        val result = service.getVariants("CAP-01", null)
        assertEquals(listOf("g:500", "g:1000", "ml:1000", "unknown"), result.options.map { it.key })
        assertEquals(4, result.optionCount)
        assertTrue(result.hasSelectableOptions)
        assertEquals("g:1000", result.selectedOptionKey)
        val mass = result.options[1]
        assertEquals(2, mass.sourceRowCount)
        assertEquals("CAP-02", mass.barcode)
        assertEquals(400.0, (mass.data["product"] as Product).energyKcal)
        assertEquals(2, result.options.last().sourceRowCount)
        assertTrue(result.options.all { analysis(it)["status"] == "UNKNOWN" })
        assertTrue(result.options.all { it.analysisScope == "CAPACITY_GROUP" })
    }

    @Test
    fun `one equal capacity is one option irrespective of warnings and nutritional differences`() {
        save(product("SINGLE-01", "50g", name = "단일 용량"), product("SINGLE-02", "0.05kg", name = "단일 용량", energy = 10.0))
        val response = service.getVariants("SINGLE-01", null)
        assertEquals(1, response.optionCount)
        assertFalse(response.hasSelectableOptions)
        assertEquals("50g", response.options.single().label)
        assertEquals(2, response.options.single().sourceRowCount)
    }

    @Test
    fun `danger in a hidden duplicate is retained without generating scan history`() {
        val user = userRepository.save(User(email = "variant-danger@example.test", nickname = "용량위험테스트", password = "test", allergies = "milk"))
        save(
            product("RISK-01", "100g", name = "용량위험", energy = 200.0),
            product("RISK-02", "0.1kg", name = "용량위험", warning = "우유 함유"),
            product("RISK-03", "200g", name = "용량위험")
        )
        val before = historyRepository.count()
        val auth = UsernamePasswordAuthenticationToken(user.id.toString(), null, emptyList())
        val response = controller.getCapacityVariants("RISK-01", null, auth)
        val result = (response.body as Map<*, *>)["data"] as ProductVariantResponse
        val first = result.options.first()
        assertEquals("RISK-01", first.barcode) // Completeness is not a way to hide DANGER.
        assertEquals("DANGER", analysis(first)["status"])
        assertEquals(listOf("milk"), analysis(first)["conflictingAllergenIds"])
        assertTrue(first.hasSafetyDifferences)
        assertEquals("PASS", analysis(result.options[1])["status"])
        service.getVariants("RISK-01", user.id)
        assertEquals(before, historyRepository.count())
    }

    @Test
    fun `unknown is not overridden by a pass record with the same capacity`() {
        val user = userRepository.save(User(email = "variant-unknown@example.test", nickname = "용량불명테스트", password = "test", allergies = "milk"))
        save(
            product("UNKNOWN-01", "100g", name = "용량불명"),
            product("UNKNOWN-02", "100g", name = "용량불명", evidence = AllergyEvidenceLevel.UNKNOWN)
        )
        val option = service.getVariants("UNKNOWN-01", user.id).options.single()
        assertEquals("UNKNOWN", analysis(option)["status"])
        assertTrue(option.hasSafetyDifferences)
        assertEquals(true, analysis(option)["verificationRequired"])
    }

    @Test
    fun `all matching pass records may return pass without multiplying options`() {
        val user = userRepository.save(User(email = "variant-pass@example.test", nickname = "용량표기테스트", password = "test", allergies = "milk"))
        save(product("PASS-01", "100g", name = "용량표기"), product("PASS-02", "0.1kg", name = "용량표기"))
        val option = service.getVariants("PASS-01", user.id).options.single()
        assertEquals("PASS", analysis(option)["status"])
        assertFalse(option.hasSafetyDifferences)
    }

    @Test
    fun `existing user ownership rules apply to variant endpoint`() {
        val anonymousError = assertFailsWith<CustomException> {
            controller.getCapacityVariants("ANY", 10L, null)
        }
        assertEquals(401, anonymousError.status.value())
        val authentication = UsernamePasswordAuthenticationToken("10", null, emptyList())
        val otherUserError = assertFailsWith<CustomException> {
            controller.getCapacityVariants("ANY", 11L, authentication)
        }
        assertEquals(403, otherUserError.status.value())
    }

    @Test
    fun `missing product is 404 and an unnamed product never joins unrelated records`() {
        assertEquals(404, assertFailsWith<CustomException> { service.getVariants("MISSING-VARIANT", null) }.status.value())
        save(product("BLANK-01", "100g", name = ""), product("BLANK-02", "200g", name = ""))
        assertEquals(1, service.getVariants("BLANK-01", null).optionCount)
    }

    @Test
    fun `key mode matches search grouping and does not combine missing group keys`() {
        val first = product("KEY-01", "50g", name = "키 모드")
        val second = product("KEY-02", "100g", name = "키 모드")
        save(first, second, product("KEY-03", "200g", name = "다른 키"))
        val keyRepository = DistinctProductSearchRepository(jdbcTemplate, productRepository, "locate", "key")
        assertEquals(listOf("KEY-01", "KEY-02"), keyRepository.findDisplayGroupMembers(first, 100).map { it.barcode })
        val noKey = Product(barcode = "KEY-NULL-01", productName = "미백필", manufacturer = "제조사")
        save(noKey, Product(barcode = "KEY-NULL-02", productName = "미백필", manufacturer = "제조사"))
        assertEquals(listOf(noKey.barcode), keyRepository.findDisplayGroupMembers(noKey, 100).map { it.barcode })
    }

    @Test
    fun `legacy membership follows the same normalization as search`() {
        val first = product("LEGACY-01", "50g", name = "legacy product")
        save(first, product("LEGACY-02", "100g", name = " LEGACY PRODUCT ", materials = "쌀,소금"))
        assertEquals(listOf("LEGACY-01", "LEGACY-02"), searchRepository.findDisplayGroupMembers(first, 100).map { it.barcode })
    }

    @Test
    fun `oversized groups fail explicitly instead of hiding potentially unsafe rows`() {
        productRepository.saveAllAndFlush((1..1001).map { product("LARGE-${it.toString().padStart(4, '0')}", "100g", name = "대량 동일상품") })
        val error = assertFailsWith<CustomException> { service.getVariants("LARGE-0001", null) }
        assertEquals(422, error.status.value())
        assertEquals("PRODUCT_VARIANT_GROUP_TOO_LARGE", error.code)
    }

    @Test
    fun `http response exposes capacity options and the existing product analysis structure`() {
        save(product("HTTP-01", "50g", name = "HTTP용량"), product("HTTP-02", "100g", name = "HTTP용량"))
        MockMvcBuilders.standaloneSetup(controller).build()
            .perform(get("/api/products/HTTP-01/variants"))
            .andExpect(status().isOk)
            .andExpect(jsonPath("$.data.optionCount").value(2))
            .andExpect(jsonPath("$.data.selectedOptionKey").value("g:50"))
            .andExpect(jsonPath("$.data.options[0].amount").value(50))
            .andExpect(jsonPath("$.data.options[0].data.product.barcode").value("HTTP-01"))
            .andExpect(jsonPath("$.data.options[0].data.analysis.status").value("UNKNOWN"))
            .andExpect(jsonPath("$.data.options[0].data.nutrientPercents").exists())
            .andExpect(jsonPath("$.data.options[0].data.product.productGroupKey").doesNotExist())
    }

    private fun analysis(option: ProductCapacityOption) = option.data["analysis"] as Map<*, *>

    private fun save(vararg products: Product) { productRepository.saveAllAndFlush(products.toList()) }

    private fun product(
        barcode: String,
        weight: String?,
        name: String = "용량테스트 상품",
        manufacturer: String = "용량테스트 제조사",
        materials: String = "쌀, 소금",
        image: String? = null,
        warning: String? = "대두 함유",
        energy: Double? = null,
        evidence: AllergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL
    ) = Product(
        barcode = barcode, productName = name, manufacturer = manufacturer,
        rawMaterials = materials, imageUrl = image, totalWeight = weight,
        allergyWarning = warning, energyKcal = energy, allergyEvidenceLevel = evidence,
        productGroupKey = ProductGroupKeyBuilder.build(name, manufacturer, materials, image)
    )
}
