package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.UserRepository
import org.springframework.stereotype.Service
import org.springframework.web.client.RestClient
import org.jjikmuk.backend.domain.chat.dto.ChatRequestDto
import org.jjikmuk.backend.domain.chat.dto.ProfileDto
import org.jjikmuk.backend.domain.chat.dto.ProductDto
import org.jjikmuk.backend.domain.chat.dto.AiChatRequestDto
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

@Configuration
class RestClientConfig {
    @Bean
    fun restClient(): RestClient {
        return RestClient.create()
    }
}

@Service
class ChatService(
    private val userRepository: UserRepository,
    private val productRepository: ProductRepository,
    private val restClient: RestClient
) {
    fun askToAiChatbot(request: ChatRequestDto): String {
        // 1. DB에서 유저와 제품 정보 조회
        val user = request.userId?.let { userRepository.findById(it).orElse(null) }
        val product = request.barcode?.let { productRepository.findFirstByBarcode(it) }

        // 2. AI 서버에 보낼 JSON 모양으로 조립
        val profileDto = user?.let { ProfileDto(it.id, it.nickname, it.allergies, it.diseases, it.specialDiet, it.dislikedIngredients) }
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

        val aiRequest = AiChatRequestDto(
            profile = profileDto,
            profiles = null, // 현재는 단일 프로필로 가정
            product = productDto,
            message = request.message,
            chat_history = request.chatHistory
        )

        // 3. AI 서버(8000 포트)로 POST 요청 발사!
        val aiResponse = restClient.post()
            .uri("http://localhost:8000/chat")
            .body(aiRequest)
            .retrieve()
            .body(String::class.java)

        // 4. 프론트엔드로 응답 전달
        return aiResponse ?: throw RuntimeException("AI 서버 응답이 없습니다.")
    }
}
