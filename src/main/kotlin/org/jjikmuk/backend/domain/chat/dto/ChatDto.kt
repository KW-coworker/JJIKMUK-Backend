package org.jjikmuk.backend.domain.chat.dto

// 💡 프론트엔드가 성민님 서버로 보낼 요청
data class ChatRequestDto(
    val userId: Long?, // 멀티 프로필 확장 시 List<Long>으로 변경 가능
    val barcode: String?,
    val message: String,
    val chatHistory: List<ChatHistoryDto> = emptyList()
)

// 💡 성민님 서버가 AI 서버(8000포트)로 보낼 요청
data class AiChatRequestDto(
    val profile: ProfileDto?,      // 단일 프로필용
    val profiles: List<ProfileDto>?, // 멀티 프로필용
    val product: ProductDto?,
    val message: String,
    val chat_history: List<ChatHistoryDto>
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
