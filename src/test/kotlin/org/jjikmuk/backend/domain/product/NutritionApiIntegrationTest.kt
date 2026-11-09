package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.auth.*
import org.jjikmuk.backend.domain.chat.AiChatClient
import org.jjikmuk.backend.domain.chat.dto.*
import org.jjikmuk.backend.domain.user.*
import org.jjikmuk.backend.global.config.*
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.ArgumentMatchers.anyLong
import org.mockito.ArgumentMatchers.eq
import org.mockito.Mockito.doAnswer
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.web.context.WebApplicationContext
import kotlin.test.*

@SpringBootTest(properties = ["spring.datasource.url=jdbc:h2:mem:nutrition-api;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@ActiveProfiles("test")
class NutritionApiIntegrationTest @Autowired constructor(private val context: WebApplicationContext,
    private val products: ProductRepository, private val users: UserRepository,
    private val auth: AuthService, private val encoder: BCryptPasswordEncoder,
    private val importer: ProductDataImportService, private val jdbc: org.springframework.jdbc.core.JdbcTemplate) {
    @MockitoBean lateinit var ai: AiChatClient

    @Test fun `JDBC staging binder preserves source basis without replacing scalar calories`() {
        val columnsField = ProductDataImportService::class.java.getDeclaredField("DATABASE_COLUMNS").apply { isAccessible = true }
        @Suppress("UNCHECKED_CAST") val columns = columnsField.get(null) as List<String>
        jdbc.execute("CREATE TABLE products_staging AS SELECT * FROM products WHERE 1=0")
        try {
            jdbc.execute("ALTER TABLE products_staging ADD COLUMN search_keywords TEXT")
            val bind = ProductDataImportService::class.java.getDeclaredMethod("bindProduct", java.sql.PreparedStatement::class.java, Product::class.java).apply { isAccessible = true }
            jdbc.execute(org.springframework.jdbc.core.ConnectionCallback<Unit> { connection ->
                connection.prepareStatement("INSERT INTO products_staging (${columns.joinToString()}) VALUES (${columns.joinToString { "?" }})").use { statement ->
                    bind.invoke(importer, statement, Product("staging-pocky", totalWeight = "44g", energyKcal = 500.0, nutritionBasisRaw = "100g"))
                    assertEquals(1, statement.executeUpdate())
                }
            })
            val row = jdbc.queryForMap("SELECT energy_kcal, nutrition_basis_raw FROM products_staging WHERE barcode='staging-pocky'")
            assertEquals(500.0, row["energy_kcal"])
            assertEquals("100g", row["nutrition_basis_raw"])
        } finally { jdbc.execute("DROP TABLE products_staging") }
    }

    @Test fun `CSV to database to detail variants search and AI retains nutrition basis`() {
        val values = arrayOfNulls<String>(ProductCsvColumn.entries.size)
        mapOf(ProductCsvColumn.PRODUCT_NAME to "포키 녹차", ProductCsvColumn.CLEAN_PRODUCT_NAME to "포키 녹차",
            ProductCsvColumn.MANUFACTURER to "해태제과식품(주)", ProductCsvColumn.TOTAL_WEIGHT to "44g",
            ProductCsvColumn.ENERGY_KCAL to "500", ProductCsvColumn.NUTRITION_BASIS_RAW to "100g")
            .forEach { (key, value) -> values[key.ordinal] = value }
        products.saveAndFlush(ProductCsvRecord(values, values.size).toProduct("8801019311673"))
        assertEquals("100g", products.findById("8801019311673").orElseThrow().nutritionBasisRaw)
        val mvc = MockMvcBuilders.webAppContextSetup(context).build()
        for ((url, prefix) in listOf("/api/products/8801019311673" to "$.data.product",
            "/api/products/search?keyword=포키" to "$.data[0].product",
            "/api/products/8801019311673/variants" to "$.data.options[0].data.product")) {
            mvc.perform(get(url)).andExpect(status().isOk)
                .andExpect(jsonPath("$prefix.energyKcal").value(500.0))
                .andExpect(jsonPath("$prefix.nutrition.sourceBasis.amount").value(100))
                .andExpect(jsonPath("$prefix.nutrition.per100g.values.energyKcal").value(500.0))
                .andExpect(jsonPath("$prefix.nutrition.perPackage.values.energyKcal").value(220.0))
        }
        users.saveAndFlush(User(email = "nutrition@example.invalid", nickname = "영양테스트", password = encoder.encode("Example123!")!!))
        val token = auth.login(LoginRequest("nutrition@example.invalid", "Example123!")).token
        var sent: AiChatRequestDto? = null
        val placeholder = AiChatRequestDto(null, emptyList(), null, "", emptyList(), ChatAnalysisContext(
            "test", policyVersion = "test", selection = AnalysisSelectionResponse("none", false, false, emptyList()),
            effectiveConditions = null, productResolution = "NOT_PROVIDED", analysis = null, dataEvidence = null))
        doAnswer { call -> sent = call.getArgument(0); "{\"answer\":\"전체 44g 기준 220kcal\"}" }
            .`when`(ai).ask(any<AiChatRequestDto>() ?: placeholder, anyLong(), eq(true))
        val secured = MockMvcBuilders.webAppContextSetup(context)
            .addFilters<org.springframework.test.web.servlet.setup.DefaultMockMvcBuilder>(context.getBean("springSecurityFilterChain", jakarta.servlet.Filter::class.java)).build()
        secured.perform(post("/api/chat").header("Authorization", "Bearer $token").contentType(MediaType.APPLICATION_JSON)
            .content("""{"message":"전체 열량?","barcode":"8801019311673","externalAiConsent":true}"""))
            .andExpect(status().isOk)
        assertEquals(220.0, sent!!.product!!.nutrition!!.perPackage!!.values.energyKcal)
        assertEquals(500.0, sent!!.product!!.energyKcal)
    }
}
