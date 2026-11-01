package org.jjikmuk.backend.domain.chat.dto

import com.fasterxml.jackson.annotation.JsonAnySetter
import org.jjikmuk.backend.domain.recommendation.ProductDataEvidence
import org.jjikmuk.backend.domain.user.AnalysisSelectionResponse

// Query selects owned server profiles. Body profile(s) explicitly supplies request-only snapshots.
data class ChatRequestDto(
    val userId: Long? = null, // Compatibility only: must equal the JWT owner, including admins.
    val barcode: String? = null,
    val message: String,
    val chatHistory: List<ChatHistoryDto?> = emptyList(),
    val chat_history: List<ChatHistoryDto?>? = null,
    val profile: ChatProfileInput? = null,
    // null/omitted preserves the legacy default; [] explicitly means no selected people.
    val profiles: List<ChatProfileInput?>? = null,
    val product: ChatProductInput? = null
) {
    // Do not silently ignore body-level selection or forged server decisions.
    @JsonAnySetter
    fun rejectUnknown(name: String, value: Any?) {
        throw IllegalArgumentException("지원하지 않는 요청 필드: $name")
    }
}

data class ChatProfileInput(
    val id: Long? = null, // Client-local reference only. NEVER used for a database lookup.
    val nickname: String,
    val allergies: String? = null,
    val diseases: String? = null,
    val specialDiet: String? = null,
    val dislikedIngredients: String? = null,
    val isActive: Boolean? = true
) {
    @JsonAnySetter fun rejectUnknown(name: String, value: Any?) {
        throw IllegalArgumentException("지원하지 않는 프로필 필드: $name")
    }
}

// Android develop compatibility only. Product facts and verdicts always come from the DB.
data class ChatProductInput(val barcode: String, val productName: String? = null,
    val allergy: List<String?> = emptyList(), val rawMaterials: String? = null) {
    @JsonAnySetter fun rejectUnknown(name: String, value: Any?) {
        throw IllegalArgumentException("지원하지 않는 상품 필드: $name")
    }
}

// 💡 성민님 서버가 AI 서버(8000포트)로 보낼 요청
data class AiChatRequestDto(
    val profile: ProfileDto?,      // 단일 프로필용
    val profiles: List<ProfileDto>, // Multi-profile list; empty when profile is used or none selected.
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
    val storedDietFlagsAreAuthoritative: Boolean = false,
    val profileSource: String = "SERVER",
    val profileAnalyses: List<ChatProfileAnalysis> = emptyList()
) {
    companion object { const val VERSION = "chat-analysis-v2" }
}

data class ChatProfileAnalysis(val profileKey: String, val analysis: Map<String, Any>?)

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
    val dislikedIngredients: String?,
    val profileKey: String? = null,
    val profileSource: String = "SERVER",
    // Separate from account id; permits distinct family/snapshot names even when names coincide.
    val profile_id: Long? = null,
    val target_type: String = "self"
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
