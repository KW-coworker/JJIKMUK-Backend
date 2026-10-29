package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.product.ProductService
import org.jjikmuk.backend.domain.recommendation.ProductDataEvidence
import org.jjikmuk.backend.domain.recommendation.RecommendationPolicy
import org.jjikmuk.backend.domain.recommendation.RecommendationService
import org.jjikmuk.backend.domain.user.AnalysisSelectionService
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import org.springframework.web.client.RestClient
import org.jjikmuk.backend.domain.chat.dto.ChatRequestDto
import org.jjikmuk.backend.domain.chat.dto.ProfileDto
import org.jjikmuk.backend.domain.chat.dto.ProductDto
import org.jjikmuk.backend.domain.chat.dto.AiChatRequestDto
import org.jjikmuk.backend.domain.chat.dto.ChatAnalysisContext
import org.jjikmuk.backend.domain.chat.dto.ChatEffectiveConditions
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
    private val selections: AnalysisSelectionService,
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
        val effective = selections.resolve(ownerId, analysisMode, includeSelf, familyProfileIds)
        val user = effective.profile.takeIf { effective.applied }
        val product = request.barcode?.let { barcode ->
            productRepository.findFirstByBarcode(barcode)
                ?: throw CustomException(HttpStatus.NOT_FOUND, "선택한 상품을 찾을 수 없습니다.", "PRODUCT_NOT_FOUND")
        }

        // 2. AI 서버에 보낼 JSON 모양으로 조립
        val profileDto = user?.let {
            // The current AI service still consumes Korean allergy names. Keep its wire
            // format compatible while users are stored under stable English IDs.
            val profile = AllergyCatalog.parse(it.allergies)
            val allergiesForAi = (profile.ids.map { allergy -> allergy.displayName } + profile.unknownTerms)
                .takeIf(List<String>::isNotEmpty)
                ?.joinToString(", ")
            // selected is an effective union, NOT the account holder or one family member.
            ProfileDto(if (effective.selection.mode == "self") ownerId else null,
                if (effective.selection.mode == "self") it.nickname else "선택한 분석 대상",
                allergiesForAi, it.diseases, it.specialDiet, it.dislikedIngredients)
        }
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
            profile = profileDto,
            profiles = null, // Legacy field: v1 deliberately transmits only the effective union.
            product = productDto,
            message = request.message,
            chat_history = request.chatHistory,
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
                    it.nutritionDataOrigin, it.nutritionDataConfidence, it.dietaryDataOrigin, it.dietaryDataConfidence) }
            )
        )
        // No SCAN writes, and no transaction held across the external AI request.
        return aiClient.ask(aiRequest)
    }

    private fun validate(request: ChatRequestDto) {
        fun invalid(field: String): Nothing = throw CustomException(HttpStatus.BAD_REQUEST,
            "질문 또는 대화 이력의 형식·크기를 확인해주세요.", "VALIDATION_FAILED", field)
        if (request.message.isBlank() || request.message.length > 4000) invalid("message")
        if (request.barcode != null && (request.barcode.isBlank() || request.barcode.length > 255 ||
                request.barcode != request.barcode.trim())) invalid("barcode")
        if (request.chatHistory.size > 20 || request.chatHistory.sumOf { it.content.length.toLong() } > 40000) invalid("chatHistory")
        if (request.chatHistory.any { it.role !in setOf("user", "assistant") || it.content.isBlank() || it.content.length > 10000 }) {
            invalid("chatHistory")
        }
    }
}
