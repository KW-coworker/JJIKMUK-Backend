package org.jjikmuk.backend.domain.chat

import com.fasterxml.jackson.annotation.JsonAnySetter
import jakarta.persistence.*
import org.jjikmuk.backend.domain.chat.dto.ChatHistoryDto
import org.jjikmuk.backend.domain.user.ProfileInputs
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.domain.user.validateListPage
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.data.domain.PageRequest
import org.springframework.data.domain.Pageable
import org.springframework.data.domain.Slice
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock
import org.springframework.data.jpa.repository.Modifying
import org.springframework.data.jpa.repository.Query
import org.springframework.http.HttpStatus
import org.springframework.security.core.Authentication
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.*
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.UUID

internal fun chatNow(): LocalDateTime = LocalDateTime.now(ZoneOffset.UTC)
internal fun chatUuid(raw: String?, field: String): String {
    val valid = raw != null && raw.matches(Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))
    if (!valid) throw ProfileInputs.invalid(field, "UUID 형식으로 전달해주세요.")
    return UUID.fromString(raw).toString()
}
internal fun chatNotFound(): Nothing = throw CustomException(HttpStatus.NOT_FOUND,
    "채팅방을 찾을 수 없습니다.", "CHAT_CONVERSATION_NOT_FOUND")
internal fun chatConflict(code: String, message: String, retry: Long? = null): Nothing =
    throw CustomException(HttpStatus.CONFLICT, message, code, retryAfterSeconds = retry)

@Entity @Table(name = "chat_conversations", uniqueConstraints = [UniqueConstraint(
    name = "uk_chat_conversation_owner_client", columnNames = ["owner_id", "client_conversation_id"])])
class ChatConversation(
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) val id: Long? = null,
    @Column(nullable = false) val ownerId: Long,
    @Column(nullable = false, length = 36) val clientConversationId: String,
    @Column(nullable = false, length = 100) val title: String,
    var activeTurnId: Long? = null,
    @Column(nullable = false) val createdAt: LocalDateTime = chatNow(),
    @Column(nullable = false) var updatedAt: LocalDateTime = createdAt
) {
    fun response() = ChatConversationResponse(requireNotNull(id), clientConversationId, title, createdAt, updatedAt)
}

enum class ChatTurnStatus { PENDING, SUCCEEDED, FAILED }

/** One row per question/answer pair: retry keys never create a second user bubble. */
@Entity @Table(name = "chat_turns", uniqueConstraints = [UniqueConstraint(
    name = "uk_chat_turn_conversation_client", columnNames = ["conversation_id", "client_message_id"])])
class ChatTurn(
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) val id: Long? = null,
    @Column(nullable = false) val conversationId: Long,
    @Column(nullable = false, length = 36) val clientMessageId: String,
    @Column(nullable = false, length = 64) val requestHash: String,
    @Column(nullable = false, length = 64) val contextHash: String,
    @Column(nullable = false, columnDefinition = "TEXT") val message: String,
    @Column(length = 255) val barcode: String? = null,
    @Enumerated(EnumType.STRING) @Column(nullable = false, length = 16)
    var status: ChatTurnStatus = ChatTurnStatus.PENDING,
    @Column(columnDefinition = "LONGTEXT") var responseBody: String? = null,
    @Column(length = 80) var errorCode: String? = null,
    @Column(nullable = false) val createdAt: LocalDateTime = chatNow(),
    var completedAt: LocalDateTime? = null,
    @Column(nullable = false) val expiresAt: LocalDateTime = createdAt.plusMinutes(2)
)

interface ChatConversationRepository : JpaRepository<ChatConversation, Long> {
    fun findByIdAndOwnerId(id: Long, ownerId: Long): ChatConversation?
    fun findByOwnerIdAndClientConversationId(ownerId: Long, clientConversationId: String): ChatConversation?
    fun findByOwnerIdOrderByUpdatedAtDescIdDesc(ownerId: Long, page: Pageable): Slice<ChatConversation>
    fun countByOwnerId(ownerId: Long): Long
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from ChatConversation c where c.id = :id and c.ownerId = :ownerId")
    fun lockOwned(id: Long, ownerId: Long): ChatConversation?
    @Modifying @Query("delete from ChatConversation c where c.ownerId = :ownerId")
    fun deleteOwned(ownerId: Long)
}
interface ChatTurnRepository : JpaRepository<ChatTurn, Long> {
    fun findByConversationIdAndClientMessageId(conversationId: Long, clientMessageId: String): ChatTurn?
    fun findByConversationIdAndIdGreaterThanOrderByIdAsc(conversationId: Long, afterId: Long, page: Pageable): Slice<ChatTurn>
    fun findByConversationIdAndContextHashAndStatusOrderByIdDesc(conversationId: Long, contextHash: String,
        status: ChatTurnStatus, page: Pageable): List<ChatTurn>
    fun countByConversationId(conversationId: Long): Long
    @Modifying @Query("delete from ChatTurn t where t.conversationId = :conversationId")
    fun deleteInConversation(conversationId: Long)
    @Modifying @Query("delete from ChatTurn t where t.conversationId in (select c.id from ChatConversation c where c.ownerId = :ownerId)")
    fun deleteOwned(ownerId: Long)
}

