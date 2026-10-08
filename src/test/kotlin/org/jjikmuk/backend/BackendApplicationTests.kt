package org.jjikmuk.backend

import org.jjikmuk.backend.domain.auth.AuthService
import org.jjikmuk.backend.domain.auth.EmailVerificationGrant
import org.jjikmuk.backend.domain.auth.EmailVerificationGrantRepository
import org.jjikmuk.backend.domain.auth.EmailVerificationPurpose
import org.jjikmuk.backend.domain.auth.EmailVerificationSecurity
import org.jjikmuk.backend.domain.auth.LoginRequest
import org.jjikmuk.backend.domain.auth.PasswordResetRequest
import org.jjikmuk.backend.domain.auth.SignupRequest
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.ProductController
import org.jjikmuk.backend.domain.product.ProductGroupKeyBuilder
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.product.DistinctProductSearchRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.domain.user.UserService
import org.jjikmuk.backend.domain.user.UserProfileRequest
import org.jjikmuk.backend.domain.user.UserController
import org.jjikmuk.backend.domain.user.UserProfileResponse
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
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
    private val jdbcTemplate: JdbcTemplate,
    private val authService: AuthService,
    private val userService: UserService,
    private val emailVerificationGrantRepository: EmailVerificationGrantRepository,
    private val userController: UserController
) {
    @Test
    fun contextLoads() {
    }

    @Test
    fun `signup stores canonical allergy diet and vegetarian IDs and profile can clear them`() {
        val verificationToken = "signup-verification-token"
        val signupRequest = SignupRequest(
            email = "allergy-contract-signup@example.com",
            password = "test-password1",
            nickname = "계약테스트",
            allergies = "계란, 밀",
            diseases = null,
            specialDiet = "저당, highProtein, 락토오보",
            dislikedIngredients = null,
            verificationToken = verificationToken
        )
        emailVerificationGrantRepository.save(
            EmailVerificationGrant(
                email = "allergy-contract-signup@example.com",
                purpose = EmailVerificationPurpose.SIGNUP,
                tokenHash = EmailVerificationSecurity.hashToken(verificationToken),
                expiredAt = java.time.LocalDateTime.now().plusMinutes(30),
                createdAt = java.time.LocalDateTime.now()
            )
        )
        val user = authService.signup(signupRequest)
        assertEquals("egg,wheat", user.allergies)
        assertEquals("lactoOvoVegetarian,lowSugar,highProtein", user.specialDiet)
        assertEquals(null, user.diseases)
        assertEquals(null, user.dislikedIngredients)

        val login = authService.login(LoginRequest(user.email, "test-password1"))
        assertEquals(user.id, login.userId)
        assertEquals(user.email, login.email)
        assertEquals(false, login.isNewUser)
        assertEquals(true, login.profileCompleted)
        assertEquals(86_400L, login.expiresInSeconds)
        assertEquals(false, authService.nicknameAvailability(user.nickname).available)

        val authentication = UsernamePasswordAuthenticationToken(requireNotNull(user.id), null, emptyList())
        val profileResponse = userController.getMyProfile(authentication)
        val profile = (profileResponse.body as Map<*, *>)["data"] as UserProfileResponse
        assertEquals(user.id, profile.id)
        assertEquals(user.email, profile.email)

        val duplicateError = assertThrows(CustomException::class.java) {
            authService.signup(signupRequest)
        }
        assertEquals(409, duplicateError.status.value())
        assertEquals(ApiErrorCode.EMAIL_ALREADY_REGISTERED, duplicateError.code)
        kotlin.test.assertTrue(duplicateError.message.contains("로그인"))

        val duplicateNicknameEmail = "duplicate-nickname@example.com"
        val duplicateNicknameToken = "duplicate-nickname-token"
        emailVerificationGrantRepository.save(
            EmailVerificationGrant(
                email = duplicateNicknameEmail,
                purpose = EmailVerificationPurpose.SIGNUP,
                tokenHash = EmailVerificationSecurity.hashToken(duplicateNicknameToken),
                expiredAt = java.time.LocalDateTime.now().plusMinutes(30),
                createdAt = java.time.LocalDateTime.now()
            )
        )
        val nicknameError = assertThrows(CustomException::class.java) {
            authService.signup(
                signupRequest.copy(
                    email = duplicateNicknameEmail,
                    verificationToken = duplicateNicknameToken
                )
            )
        }
        assertEquals(ApiErrorCode.NICKNAME_ALREADY_EXISTS, nicknameError.code)

        val updated = userService.updateUserProfile(
            requireNotNull(user.id),
            UserProfileRequest(
                nickname = user.nickname,
                allergies = "egg, 견과류",
                diseases = null,
                specialDiet = null,
                dislikedIngredients = null
            )
        )
        assertEquals("egg,walnut,pine_nut,almond", updated?.allergies)
        assertEquals(null, updated?.specialDiet)
        assertThrows(CustomException::class.java) {
            userService.updateUserProfile(
                requireNotNull(user.id),
                UserProfileRequest(
                    nickname = user.nickname,
                    allergies = "unsupported-allergen",
                    diseases = null,
                    specialDiet = null,
                    dislikedIngredients = null
                )
            )
        }

        val conflictingDietError = assertThrows(CustomException::class.java) {
            userService.updateUserProfile(
                requireNotNull(user.id),
                UserProfileRequest(
                    nickname = user.nickname,
                    allergies = null,
                    diseases = null,
                    specialDiet = "vegan,pescatarian,lowSugar",
                    dislikedIngredients = null
                )
            )
        }
        assertEquals(400, conflictingDietError.status.value())

        val cleared = userService.updateUserProfile(
            requireNotNull(user.id),
            UserProfileRequest(
                nickname = user.nickname,
                allergies = null,
                diseases = null,
                specialDiet = null,
                dislikedIngredients = null
            )
        )
        assertEquals(null, cleared?.allergies)
        assertEquals(null, cleared?.diseases)
        assertEquals(null, cleared?.specialDiet)
        assertEquals(null, cleared?.dislikedIngredients)
    }

    @Test
    fun `failed signup keeps an unexpired verification grant for retry`() {
        val email = "retryable-signup@example.com"
        val verificationToken = "retryable-signup-token"
        emailVerificationGrantRepository.save(
            EmailVerificationGrant(
                email = email,
                purpose = EmailVerificationPurpose.SIGNUP,
                tokenHash = EmailVerificationSecurity.hashToken(verificationToken),
                expiredAt = java.time.LocalDateTime.now().plusMinutes(30),
                createdAt = java.time.LocalDateTime.now()
            )
        )

        assertThrows(CustomException::class.java) {
            authService.signup(
                SignupRequest(
                    email = email,
                    password = "test-password1",
                    nickname = "재시도사용자",
                    allergies = "unsupported-allergen",
                    diseases = null,
                    verificationToken = verificationToken
                )
            )
        }

        val preserved = emailVerificationGrantRepository.findAll()
            .firstOrNull { it.email == email && it.purpose == EmailVerificationPurpose.SIGNUP }
        kotlin.test.assertNotNull(preserved)
        kotlin.test.assertTrue(
            EmailVerificationSecurity.tokenMatches(verificationToken, preserved.tokenHash)
        )
    }

    @Test
    fun `password reset consumes a purpose scoped one time verification token`() {
        val email = "password-reset-contract@example.com"
        val verificationToken = "password-reset-verification-token"
        userRepository.save(
            User(
                email = email,
                password = org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder()
                    .encode("old-password")!!,
                nickname = "비밀번호 재설정 테스트"
            )
        )
        emailVerificationGrantRepository.save(
            EmailVerificationGrant(
                email = email,
                purpose = EmailVerificationPurpose.PASSWORD_RESET,
                tokenHash = EmailVerificationSecurity.hashToken(verificationToken),
                expiredAt = java.time.LocalDateTime.now().plusMinutes(5),
                createdAt = java.time.LocalDateTime.now()
            )
        )

        authService.resetPassword(
            PasswordResetRequest(
                email = email,
                verificationToken = verificationToken,
                newPassword = "new-password1"
            )
        )

        val updatedUser = requireNotNull(userRepository.findByEmail(email))
        assertEquals(1, updatedUser.tokenVersion)
        assertEquals(email, authService.login(LoginRequest(email, "new-password1")).email)
        assertThrows(CustomException::class.java) {
            authService.resetPassword(
                PasswordResetRequest(
                    email = email,
                    verificationToken = verificationToken,
                    newPassword = "another-password1"
                )
            )
        }
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
        assertEquals("DANGER", analysis["status"])
        assertEquals(listOf("milk"), analysis["conflictingAllergenIds"])
    }

    @Test
    fun `product lookup search and filter share one warning based safety verdict`() {
        val barcode = "ALLERGY-API-0001"
        val user = userRepository.save(
            User(
                email = "allergy-api-test@example.com",
                nickname = "알레르기 API 테스트",
                allergies = "milk",
                password = "test-password"
            )
        )
        productRepository.save(
            Product(
                barcode = barcode,
                productName = "공통판정 두유바",
                rawMaterials = null,
                allergyWarning = "우유 함유",
                allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL,
                vegan = true
            )
        )
        val authentication = UsernamePasswordAuthenticationToken(user.id.toString(), null, emptyList())
        val scan = productController.getProductByBarcode(barcode, null, authentication)
        val searched = productController.searchProducts("공통판정", null, authentication)
        val filtered = productController.filterProducts(
            filters = listOf("vegan"),
            match = "all",
            keyword = "공통판정",
            page = 0,
            size = 20,
            userId = null,
            authentication = authentication
        )
        val scanAnalysis = ((scan.body as Map<*, *>)["data"] as Map<*, *>)["analysis"] as Map<*, *>
        val searchItem = ((searched.body as Map<*, *>)["data"] as List<*>)
            .map { it as Map<*, *> }
            .first { (it["product"] as Product).barcode == barcode }
        val searchAnalysis = searchItem["analysis"] as Map<*, *>
        val filterItems = (((filtered.body as Map<*, *>)["data"] as Map<*, *>)["items"] as List<*>)
        val filterAnalysis = (filterItems.first() as Map<*, *>)["analysis"] as Map<*, *>
        listOf(scanAnalysis, searchAnalysis, filterAnalysis).forEach { analysis ->
            assertEquals("DANGER", analysis["status"])
            assertEquals(true, analysis["isDangerous"])
            assertEquals(listOf("milk"), analysis["conflictingAllergenIds"])
            assertEquals(listOf("우유"), analysis["dangerousIngredients"])
        }
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
    fun `classification api exposes stable IDs and filters exact multi-value memberships`() {
        productRepository.saveAll(
            listOf(
                Product(
                    barcode = "CLASS-FILTER-0001",
                    productName = "분류필터 대상 하나",
                    foodCategories = "음료|유제품",
                    allergyClassification = "우유|밀"
                ),
                Product(
                    barcode = "CLASS-FILTER-0002",
                    productName = "분류필터 대상 둘",
                    foodCategories = "음료",
                    allergyClassification = "우유"
                ),
                Product(
                    barcode = "CLASS-FILTER-0003",
                    productName = "분류필터 대상 셋",
                    foodCategories = "유제품",
                    allergyClassification = "밀"
                )
            )
        )
        listOf(
            "CLASS-FILTER-0001" to "beverage",
            "CLASS-FILTER-0001" to "dairy",
            "CLASS-FILTER-0002" to "beverage",
            "CLASS-FILTER-0003" to "dairy"
        ).forEach { (barcode, categoryId) ->
            jdbcTemplate.update(
                "INSERT INTO product_food_category_memberships (barcode, category_id) VALUES (?, ?)",
                barcode,
                categoryId
            )
        }
        listOf(
            "CLASS-FILTER-0001" to "milk",
            "CLASS-FILTER-0001" to "wheat",
            "CLASS-FILTER-0002" to "milk",
            "CLASS-FILTER-0003" to "wheat"
        ).forEach { (barcode, allergyId) ->
            jdbcTemplate.update(
                "INSERT INTO product_allergy_classification_memberships (barcode, allergy_id) VALUES (?, ?)",
                barcode,
                allergyId
            )
        }

        val metadata = (productController.getAvailableClassifications().body as Map<*, *>)["data"] as Map<*, *>
        assertEquals(14, (metadata["foodCategories"] as List<*>).size)
        assertEquals(26, (metadata["allergens"] as List<*>).size)

        val allResponse = productController.filterProducts(
            filters = null,
            match = "all",
            categories = listOf("beverage,dairy"),
            categoryMatch = "all",
            containsAllergens = listOf("milk,wheat"),
            allergenMatch = "all",
            keyword = "분류필터",
            page = 0,
            size = 20,
            userId = null,
            authentication = null
        )
        val allData = (allResponse.body as Map<*, *>)["data"] as Map<*, *>
        assertEquals(1L, allData["totalElements"])
        val allProduct = (((allData["items"] as List<*>).single() as Map<*, *>)["product"] as Product)
        assertEquals("CLASS-FILTER-0001", allProduct.barcode)
        assertEquals(listOf("beverage", "dairy"), allProduct.foodCategoryIds)
        assertEquals(listOf("milk", "wheat"), allProduct.allergyClassificationIds)

        val axisAndResponse = productController.filterProducts(
            filters = null,
            match = "all",
            categories = listOf("beverage,dairy"),
            categoryMatch = "any",
            containsAllergens = listOf("milk"),
            allergenMatch = "any",
            keyword = "분류필터",
            page = 0,
            size = 20,
            userId = null,
            authentication = null
        )
        val axisAndData = (axisAndResponse.body as Map<*, *>)["data"] as Map<*, *>
        assertEquals(2L, axisAndData["totalElements"])
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
