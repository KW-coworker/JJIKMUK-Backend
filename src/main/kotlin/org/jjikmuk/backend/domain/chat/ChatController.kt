package org.jjikmuk.backend.domain.chat

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.*
import org.jjikmuk.backend.domain.chat.dto.ChatRequestDto
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.security.core.Authentication

@RestController
@RequestMapping("/api/chat")
class ChatController(
    private val chatService: ChatService,
    private val storedChat: StoredChatService
) {
    @ModelAttribute
    fun preventCaching(response: jakarta.servlet.http.HttpServletResponse) {
        response.setHeader("Cache-Control", "no-store")
    }

    @PostMapping
    fun chatWithAi(
        @RequestBody request: ChatRequestDto,
        authentication: Authentication?,
        @RequestParam(required = false) analysisMode: String? = null,
        @RequestParam(required = false) includeSelf: Boolean? = null,
        @RequestParam(required = false) familyProfileIds: List<Long>? = null
    ): ResponseEntity<String> {
        val ownerId = authentication?.takeIf { it.isAuthenticated }?.principal?.toString()?.toLongOrNull()
            ?: throw CustomException(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다.", "AUTHENTICATION_REQUIRED")
        if (request.conversationId != null || request.clientMessageId != null) {
            val reply = storedChat.ask(request, ownerId, analysisMode, includeSelf, familyProfileIds)
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON)
                .header("X-Jjikmuk-Conversation-Id", request.conversationId.toString())
                .header("X-Jjikmuk-Chat-Turn-Id", reply.turnId.toString())
                .header("X-Jjikmuk-Chat-Replayed", reply.replayed.toString()).body(reply.body)
        }
        val response = chatService.askToAiChatbot(request, ownerId, analysisMode, includeSelf, familyProfileIds)
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(response)
    }
}
