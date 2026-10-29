package org.jjikmuk.backend.domain.chat.dto

import com.fasterxml.jackson.annotation.JsonAnySetter
import org.jjikmuk.backend.domain.recommendation.ProductDataEvidence
import org.jjikmuk.backend.domain.user.AnalysisSelectionResponse

// Selection parameters are query parameters, just like the product APIs.
data class ChatRequestDto(
    val userId: Long? = null, // Compatibility only: must equal the JWT owner, including admins.
    val barcode: String? = null,
    val message: String,
    val chatHistory: List<ChatHistoryDto> = emptyList()
) {
    // Do not silently ignore body-level selection or forged server decisions.
    @JsonAnySetter
    fun rejectUnknown(name: String, value: Any?) {
        throw IllegalArgumentException("지원하지 않는 요청 필드: $name")
    }
}

// 💡 성민님 서버가 AI 서버(8000포트)로 보낼 요청
data class AiChatRequestDto(
    val profile: ProfileDto?,      // 단일 프로필용
    val profiles: List<ProfileDto>?, // 멀티 프로필용
    val product: ProductDto?,
    val message: String,
    val chat_history: List<ChatHistoryDto>,
    val analysisContext: ChatAnalysisContext
)

data class ChatAnalysisContext(
    val contextId: String,
    val contractVersion: String = VERSION,
    val policyVersion: String,
    val selection: AnalysisSelectionResponse,
    val effectiveConditions: ChatEffectiveConditions?,
    val productResolution: String,
    // A product detail barcode row; not the conservative aggregate of a capacity option.
    val decisionScope: String = "BARCODE_ROW",
    val analysis: Map<String, Any>?,
    val dataEvidence: ProductDataEvidence?,
    val decisionAuthority: String = "BACKEND",
    val historyIsAuthoritative: Boolean = false,
    val storedDietFlagsAreAuthoritative: Boolean = false
) {
    companion object { const val VERSION = "chat-analysis-v1" }
}

data class ChatEffectiveConditions(
    val allergyIds: List<String>,
    val unknownAllergyTerms: List<String>,
    val requiredDietFilterIds: List<String>,
    val diseases: List<String>,
    val dislikedIngredients: List<String>
)

data class ChatHistoryDto(
    val role: String,
    val content: String
)

// 기존 User, Product 엔티티를 이 DTO로 변환해서 담습니다.
// (AI 팀원이 키값을 유연하게 만들어 두어서 기존 필드명과 비슷하게 쓰시면 됩니다!)
data class ProfileDto(
    val id: Long?,
    val nickname: String,
    val allergies: String?,
    val diseases: String?,
    val specialDiet: String?,
    val dislikedIngredients: String?
)

data class ProductDto(
    val reportNo: String?,
    val barcode: String?,
    val productName: String?,
    val manufacturer: String?,
    val allergy: String?,
    val rawMaterialName: String?,
    val nutrientText: String?,
    val allergyWarning: String?,
    val foodCategories: String?,
    val foodCategoryIds: List<String>,
    val allergyClassification: String?,
    val allergyClassificationIds: List<String>,
    val allergyClassificationState: String,
    val source: String?,
    val weight: String?,
    val energyKcal: Double?,
    val carbsG: Double?,
    val proteinG: Double?,
    val fatG: Double?,
    val sugarG: Double?,
    val sodiumMg: Double?,
    val cholesterolMg: Double?,
    val vegan: Boolean,
    val lactoVegetarian: Boolean,
    val ovoVegetarian: Boolean,
    val lactoOvoVegetarian: Boolean,
    val pescatarian: Boolean,
    val pollotarian: Boolean,
    val lowSugar: Boolean,
    val lowSodium: Boolean,
    val glutenFree: Boolean,
    val lowCalorie: Boolean,
    val lowFat: Boolean,
    val highProtein: Boolean
)