data class CreateChatConversationRequest(val clientConversationId: String, val title: String? = null) {
    @JsonAnySetter fun rejectUnknown(name: String, value: Any?) {
        throw IllegalArgumentException("지원하지 않는 요청 필드: $name")
    }
}
data class ChatConversationResponse(val id: Long, val clientConversationId: String, val title: String,
    val createdAt: LocalDateTime, val updatedAt: LocalDateTime)
data class ChatConversationPage(val items: List<ChatConversationResponse>, val page: Int, val size: Int, val hasNext: Boolean)
data class ChatTurnResponse(val id: Long, val clientMessageId: String, val message: String, val barcode: String?,
    val status: ChatTurnStatus, val response: JsonNode?, val errorCode: String?,
    val createdAt: LocalDateTime, val completedAt: LocalDateTime?, val expiresAt: LocalDateTime)
data class ChatTurnPage(val items: List<ChatTurnResponse>, val nextAfterId: Long, val hasNext: Boolean)
data class ReservedChatTurn(val id: Long, val history: List<ChatHistoryDto>, val replayBody: String? = null)

/** Short transactions only. Lock order is always account -> conversation -> turn.
 * Account deletion shares the account lock, preventing late AI completions from resurrecting data.
 */
@Service @Transactional(readOnly = true)
class ChatConversationStore(
    private val conversations: ChatConversationRepository,
    private val turns: ChatTurnRepository,
    private val users: UserRepository
) {
    private val mapper = JsonMapper.builder().build()
    private fun owned(owner: Long, id: Long) = conversations.findByIdAndOwnerId(id, owner) ?: chatNotFound()
    private fun lock(owner: Long, id: Long): ChatConversation {
        users.lockById(owner) ?: chatNotFound()
        return conversations.lockOwned(id, owner) ?: chatNotFound()
    }

    fun list(owner: Long, page: Int, size: Int): ChatConversationPage {
        validateListPage(page, size)
        val rows = conversations.findByOwnerIdOrderByUpdatedAtDescIdDesc(owner, PageRequest.of(page, size))
        return ChatConversationPage(rows.content.map { it.response() }, page, size, rows.hasNext())
    }
    fun get(owner: Long, id: Long) = owned(owner, id).response()

    @Transactional
    fun create(owner: Long, body: CreateChatConversationRequest): ChatConversationResponse {
        val key = chatUuid(body.clientConversationId, "clientConversationId")
        val title = body.title?.trim() ?: "새 대화"
        if (title.isBlank() || title.length > 100 || title.any { it.isISOControl() })
            throw ProfileInputs.invalid("title", "제목은 제어 문자 없이 1~100자로 입력해주세요.")
        users.lockById(owner) ?: chatNotFound()
        conversations.findByOwnerIdAndClientConversationId(owner, key)?.let {
            if (it.title != title) chatConflict("CHAT_IDEMPOTENCY_CONFLICT", "같은 생성 요청 ID의 제목이 달라졌습니다.")
            return it.response()
        }
        if (conversations.countByOwnerId(owner) >= 1000)
            chatConflict("CHAT_CONVERSATION_LIMIT", "채팅방은 계정당 최대 1,000개입니다.")
        return conversations.saveAndFlush(ChatConversation(ownerId = owner, clientConversationId = key, title = title)).response()
    }

    fun messages(owner: Long, id: Long, afterId: Long, limit: Int): ChatTurnPage {
        owned(owner, id)
        if (afterId < 0) throw ProfileInputs.invalid("afterId", "afterId는 0 이상이어야 합니다.")
        if (limit !in 1..50) throw ProfileInputs.invalid("limit", "limit은 1~50이어야 합니다.")
        val rows = turns.findByConversationIdAndIdGreaterThanOrderByIdAsc(id, afterId, PageRequest.of(0, limit))
        return ChatTurnPage(rows.content.map { response(it) }, rows.content.lastOrNull()?.id ?: afterId, rows.hasNext())
    }

    // Read a specific pending turn again: afterId pagination alone cannot discover its completion.
    fun message(owner: Long, id: Long, turnId: Long): ChatTurnResponse {
        owned(owner, id)
        val turn = turns.findById(turnId).orElse(null)?.takeIf { it.conversationId == id } ?: chatNotFound()
        return response(turn)
    }
    fun messageByClientId(owner: Long, id: Long, clientMessageId: String): ChatTurnResponse {
        owned(owner, id)
        return response(turns.findByConversationIdAndClientMessageId(id, chatUuid(clientMessageId, "clientMessageId"))
            ?: chatNotFound())
    }
    private fun response(turn: ChatTurn): ChatTurnResponse {
        val expired = turn.status == ChatTurnStatus.PENDING && !turn.expiresAt.isAfter(chatNow())
        return ChatTurnResponse(requireNotNull(turn.id), turn.clientMessageId, turn.message, turn.barcode,
            if (expired) ChatTurnStatus.FAILED else turn.status, turn.responseBody?.let { mapper.readTree(it) },
            if (expired) "CHAT_REQUEST_INTERRUPTED" else turn.errorCode, turn.createdAt, turn.completedAt, turn.expiresAt)
    }

    @Transactional
    fun reserve(owner: Long, id: Long, key: String, hash: String, contextHash: String,
        message: String, barcode: String?): ReservedChatTurn {
        val room = lock(owner, id)
        turns.findByConversationIdAndClientMessageId(id, key)?.let {
            if (it.requestHash != hash) chatConflict("CHAT_IDEMPOTENCY_CONFLICT", "같은 요청 ID의 질문 또는 분석 조건이 달라졌습니다.")
            when (it.status) {
                ChatTurnStatus.SUCCEEDED -> return ReservedChatTurn(requireNotNull(it.id), emptyList(), requireNotNull(it.responseBody))
                ChatTurnStatus.FAILED -> chatConflict("CHAT_MESSAGE_FAILED", "이 요청은 실패했습니다. 상태를 조회한 뒤 새 요청 ID로 다시 시도해주세요.")
                ChatTurnStatus.PENDING -> if (it.expiresAt.isAfter(chatNow()))
                    chatConflict("CHAT_REQUEST_IN_PROGRESS", "이 요청을 처리 중입니다. 메시지 상태를 조회해주세요.", 2)
                else chatConflict("CHAT_REQUEST_INTERRUPTED", "처리가 중단되었습니다. 새 요청 ID로 다시 시도해주세요.")
            }
        }
        room.activeTurnId?.let { activeId ->
            val active = turns.findById(activeId).orElse(null)
            if (active?.status == ChatTurnStatus.PENDING) {
                if (active.expiresAt.isAfter(chatNow()))
                    chatConflict("CHAT_CONVERSATION_BUSY", "이 채팅방의 이전 질문을 처리 중입니다.", 2)
                active.status = ChatTurnStatus.FAILED
                active.errorCode = "CHAT_REQUEST_INTERRUPTED"
                active.completedAt = chatNow()
            }
            room.activeTurnId = null
        }
        if (turns.countByConversationId(id) >= 1000)
            chatConflict("CHAT_MESSAGE_LIMIT", "채팅방당 최대 1,000회 질문할 수 있습니다. 새 채팅방을 만들어주세요.")
        val history = serverHistory(id, contextHash)
        val turn = turns.saveAndFlush(ChatTurn(conversationId = id, clientMessageId = key, requestHash = hash,
            contextHash = contextHash, message = message, barcode = barcode))
        room.activeTurnId = requireNotNull(turn.id)
        room.updatedAt = chatNow()
        return ReservedChatTurn(requireNotNull(turn.id), history)
    }

    private fun serverHistory(id: Long, contextHash: String): List<ChatHistoryDto> {
        val pairs = mutableListOf<List<ChatHistoryDto>>()
        var chars = 0
        val previous = turns.findByConversationIdAndContextHashAndStatusOrderByIdDesc(id, contextHash,
            ChatTurnStatus.SUCCEEDED, PageRequest.of(0, 10))
        for (turn in previous) {
            val answer = turn.responseBody?.let { mapper.readTree(it).get("answer") }
                ?.takeIf { it.isString }?.asText()?.takeIf { it.isNotBlank() } ?: continue
            if (answer.length > 10000 || chars + turn.message.length + answer.length > 40000) break
            pairs += listOf(ChatHistoryDto("user", turn.message), ChatHistoryDto("assistant", answer))
            chars += turn.message.length + answer.length
        }
        return pairs.asReversed().flatten()
    }

    @Transactional
    fun complete(owner: Long, id: Long, turnId: Long, body: String) {
        val room = lock(owner, id)
        val turn = turns.findById(turnId).orElseThrow { IllegalStateException("Missing reserved chat turn") }
        if (turn.conversationId != id || room.activeTurnId != turnId || turn.status != ChatTurnStatus.PENDING ||
            !turn.expiresAt.isAfter(chatNow()))
            chatConflict("CHAT_REQUEST_INTERRUPTED", "처리 기한이 지났거나 채팅 상태가 변경되었습니다.")
        turn.status = ChatTurnStatus.SUCCEEDED
        turn.responseBody = body
        turn.completedAt = chatNow()
        room.activeTurnId = null
        room.updatedAt = chatNow()
    }

    @Transactional
    fun fail(owner: Long, id: Long, turnId: Long, code: String) {
        if (users.lockById(owner) == null) return
        val room = conversations.lockOwned(id, owner) ?: return
        val turn = turns.findById(turnId).orElse(null) ?: return
        if (turn.conversationId != id || turn.status != ChatTurnStatus.PENDING) return
        turn.status = ChatTurnStatus.FAILED
        turn.errorCode = code.takeIf { it.matches(Regex("[A-Z0-9_]{1,80}")) } ?: "CHAT_PROCESSING_FAILED"
        turn.completedAt = chatNow()
        if (room.activeTurnId == turnId) room.activeTurnId = null
        room.updatedAt = chatNow()
    }

    @Transactional
    fun delete(owner: Long, id: Long) {
        val room = lock(owner, id)
        turns.deleteInConversation(id)
        conversations.delete(room)
        conversations.flush()
    }

    @Transactional
    fun deleteAccount(owner: Long) {
        // UserService already holds this lock; the same ordering also protects direct callers.
        if (users.lockById(owner) == null) return
        turns.deleteOwned(owner)
        conversations.deleteOwned(owner)
    }
}

