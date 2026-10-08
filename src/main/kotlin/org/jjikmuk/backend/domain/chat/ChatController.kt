package org.jjikmuk.backend.domain.chat

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.*
import org.jjikmuk.backend.domain.chat.dto.ChatRequestDto

@RestController
@RequestMapping("/api/chat")
class ChatController(
    private val chatService: ChatService
) {
    @PostMapping
    fun chatWithAi(@RequestBody request: ChatRequestDto): ResponseEntity<*> {
        val response = chatService.askToAiChatbot(request)
        // AI 서버에서 받은 JSON 응답을 그대로 프론트엔드에 전달합니다.
        return ResponseEntity.ok(response)
    }
}