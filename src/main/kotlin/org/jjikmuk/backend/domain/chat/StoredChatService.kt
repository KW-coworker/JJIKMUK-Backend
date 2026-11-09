package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.chat.dto.ChatRequestDto
import org.jjikmuk.backend.domain.user.ProfileInputs
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import tools.jackson.databind.json.JsonMapper
import java.security.MessageDigest
import java.util.TreeMap

data class StoredChatReply(val body: String, val turnId: Long, val replayed: Boolean)

/** No surrounding transaction: reserve/complete/fail use separate proxied short transactions. */
@Service
class StoredChatService(private val chat: ChatService, private val store: ChatConversationStore) {
    private val mapper = JsonMapper.builder().findAndAddModules().build()

    fun ask(request: ChatRequestDto, owner: Long, analysisMode: String?, includeSelf: Boolean?,
        familyProfileIds: List<Long>?): StoredChatReply {
        val room = request.conversationId?.takeIf { it > 0 }
            ?: throw ProfileInputs.invalid("conversationId", "저장할 채팅방 ID가 필요합니다.")
        val key = chatUuid(request.clientMessageId, "clientMessageId")
        // Authorize the room before resolving any profiles or making an AI call, even for admins.
        store.get(owner, room)
        if (request.chatHistory.isNotEmpty() || !request.chat_history.isNullOrEmpty())
            throw ProfileInputs.invalid("chatHistory", "저장형 채팅에서는 서버 대화를 사용합니다. 클라이언트 이력을 보내지 마세요.")
        val prepared = chat.prepareRequest(request, owner, analysisMode, includeSelf, familyProfileIds)
        val hash = fingerprint(mapOf("body" to request.copy(clientMessageId = key), "analysisMode" to analysisMode,
            "includeSelf" to includeSelf, "familyProfileIds" to familyProfileIds))
        // Changed people, dietary conditions, product facts or policy cannot inherit stale history.
        val contextHash = fingerprint(mapOf("profile" to prepared.profile, "profiles" to prepared.profiles,
            "product" to prepared.product, "selection" to prepared.analysisContext.selection,
            "conditions" to prepared.analysisContext.effectiveConditions, "policy" to prepared.analysisContext.policyVersion))
        val reserved = store.reserve(owner, room, key, hash, contextHash, request.message, prepared.product?.barcode)
        reserved.replayBody?.let { return StoredChatReply(it, reserved.id, true) }
        try {
            val body = chat.askPrepared(prepared.copy(chat_history = reserved.history), owner, request.externalAiConsent)
            // Preserve the full AI response for FE reconstruction, not just generated prose.
            if (body.toByteArray(Charsets.UTF_8).size > 1024 * 1024 ||
                !runCatching { mapper.readTree(body).isObject }.getOrDefault(false)) {
                throw CustomException(HttpStatus.BAD_GATEWAY, "저장할 AI 응답 형식·크기를 확인해주세요.", "AI_RESPONSE_INVALID")
            }
            store.complete(owner, room, reserved.id, body)
            return StoredChatReply(body, reserved.id, false)
        } catch (error: Exception) {
            // Never persist raw exception messages, network addresses, headers or credentials.
            // If recording failure also fails, the finite PENDING lease still prevents a stuck room.
            runCatching { store.fail(owner, room, reserved.id, (error as? CustomException)?.code ?: "CHAT_PROCESSING_FAILED") }
            throw error
        }
    }

    private fun fingerprint(value: Any): String {
        fun canonical(v: Any?): Any? = when (v) {
            is Map<*, *> -> TreeMap(v.entries.associate { it.key.toString() to canonical(it.value) })
            is List<*> -> v.map { canonical(it) }
            else -> v
        }
        val bytes = mapper.writeValueAsBytes(canonical(mapper.convertValue(value, Map::class.java)))
        return MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
