package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.auth.AuthSessionService
import org.jjikmuk.backend.domain.chat.dto.*
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.*
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.*
import org.mockito.Mockito.doAnswer
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc
import org.springframework.http.HttpStatus
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.ResultActions
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import org.springframework.transaction.support.TransactionSynchronizationManager
import tools.jackson.databind.json.JsonMapper
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlin.test.*

/** Real JWT + MVC + transactions, isolated H2, mocked AI. No real account/MySQL/AWS writes. */
@SpringBootTest(properties = ["spring.config.import=",
    "spring.datasource.url=jdbc:h2:mem:account-chat;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@AutoConfigureMockMvc @ActiveProfiles("test")
class AccountChatIntegrationTest @Autowired constructor(
    private val mvc: MockMvc, private val users: UserRepository, private val auth: AuthSessionService,
    private val userService: UserService, private val families: FamilyProfileService,
    private val store: ChatConversationStore, private val turns: ChatTurnRepository,
    private val rooms: ChatConversationRepository, private val products: ProductRepository,
    private val histories: HistoryRepository, private val jdbc: JdbcTemplate
) {
    @MockitoBean lateinit var ai: AiChatClient
    private val mapper = JsonMapper.builder().findAndAddModules().build()
    private val sent = CopyOnWriteArrayList<AiChatRequestDto>()
    private var answer: (AiChatRequestDto) -> String = { """{"answer":"저장된 설명","per_profile_results":[]}""" }
    private fun uuid() = UUID.randomUUID().toString()

    @BeforeEach fun setup() {
        sent.clear()
        answer = { """{"answer":"저장된 설명","per_profile_results":[]}""" }
        val placeholder = AiChatRequestDto(null, emptyList(), null, "", emptyList(), ChatAnalysisContext(
            contextId = "test", policyVersion = "test", selection = AnalysisSelectionResponse("none", false, false, emptyList()),
            effectiveConditions = null, productResolution = "NOT_PROVIDED", analysis = null, dataEvidence = null))
        doAnswer { call ->
            assertFalse(TransactionSynchronizationManager.isActualTransactionActive(), "AI must not hold a DB transaction")
            val request = call.getArgument<AiChatRequestDto>(0)
            sent += request
            answer(request)
        }.`when`(ai).ask(any<AiChatRequestDto>() ?: placeholder, anyLong(), anyBoolean())
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_feedback (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_logs (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
    }
    private fun account(role: UserRole = UserRole.USER, complete: Boolean = true): User {
        val unique = uuid().replace("-", "").take(12)
        return users.saveAndFlush(User(email = "$unique@example.invalid", nickname = "u$unique", password = "unused",
            role = role, profileCompleted = complete))
    }
    private fun token(user: User) = "Bearer ${auth.issue(user, false, "test").token}"
    private fun create(token: String, key: String = uuid(), title: String = "테스트 대화"): Long {
        val result = mvc.perform(post("/api/chat/conversations").header("Authorization", token)
            .contentType("application/json").content(mapper.writeValueAsString(mapOf("clientConversationId" to key, "title" to title))))
            .andExpect(status().isCreated).andExpect(header().string("Cache-Control", "no-store"))
            .andReturn().response.contentAsString
        return mapper.readTree(result).at("/data/id").asLong()
    }
    private fun send(token: String, room: Long, key: String = uuid(), message: String = "성분을 설명해줘",
        extra: Map<String, Any?> = emptyMap(), query: String = ""): ResultActions =
        mvc.perform(post("/api/chat$query").header("Authorization", token).contentType("application/json")
            .content(mapper.writeValueAsString(mapOf("conversationId" to room, "clientMessageId" to key, "message" to message) + extra)))
    private fun turnId(result: ResultActions) = result.andReturn().response.getHeader("X-Jjikmuk-Chat-Turn-Id")!!.toLong()

    @Test fun `chat is restored across sessions and other accounts including admins cannot read write or delete it`() {
        val a = account(); val a1 = token(a); val a2 = token(a); val room = create(a1)
        val turn = turnId(send(a1, room).andExpect(status().isOk).andExpect(jsonPath("$.answer").value("저장된 설명")))
        mvc.perform(get("/api/chat/conversations").header("Authorization", a2))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items[0].id").value(room))
        mvc.perform(get("/api/chat/conversations/$room/messages").header("Authorization", a2))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items[0].status").value("SUCCEEDED"))
            .andExpect(jsonPath("$.data.items[0].response.answer").value("저장된 설명"))
            .andExpect(jsonPath("$.data.items[0].response.per_profile_results").isArray)
        for (role in UserRole.entries) {
            val b = token(account(role))
            mvc.perform(get("/api/chat/conversations").header("Authorization", b))
                .andExpect(status().isOk).andExpect(jsonPath("$.data.items").isEmpty)
            for (path in listOf("/api/chat/conversations/$room", "/api/chat/conversations/$room/messages", "/api/chat/conversations/$room/messages/$turn"))
                mvc.perform(get(path).header("Authorization", b)).andExpect(status().isNotFound)
            send(b, room).andExpect(status().isNotFound)
            mvc.perform(delete("/api/chat/conversations/$room").header("Authorization", b)).andExpect(status().isNotFound)
        }
        assertEquals(1, sent.size)
        val anotherRoom = create(a1)
        mvc.perform(get("/api/chat/conversations/$anotherRoom/messages/$turn").header("Authorization", a1)).andExpect(status().isNotFound)
    }

    @Test fun `room creation and successful message retry are idempotent and changed payload is rejected`() {
        val a = account(); val first = token(a); val second = token(a); val key = uuid()
        val room = create(first, key)
        assertEquals(room, create(second, key))
        val messageKey = uuid()
        val one = send(first, room, messageKey).andExpect(status().isOk)
            .andExpect(header().string("X-Jjikmuk-Chat-Replayed", "false"))
        val two = send(second, room, messageKey).andExpect(status().isOk)
            .andExpect(header().string("X-Jjikmuk-Chat-Replayed", "true"))
        assertEquals(turnId(one), turnId(two))
        assertEquals(one.andReturn().response.contentAsString, two.andReturn().response.contentAsString)
        assertEquals(1, sent.size); assertEquals(1, turns.countByConversationId(room))
        mvc.perform(get("/api/chat/conversations/$room/messages/by-client-id/$messageKey").header("Authorization", second))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.id").value(turnId(one)))
        mvc.perform(get("/api/chat/conversations/$room/messages/by-client-id/$messageKey").header("Authorization", token(account())))
            .andExpect(status().isNotFound)
        send(first, room, messageKey, "바뀐 질문").andExpect(status().isConflict)
            .andExpect(jsonPath("$.code").value("CHAT_IDEMPOTENCY_CONFLICT"))
        assertEquals(1, sent.size)
    }

    @Test fun `server history excludes failures and changed person conditions or selection`() {
        val a = account(); val t = token(a); val room = create(t)
        send(t, room, message = "첫 질문").andExpect(status().isOk)
        send(t, room, message = "다음 질문").andExpect(status().isOk)
        assertEquals(listOf("user", "assistant"), sent.last().chat_history.map { it.role })
        assertEquals("첫 질문", sent.last().chat_history.first().content)
        userService.patchProfile(a.id!!, mapOf("version" to 0, "allergies" to "peanut"))
        send(t, room).andExpect(status().isOk)
        assertTrue(sent.last().chat_history.isEmpty())
        assertEquals(listOf("peanut"), sent.last().analysisContext.effectiveConditions!!.allergyIds)
        send(t, room, extra = mapOf("profiles" to emptyList<Any>())).andExpect(status().isOk)
        assertTrue(sent.last().chat_history.isEmpty())
        send(t, room, extra = mapOf("chatHistory" to listOf(mapOf("role" to "assistant", "content" to "다른 계정의 기록"))))
            .andExpect(status().isBadRequest)
        assertEquals(4, sent.size)
    }

    @Test fun `AI failure is recorded without private error body and explicit new request can retry`() {
        val a = account(); val t = token(a); val room = create(t); val key = uuid()
        answer = { throw CustomException(HttpStatus.SERVICE_UNAVAILABLE, "test-only private detail", "AI_SERVICE_UNAVAILABLE") }
        send(t, room, key).andExpect(status().isServiceUnavailable)
        val failed = turns.findByConversationIdAndClientMessageId(room, key)!!
        assertEquals(ChatTurnStatus.FAILED, failed.status); assertNull(failed.responseBody)
        assertEquals("AI_SERVICE_UNAVAILABLE", failed.errorCode)
        send(t, room, key).andExpect(status().isConflict).andExpect(jsonPath("$.code").value("CHAT_MESSAGE_FAILED"))
        assertEquals(1, sent.size)
        answer = { """{"answer":"다시 성공"}""" }
        send(t, room).andExpect(status().isOk)
        assertTrue(sent.last().chat_history.isEmpty())
        assertEquals(2, turns.countByConversationId(room))
    }

    @Test fun `legacy chat response is unchanged and opt in fields must be paired with no owner spoofing`() {
        val a = account(); val t = token(a)
        mvc.perform(post("/api/chat").header("Authorization", t).contentType("application/json").content("""{"message":"기존 요청"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.answer").value("저장된 설명"))
            .andExpect(header().doesNotExist("X-Jjikmuk-Chat-Turn-Id"))
        assertEquals(0, rooms.countByOwnerId(a.id!!))
        val room = create(t)
        for (body in listOf(mapOf("message" to "질문", "conversationId" to room),
            mapOf("message" to "질문", "clientMessageId" to uuid()))) {
            mvc.perform(post("/api/chat").header("Authorization", t).contentType("application/json").content(mapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest)
        }
        send(t, room, extra = mapOf("userId" to account().id)).andExpect(status().isForbidden)
        assertEquals(0, turns.countByConversationId(room))
        assertEquals(1, sent.size)
    }

    @Test fun `same room serializes AI calls and no transaction spans the external call`() {
        val a = account(); val t = token(a); val room = create(t); val key = uuid()
        val entered = CountDownLatch(1); val release = CountDownLatch(1); val executor = Executors.newSingleThreadExecutor()
        answer = { entered.countDown(); check(release.await(10, TimeUnit.SECONDS)); """{"answer":"완료"}""" }
        try {
            val first = executor.submit<Int> { send(t, room, key).andReturn().response.status }
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            send(t, room, key).andExpect(status().isConflict).andExpect(jsonPath("$.code").value("CHAT_REQUEST_IN_PROGRESS"))
                .andExpect(header().string("Retry-After", "2"))
            send(t, room).andExpect(status().isConflict).andExpect(jsonPath("$.code").value("CHAT_CONVERSATION_BUSY"))
            assertEquals(1, turns.countByConversationId(room))
            release.countDown(); assertEquals(200, first.get(10, TimeUnit.SECONDS)); assertEquals(1, sent.size)
        } finally { release.countDown(); executor.shutdownNow() }
    }

    @Test fun `deleting a room while AI runs prevents late response from resurrecting it`() {
        val a = account(); val t = token(a); val room = create(t)
        val entered = CountDownLatch(1); val release = CountDownLatch(1); val executor = Executors.newSingleThreadExecutor()
        answer = { entered.countDown(); check(release.await(10, TimeUnit.SECONDS)); """{"answer":"늦은 응답"}""" }
        try {
            val first = executor.submit<Int> { send(t, room).andReturn().response.status }
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            mvc.perform(delete("/api/chat/conversations/$room").header("Authorization", t)).andExpect(status().isNoContent)
            release.countDown(); assertEquals(404, first.get(10, TimeUnit.SECONDS))
            assertEquals(0, turns.countByConversationId(room)); assertFalse(rooms.existsById(room))
        } finally { release.countDown(); executor.shutdownNow() }
    }

    @Test fun `expired pending request is reported failed and a new request releases stale room lock`() {
        val a = account(); val t = token(a); val room = create(t)
        val reservation = store.reserve(a.id!!, room, uuid(), "a".repeat(64), "b".repeat(64), "중단된 질문", null)
        jdbc.update("UPDATE chat_turns SET expires_at = ? WHERE id = ?", chatNow().minusMinutes(1), reservation.id)
        mvc.perform(get("/api/chat/conversations/$room/messages/${reservation.id}").header("Authorization", t))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.status").value("FAILED"))
            .andExpect(jsonPath("$.data.errorCode").value("CHAT_REQUEST_INTERRUPTED"))
        send(t, room).andExpect(status().isOk)
        assertEquals(ChatTurnStatus.FAILED, turns.findById(reservation.id).orElseThrow().status)
        assertTrue(sent.last().chat_history.isEmpty())
    }

    @Test fun `message pagination is bounded ordered and pending rows can be polled independently`() {
        val a = account(); val t = token(a); val room = create(t)
        val ids = (1..3).map { turnId(send(t, room, message = "질문$it").andExpect(status().isOk)) }
        mvc.perform(get("/api/chat/conversations/$room/messages?limit=2").header("Authorization", t))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items.length()").value(2))
            .andExpect(jsonPath("$.data.nextAfterId").value(ids[1])).andExpect(jsonPath("$.data.hasNext").value(true))
        mvc.perform(get("/api/chat/conversations/$room/messages?afterId=${ids[1]}&limit=2").header("Authorization", t))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items[0].id").value(ids[2]))
            .andExpect(jsonPath("$.data.hasNext").value(false))
        for (query in listOf("limit=0", "limit=51", "afterId=-1"))
            mvc.perform(get("/api/chat/conversations/$room/messages?$query").header("Authorization", t)).andExpect(status().isBadRequest)
        mvc.perform(get("/api/chat/conversations?size=51").header("Authorization", t)).andExpect(status().isBadRequest)
    }

    @Test fun `anonymous and incomplete accounts cannot use stored chat and creation rejects forged owner`() {
        mvc.perform(get("/api/chat/conversations")).andExpect(status().isUnauthorized)
        mvc.perform(get("/api/chat/conversations").header("Authorization", token(account(complete = false))))
            .andExpect(status().isForbidden).andExpect(jsonPath("$.code").value("PROFILE_INCOMPLETE"))
        val t = token(account())
        mvc.perform(post("/api/chat/conversations").header("Authorization", t).contentType("application/json")
            .content("""{"clientConversationId":"${uuid()}","ownerId":1}"""))
            .andExpect(status().isBadRequest)
        mvc.perform(post("/api/chat/conversations").header("Authorization", t).contentType("application/json")
            .content("""{"clientConversationId":"not-uuid"}"""))
            .andExpect(status().isBadRequest)
        assertTrue(sent.isEmpty())
    }

    @Test fun `account deletion removes only owned conversations and messages`() {
        val a = account(); val b = account(); val ta = token(a); val tb = token(b)
        val ar = create(ta); val br = create(tb)
        send(ta, ar).andExpect(status().isOk); send(tb, br).andExpect(status().isOk)
        userService.deleteUser(a.id!!)
        assertEquals(0, rooms.countByOwnerId(a.id!!)); assertEquals(0, turns.countByConversationId(ar))
        mvc.perform(get("/api/chat/conversations/$br/messages").header("Authorization", tb))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items.length()").value(1))
    }

    @Test fun `account deletion during an AI call cannot restore messages with a stale owner`() {
        val a = account(); val t = token(a); val room = create(t)
        val entered = CountDownLatch(1); val release = CountDownLatch(1); val executor = Executors.newSingleThreadExecutor()
        answer = { entered.countDown(); check(release.await(10, TimeUnit.SECONDS)); """{"answer":"늦은 응답"}""" }
        try {
            val first = executor.submit<Int> { send(t, room).andReturn().response.status }
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            userService.deleteUser(a.id!!)
            release.countDown(); assertEquals(404, first.get(10, TimeUnit.SECONDS))
            assertFalse(users.existsById(a.id!!)); assertFalse(rooms.existsById(room))
            assertEquals(0, turns.countByConversationId(room))
        } finally { release.countDown(); executor.shutdownNow() }
    }

    @Test fun `stored history stays within message and character budget and invalid responses are not saved`() {
        val a = account(); val t = token(a); val room = create(t)
        answer = { mapper.writeValueAsString(mapOf("answer" to "가".repeat(9000))) }
        repeat(6) { send(t, room, message = "나".repeat(4000)).andExpect(status().isOk) }
        assertTrue(sent.last().chat_history.size <= 20)
        assertTrue(sent.last().chat_history.sumOf { it.content.length } <= 40000)
        val key = uuid()
        answer = { "[]" }
        send(t, room, key).andExpect(status().isBadGateway)
        assertNull(turns.findByConversationIdAndClientMessageId(room, key)!!.responseBody)
        val largeKey = uuid()
        answer = { mapper.writeValueAsString(mapOf("answer" to "가".repeat(400000))) }
        send(t, room, largeKey).andExpect(status().isBadGateway)
        assertEquals(ChatTurnStatus.FAILED, turns.findByConversationIdAndClientMessageId(room, largeKey)!!.status)
    }

    @Test fun `allergy preferences are separated by JWT and restored after account switch or new session`() {
        val a = account(); val b = account(); val ta = token(a); val tb = token(b)
        for ((t, allergy) in listOf(ta to "peanut", tb to "milk"))
            mvc.perform(patch("/api/users/me").header("Authorization", t).contentType("application/json")
                .content("""{"version":0,"allergies":"$allergy"}"""))
                .andExpect(status().isOk).andExpect(jsonPath("$.data.allergies").value(allergy))
        for ((t, allergy) in listOf(ta to "peanut", tb to "milk", token(a) to "peanut"))
            mvc.perform(get("/api/users/me").header("Authorization", t)).andExpect(status().isOk)
                .andExpect(jsonPath("$.data.allergies").value(allergy))
        mvc.perform(get("/api/users/${a.id}").header("Authorization", tb)).andExpect(status().isForbidden)
        mvc.perform(put("/api/users/${a.id}").header("Authorization", tb).contentType("application/json")
            .content("""{"nickname":"잘못된수정","allergies":"soy"}"""))
            .andExpect(status().isForbidden)
        mvc.perform(patch("/api/users/me").header("Authorization", tb).contentType("application/json").content("""{"version":1,"allergies":null}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.allergies").isEmpty)
        assertEquals("peanut", users.findById(a.id!!).orElseThrow().allergies)
    }

    @Test fun `family data lists and mutations are owned by account across sessions`() {
        val a = account(); val b = account(); val ta = token(a); val tb = token(b)
        val family = families.create(a.id!!, mapOf("nickname" to "가족", "allergies" to "soy", "emoji" to "👨", "relation" to "아버지"))
        mvc.perform(get("/api/users/me/family-profiles").header("Authorization", token(a)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data[0].allergies").value("soy"))
        mvc.perform(get("/api/users/me/family-profiles").header("Authorization", tb))
            .andExpect(status().isOk).andExpect(jsonPath("$.data").isEmpty)
        mvc.perform(patch("/api/users/me/family-profiles/${family.id}").header("Authorization", tb).contentType("application/json")
            .content("""{"version":0,"allergies":"milk"}"""))
            .andExpect(status().isNotFound)
        mvc.perform(delete("/api/users/me/family-profiles/${family.id}?version=0").header("Authorization", tb)).andExpect(status().isNotFound)
        val room = create(ta)
        send(ta, room, query = "?analysisMode=selected&familyProfileIds=${family.id}").andExpect(status().isOk)
        assertEquals(listOf("soy"), sent.last().analysisContext.effectiveConditions!!.allergyIds)
        send(tb, create(tb), query = "?analysisMode=selected&familyProfileIds=${family.id}").andExpect(status().isNotFound)
        assertEquals(1, sent.size)
    }

    @Test fun `recent views and favorites do not leak across accounts and persist across sessions`() {
        val a = account(); val b = account(); val ta = token(a); val tb = token(b)
        val pid = productIds.incrementAndGet()
        val item = products.saveAndFlush(Product(barcode = "ACCOUNT-$pid", productId = pid, productName = "격리 상품"))
        mvc.perform(get("/api/products/id/$pid?analysisMode=none").header("Authorization", ta)).andExpect(status().isOk)
        mvc.perform(put("/api/users/me/favorites/$pid").header("Authorization", ta)).andExpect(status().isOk)
        mvc.perform(get("/api/histories/user/${a.id}?view=recent").header("Authorization", token(a)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items[0].productId").value(pid))
        mvc.perform(get("/api/histories/user/${a.id}?view=recent").header("Authorization", tb)).andExpect(status().isForbidden)
        mvc.perform(get("/api/histories/user/${b.id}?view=recent").header("Authorization", tb))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items").isEmpty)
        mvc.perform(get("/api/users/me/favorites").header("Authorization", token(a)))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items[0].productId").value(pid))
        mvc.perform(get("/api/users/me/favorites").header("Authorization", tb))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items").isEmpty)
        mvc.perform(delete("/api/users/me/favorites/$pid").header("Authorization", tb)).andExpect(status().isOk)
        mvc.perform(get("/api/users/me/favorites/$pid").header("Authorization", ta))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.isFavorite").value(true))
        assertTrue(histories.findByUserIdOrderByCreatedAtDesc(b.id!!).isEmpty())
        assertEquals(item.barcode, histories.findByUserIdOrderByCreatedAtDesc(a.id!!).first().barcode)
    }

    companion object { private val productIds = AtomicLong(98_000_000_000L) }
}