@RestController @RequestMapping("/api/chat/conversations")
class ChatConversationController(private val store: ChatConversationStore) {
    @ModelAttribute
    fun preventCaching(response: jakarta.servlet.http.HttpServletResponse) {
        response.setHeader("Cache-Control", "no-store")
    }

    @PostMapping @ResponseStatus(HttpStatus.CREATED)
    fun create(auth: Authentication, @RequestBody body: CreateChatConversationRequest) =
        mapOf("message" to "채팅방 생성 성공", "data" to store.create(auth.owner(), body))
    @GetMapping
    fun list(auth: Authentication, @RequestParam(defaultValue = "0") page: Int,
        @RequestParam(defaultValue = "20") size: Int) =
        mapOf("message" to "채팅방 목록 조회 성공", "data" to store.list(auth.owner(), page, size))
    @GetMapping("/{id}")
    fun get(auth: Authentication, @PathVariable id: Long) =
        mapOf("message" to "채팅방 조회 성공", "data" to store.get(auth.owner(), id))
    @GetMapping("/{id}/messages")
    fun messages(auth: Authentication, @PathVariable id: Long, @RequestParam(defaultValue = "0") afterId: Long,
        @RequestParam(defaultValue = "20") limit: Int) =
        mapOf("message" to "대화 조회 성공", "data" to store.messages(auth.owner(), id, afterId, limit))
    @GetMapping("/{id}/messages/{turnId}")
    fun message(auth: Authentication, @PathVariable id: Long, @PathVariable turnId: Long) =
        mapOf("message" to "메시지 상태 조회 성공", "data" to store.message(auth.owner(), id, turnId))
    @GetMapping("/{id}/messages/by-client-id/{clientMessageId}")
    fun messageByClientId(auth: Authentication, @PathVariable id: Long, @PathVariable clientMessageId: String) =
        mapOf("message" to "요청 ID로 메시지 조회 성공", "data" to store.messageByClientId(auth.owner(), id, clientMessageId))
    @DeleteMapping("/{id}") @ResponseStatus(HttpStatus.NO_CONTENT)
    fun delete(auth: Authentication, @PathVariable id: Long) = store.delete(auth.owner(), id)
    private fun Authentication.owner() = principal.toString().toLong()
}
