package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.product.ProductService
import org.jjikmuk.backend.domain.recommendation.ProductDataEvidence
import org.jjikmuk.backend.domain.recommendation.RecommendationPolicy
import org.jjikmuk.backend.domain.recommendation.RecommendationService
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import org.springframework.web.client.RestClient
import org.jjikmuk.backend.domain.chat.dto.ChatRequestDto
import org.jjikmuk.backend.domain.chat.dto.ProductDto
import org.jjikmuk.backend.domain.chat.dto.AiChatRequestDto
import org.jjikmuk.backend.domain.chat.dto.ChatAnalysisContext
import org.jjikmuk.backend.domain.chat.dto.ChatEffectiveConditions
import org.jjikmuk.backend.domain.chat.dto.ChatProfileAnalysis
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import java.util.UUID

@Configuration
class RestClientConfig {
    @Bean
    fun restClient(): RestClient {
        return RestClient.create()
    }
}

@Service
class ChatService(
    private val productRepository: ProductRepository,
    private val productService: ProductService,
    private val profiles: ChatProfileResolver,
    private val policy: RecommendationPolicy,
    private val aiClient: AiChatClient
) {
    fun askToAiChatbot(request: ChatRequestDto, ownerId: Long,
        analysisMode: String? = null, includeSelf: Boolean? = null, familyProfileIds: List<Long>? = null
    ): String {
        // Never use a client-supplied account ID to fetch private conditions.
        if (request.userId != null && request.userId != ownerId) {
            throw CustomException(HttpStatus.FORBIDDEN, "다른 사용자의 조건으로 질문할 수 없습니다.", "ACCESS_DENIED")
        }
        validate(request)
        val resolved = profiles.resolve(request, ownerId, analysisMode, includeSelf, familyProfileIds)
        val effective = resolved.effective
        val user = effective.profile.takeIf { effective.applied }
        val product = (request.barcode ?: request.product?.barcode)?.let { barcode ->
            productRepository.findFirstByBarcode(barcode)
                ?: throw CustomException(HttpStatus.NOT_FOUND, "선택한 상품을 찾을 수 없습니다.", "PRODUCT_NOT_FOUND")
        }

        // 2. AI 서버에 보낼 JSON 모양으로 조립
        val selectedProfiles = resolved.selected.map { it.dto }
        val productDto = product?.let {
            ProductDto(
                reportNo = it.reportNo,
                barcode = it.barcode,
                productName = it.productName,
                manufacturer = it.manufacturer,
                allergy = it.allergy,
                rawMaterialName = it.rawMaterials,
                nutrientText = it.nutrientText,
                allergyWarning = it.allergyWarning,
                foodCategories = it.foodCategories,
                foodCategoryIds = it.foodCategoryIds,
                allergyClassification = it.allergyClassification,
                allergyClassificationIds = it.allergyClassificationIds,
                allergyClassificationState = it.allergyClassificationState,
                source = it.source,
                weight = it.totalWeight,
                energyKcal = it.energyKcal,
                carbsG = it.carbsG,
                proteinG = it.proteinG,
                fatG = it.fatG,
                sugarG = it.sugarG,
                sodiumMg = it.sodiumMg,
                cholesterolMg = it.cholesterolMg,
                vegan = it.vegan,
                lactoVegetarian = it.lactoVegetarian,
                ovoVegetarian = it.ovoVegetarian,
                lactoOvoVegetarian = it.lactoOvoVegetarian,
                pescatarian = it.pescatarian,
                pollotarian = it.pollotarian,
                lowSugar = it.lowSugar,
                lowSodium = it.lowSodium,
                glutenFree = it.glutenFree,
                lowCalorie = it.lowCalorie,
                lowFat = it.lowFat,
                highProtein = it.highProtein
            )
        }

        val allergyProfile = user?.let { AllergyCatalog.parse(it.allergies) }
        val aiRequest = AiChatRequestDto(
            // Never insert an aggregate pseudo-person alongside real people.
            profile = selectedProfiles.singleOrNull(),
            profiles = if (selectedProfiles.size > 1) selectedProfiles else emptyList(),
            product = productDto,
            message = request.message,
            chat_history = (request.chat_history ?: request.chatHistory).map { requireNotNull(it) },
            analysisContext = ChatAnalysisContext(
                contextId = UUID.randomUUID().toString(),
                policyVersion = RecommendationService.POLICY_VERSION,
                selection = effective.selection,
                effectiveConditions = user?.let {
                    ChatEffectiveConditions(
                        allergyProfile!!.ids.map { allergy -> allergy.id }.sorted(),
                        allergyProfile.unknownTerms.sorted(),
                        policy.requiredFilters(it).map { filter -> filter.key }.sorted(),
                        policy.profileTerms(it.diseases), policy.profileTerms(it.dislikedIngredients)
                    )
                },
                productResolution = if (product == null) "NOT_PROVIDED" else "FOUND",
                analysis = product?.let { productService.evaluateProductConditions(it, user, analysis = effective) },
                dataEvidence = product?.let { ProductDataEvidence(it.allergyEvidenceLevel, it.allergyDataConfidence,
                    it.nutritionDataOrigin, it.nutritionDataConfidence, it.dietaryDataOrigin, it.dietaryDataConfidence) },
                profileSource = resolved.source,
                profileAnalyses = resolved.selected.map { selected ->
                    ChatProfileAnalysis(requireNotNull(selected.dto.profileKey),
                        product?.let { productService.evaluateProductConditions(it, selected.analysis.profile,
                            analysis = selected.analysis) })
                }
            )
        )
        // No SCAN writes, and no transaction held across the external AI request.
        return aiClient.ask(aiRequest)
    }

    private fun validate(request: ChatRequestDto) {
        fun invalid(field: String): Nothing = throw CustomException(HttpStatus.BAD_REQUEST,
            "질문 또는 대화 이력의 형식·크기를 확인해주세요.", "VALIDATION_FAILED", field)
        if (request.message.isBlank() || request.message.length > 4000) invalid("message")
        for (barcode in listOfNotNull(request.barcode, request.product?.barcode)) {
            if (barcode.isBlank() || barcode.length > 255 || barcode != barcode.trim()) invalid("barcode")
        }
        request.product?.let {
            if (request.barcode != null && request.barcode != it.barcode) invalid("product.barcode")
            if ((it.productName?.length ?: 0) > 500 || (it.rawMaterials?.length ?: 0) > 16000 ||
                it.allergy.size > 26 || it.allergy.any { value -> value == null || value.length > 100 }) invalid("product")
        }
        if (request.chat_history != null && request.chatHistory.isNotEmpty()) invalid("chatHistory")
        val history = (request.chat_history ?: request.chatHistory).map { it ?: invalid("chatHistory") }
        if (history.size > 20 || history.sumOf { it.content.length.toLong() } > 40000) invalid("chatHistory")
        if (history.any { it.role !in setOf("user", "assistant") || it.content.isBlank() || it.content.length > 10000 }) {
            invalid("chatHistory")
        }
    }
}
