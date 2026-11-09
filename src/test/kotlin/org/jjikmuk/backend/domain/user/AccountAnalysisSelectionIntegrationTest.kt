package org.jjikmuk.backend.domain.user

import org.jjikmuk.backend.domain.auth.AuthSessionService
import org.jjikmuk.backend.domain.chat.*
import org.jjikmuk.backend.domain.chat.dto.*
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.product.*
import org.jjikmuk.backend.domain.recommendation.ProductNeighborSet
import org.jjikmuk.backend.domain.recommendation.ProductNeighborSetRepository
import org.junit.jupiter.api.Test
import org.mockito.Mockito.doAnswer
import org.mockito.ArgumentMatchers.*
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import tools.jackson.databind.json.JsonMapper
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlin.test.*

/** Real JWT + independent committed transactions. H2 only; Google/AI/MySQL/AWS are not contacted. */
@SpringBootTest(properties = ["spring.config.import=",
    "spring.datasource.url=jdbc:h2:mem:account-analysis-selection;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@AutoConfigureMockMvc @ActiveProfiles("test")
class AccountAnalysisSelectionIntegrationTest @Autowired constructor(
    private val mvc: MockMvc, private val users: UserRepository, private val sessions: AuthSessionService,
    private val families: FamilyProfileService, private val settings: AccountAnalysisSelectionService,
    private val settingsRepository: AccountAnalysisSelectionRepository, private val resolver: AnalysisSelectionService,
    private val chatProfiles: ChatProfileResolver, private val products: ProductRepository,
    private val histories: HistoryRepository, private val userService: UserService, private val jdbc: JdbcTemplate,
    private val neighbors: ProductNeighborSetRepository
) {
    @MockitoBean lateinit var ai: AiChatClient
    private val mapper = JsonMapper.builder().findAndAddModules().build()
    private val path = "/api/users/me/analysis-selection"
    private fun account(complete: Boolean = true, role: UserRole = UserRole.USER): User {
        val key = UUID.randomUUID().toString().replace("-", "").take(12)
        return users.saveAndFlush(User(email = "$key@example.invalid", nickname = "u$key", password = "unused",
            allergies = "milk", profileCompleted = complete, role = role))
    }
    private fun token(user: User) = "Bearer ${sessions.issue(user, false, "test").token}"
    private fun read(auth: String) = mvc.perform(get(path).header("Authorization", auth))
    private fun write(auth: String, body: Map<String, Any?>) = mvc.perform(put(path).header("Authorization", auth)
        .contentType("application/json").content(mapper.writeValueAsString(body)))
    private fun body(version: Long = 0, self: Boolean = false, ids: List<Long> = emptyList()) =
        mapOf("version" to version, "includeSelf" to self, "familyProfileIds" to ids)
    private fun family(user: User, allergy: String = "peanut") =
        families.create(user.id!!, mapOf("nickname" to "가족", "allergies" to allergy, "emoji" to "👩", "relation" to "보호자"))
    private fun product(): Product {
        val id = ids.incrementAndGet()
        return products.saveAndFlush(Product(barcode = "SELECTION-$id", productId = id, productName = "테스트$id",
            manufacturer = "테스트", totalWeight = "100g", rawMaterials = "땅콩, 쌀, 소금", allergy = "땅콩",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL))
    }

    @Test fun `login reads and existing family rows never import or enable families`() {
        val user = account(); val member = family(user); val auth = token(user)
        repeat(2) {
            read(auth).andExpect(status().isOk).andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.data.includeSelf").value(true)).andExpect(jsonPath("$.data.mode").value("self"))
                .andExpect(jsonPath("$.data.familyProfileIds").isEmpty).andExpect(jsonPath("$.data.version").value(0))
                .andExpect(jsonPath("$.data.configured").value(false))
        }
        assertFalse(settingsRepository.existsById(user.id!!))
        assertEquals(listOf(member.id), families.list(user.id!!).map { it.id })
        assertEquals(listOf("self"), resolver.resolve(user.id, null, null, null).subjects.map { it.kind })
    }

    @Test fun `two devices share selected ids and new reviewed families stay OFF`() {
        val user = account(); val a = token(user); val b = token(user); val member = family(user)
        write(a, body(ids = listOf(member.id, member.id))).andExpect(status().isOk)
            .andExpect(jsonPath("$.data.version").value(1)).andExpect(jsonPath("$.data.configured").value(true))
        family(user, "soy") // Manually confirmed create, not automatic toggle import.
        read(b).andExpect(status().isOk).andExpect(jsonPath("$.data.includeSelf").value(false))
            .andExpect(jsonPath("$.data.familyProfileIds[0]").value(member.id))
            .andExpect(jsonPath("$.data.familyProfileIds.length()").value(1))
        assertEquals("peanut", resolver.resolve(user.id, null, null, null).profile.allergies)
        write(b, body(1, true, listOf(member.id))).andExpect(status().isOk)
        assertEquals(setOf("milk", "peanut"), resolver.resolve(user.id, null, null, null).profile.allergies!!.split(',').toSet())
        assertEquals(0, users.findById(user.id!!).orElseThrow().profileVersion)
    }

    @Test fun `stale devices cannot overwrite and explicit reload permits another edit`() {
        val user = account(); val a = token(user); val b = token(user)
        write(a, body()).andExpect(status().isOk)
        write(b, body(self = true)).andExpect(status().isConflict)
            .andExpect(jsonPath("$.code").value("ANALYSIS_SELECTION_VERSION_CONFLICT"))
            .andExpect(jsonPath("$.field").value("version"))
        assertEquals("none", settings.get(user.id!!).mode)
        read(b).andExpect(jsonPath("$.data.version").value(1))
        write(b, body(1, true)).andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(2))
        // Even an accepted identical save advances the revision; a timed-out PUT must be re-read.
        write(b, body(2, true)).andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(3))
    }

    @Test fun `simultaneous first saves have one winner even without a preexisting settings row`() {
        val user = account(); val credentials = listOf(token(user), token(user))
        val ready = CountDownLatch(2); val start = CountDownLatch(1); val pool = Executors.newFixedThreadPool(2)
        try {
            val futures = credentials.mapIndexed { index, auth -> pool.submit<Pair<Int, Boolean>> {
                ready.countDown(); check(start.await(10, TimeUnit.SECONDS))
                write(auth, body(self = index == 0)).andReturn().response.status to (index == 0)
            } }
            assertTrue(ready.await(10, TimeUnit.SECONDS)); start.countDown()
            val results = futures.map { it.get(20, TimeUnit.SECONDS) }
            assertEquals(listOf(200, 409), results.map { it.first }.sorted())
            assertEquals(results.single { it.first == 200 }.second, settings.get(user.id!!).includeSelf)
            assertEquals(1, settings.get(user.id!!).version)
        } finally { start.countDown(); pool.shutdownNow() }
    }

    @Test fun `selection is JWT owned and other accounts including admin cannot select foreign families`() {
        val a = account(); val member = family(a)
        for (role in UserRole.entries) {
            val b = account(role = role); val auth = token(b)
            write(auth, body(ids = listOf(member.id))).andExpect(status().isNotFound)
                .andExpect(jsonPath("$.code").value("FAMILY_NOT_FOUND"))
            write(auth, body() + ("ownerId" to a.id)).andExpect(status().isBadRequest)
            assertFalse(settingsRepository.existsById(b.id!!))
            read(auth).andExpect(jsonPath("$.data.mode").value("self"))
        }
        write(token(a), body(ids = listOf(member.id))).andExpect(status().isOk)
        val b = account()
        assertTrue(settings.get(b.id!!).familyProfileIds.isEmpty())
    }

    @Test fun `anonymous and incomplete accounts cannot read or save choices`() {
        mvc.perform(get(path)).andExpect(status().isUnauthorized)
        mvc.perform(put(path).contentType("application/json").content(mapper.writeValueAsString(body())))
            .andExpect(status().isUnauthorized)
        val auth = token(account(complete = false))
        read(auth).andExpect(status().isForbidden).andExpect(jsonPath("$.code").value("PROFILE_INCOMPLETE"))
        write(auth, body()).andExpect(status().isForbidden)
    }

    @Test fun `strict complete payload validation rejects local snapshots coercions and missing fields atomically`() {
        val user = account(); val auth = token(user)
        val invalid = listOf(
            body() - "version", body() - "includeSelf", body() - "familyProfileIds",
            body() + ("version" to "0"), body() + ("version" to 0.0), body() + ("version" to -1),
            body() + ("version" to null), body() + ("includeSelf" to "false"), body() + ("includeSelf" to null),
            body() + ("familyProfileIds" to null), body() + ("familyProfileIds" to "1"),
            body(ids = listOf(0)), body(ids = listOf(-1)), body(ids = (1L..21L).toList()),
            body() + ("familyProfileIds" to listOf(1.0)), body() + ("familyProfileIds" to listOf("1")),
            body() + ("familyProfileIds" to listOf(null)), body() + ("familyProfileIds" to listOf(true)),
            body() + ("familyProfileIds" to listOf(java.math.BigInteger("9223372036854775808"))),
            body() + ("profiles" to listOf(mapOf("nickname" to "로컬가족", "allergies" to "milk"))),
            body() + ("isActive" to true))
        for (payload in invalid) write(auth, payload).andExpect(status().isBadRequest)
            .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
        write(auth, body(ids = listOf(Long.MAX_VALUE))).andExpect(status().isNotFound)
        assertFalse(settingsRepository.existsById(user.id!!)); assertTrue(families.list(user.id!!).isEmpty())
    }

    @Test fun `explicit request overrides never write saved selection and malformed overrides never silently fall back`() {
        val user = account(); val member = family(user)
        settings.replace(user.id!!, body(ids = listOf(member.id)))
        assertEquals("self", resolver.resolve(user.id, "self", null, null).selection.mode)
        assertFalse(resolver.resolve(user.id, "none", null, null).applied)
        assertEquals("selected", settings.get(user.id!!).mode); assertEquals(1, settings.get(user.id!!).version)
        val auth = token(user); val item = product()
        for (query in listOf("?includeSelf=true", "?familyProfileIds=${member.id}", "?analysisMode=invalid"))
            mvc.perform(get("/api/products/${item.barcode}$query").header("Authorization", auth))
                .andExpect(status().isBadRequest).andExpect(jsonPath("$.code").value("ANALYSIS_SELECTION_INVALID"))
        assertFalse(resolver.resolve(null, null, null, null).applied)
    }

    @Test fun `all OFF persists and product and recommendation APIs do not label it PASS`() {
        val user = account(); val auth = token(user); val item = product()
        val candidate = product()
        neighbors.saveAndFlush(ProductNeighborSet(item.barcode, "test", 1, "${candidate.barcode}|0.9"))
        write(auth, body()).andExpect(status().isOk).andExpect(jsonPath("$.data.mode").value("none"))
        mvc.perform(get("/api/products/${item.barcode}").header("Authorization", auth))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.analysis.status").value("NOT_EVALUATED"))
            .andExpect(jsonPath("$.data.analysis.selection.mode").value("none"))
        mvc.perform(get("/api/products/safe-recommendations").header("Authorization", auth))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.analysisSelection.mode").value("none"))
        mvc.perform(get("/api/recommendations/products/${item.barcode}").header("Authorization", auth))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.analysisSelection.mode").value("none"))
        assertFalse(settings.get(user.id!!).includeSelf)
        assertFalse(histories.findByUserIdOrderByCreatedAtDesc(user.id!!).single().personalizationAllowed)
    }

    @Test fun `saved family restrictions are used for product detail and API chat with current server facts`() {
        val user = account(); val auth = token(user); val member = family(user); val item = product()
        settings.replace(user.id!!, body(ids = listOf(member.id)))
        val detail = mvc.perform(get("/api/products/${item.barcode}").header("Authorization", auth))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.analysis.status").value("DANGER"))
            .andExpect(jsonPath("$.data.analysis.selection.familyProfileIds[0]").value(member.id))
            .andReturn().response.contentAsString
        val sent = mutableListOf<AiChatRequestDto>()
        val placeholder = AiChatRequestDto(null, emptyList(), null, "", emptyList(), ChatAnalysisContext(
            "test", policyVersion = "test", selection = AnalysisSelectionResponse("none", false, false, emptyList()),
            effectiveConditions = null, productResolution = "NOT_PROVIDED", analysis = null, dataEvidence = null))
        doAnswer { invocation -> sent += invocation.getArgument<AiChatRequestDto>(0); """{"answer":"테스트"}""" }
            .`when`(ai).ask(any<AiChatRequestDto>() ?: placeholder, anyLong(), anyBoolean())
        mvc.perform(post("/api/chat").header("Authorization", auth).contentType("application/json")
            .content("""{"message":"표시 정보를 알려줘","barcode":"${item.barcode}"}"""))
            .andExpect(status().isOk)
        val payload = sent.single()
        assertEquals(listOf("peanut"), payload.analysisContext.effectiveConditions!!.allergyIds)
        assertEquals("SERVER", payload.analysisContext.profileSource)
        assertEquals(mapper.readTree(detail)["data"]["analysis"],
            mapper.readTree(mapper.writeValueAsString(payload.analysisContext.analysis)))
        // The selection stores only IDs; later family edits must be reflected without saving toggles again.
        families.patch(user.id!!, member.id, mapOf("version" to member.version, "allergies" to "soy"))
        assertEquals("soy", resolver.resolve(user.id, null, null, null).profile.allergies)
        assertEquals(1, settings.get(user.id!!).version)
    }

    @Test fun `legacy chat snapshots remain request only and do not import families or toggle settings`() {
        val user = account(); val member = family(user)
        settings.replace(user.id!!, body(ids = listOf(member.id)))
        val request = ChatRequestDto(message = "test", profiles = listOf(
            ChatProfileInput(nickname = "로컬가족", allergies = "soy", isActive = true)))
        val resolved = chatProfiles.resolve(request, user.id!!, null, null, null)
        assertEquals("CLIENT_REQUEST", resolved.source); assertEquals("soy", resolved.effective.profile.allergies)
        assertEquals(1, families.list(user.id!!).size); assertEquals(listOf(member.id), settings.get(user.id!!).familyProfileIds)
        val off = chatProfiles.resolve(ChatRequestDto(message = "test", profiles = emptyList()), user.id!!, null, null, null)
        assertFalse(off.effective.applied); assertEquals(1, settings.get(user.id!!).version)
    }

    @Test fun `deleting selected family prunes selection increments revision and never enables self`() {
        val user = account(); val auth = token(user); val member = family(user); val unused = family(user, "soy")
        settings.replace(user.id!!, body(ids = listOf(member.id)))
        families.delete(user.id!!, unused.id, unused.version)
        assertEquals(1, settings.get(user.id!!).version)
        mvc.perform(delete("/api/users/me/family-profiles/${member.id}?version=${member.version}").header("Authorization", auth))
            .andExpect(status().isOk)
        read(auth).andExpect(jsonPath("$.data.version").value(2)).andExpect(jsonPath("$.data.mode").value("none"))
            .andExpect(jsonPath("$.data.familyProfileIds").isEmpty)
        write(auth, body(1, false, listOf(member.id))).andExpect(status().isConflict)
        write(auth, body(2, false, listOf(member.id))).andExpect(status().isNotFound)
        assertFalse(resolver.resolve(user.id, null, null, null).applied)
    }

    @Test fun `failed family deletion preserves both family and saved toggles`() {
        val user = account(); val member = family(user); val auth = token(user)
        settings.replace(user.id!!, body(ids = listOf(member.id)))
        mvc.perform(delete("/api/users/me/family-profiles/${member.id}?version=99").header("Authorization", auth))
            .andExpect(status().isConflict)
        assertEquals(listOf(member.id), settings.get(user.id!!).familyProfileIds)
        assertEquals(1, settings.get(user.id!!).version); assertEquals(1, families.list(user.id!!).size)
    }

    @Test fun `concurrent family deletion and selection save cannot retain a deleted family`() {
        val user = account(); val member = family(user); val auth = token(user)
        val start = CountDownLatch(1); val pool = Executors.newFixedThreadPool(2)
        try {
            val saving = pool.submit<Int> { check(start.await(10, TimeUnit.SECONDS));
                write(auth, body(ids = listOf(member.id))).andReturn().response.status }
            val removing = pool.submit<Int> { check(start.await(10, TimeUnit.SECONDS));
                mvc.perform(delete("/api/users/me/family-profiles/${member.id}?version=0").header("Authorization", auth))
                    .andReturn().response.status }
            start.countDown()
            assertEquals(200, removing.get(20, TimeUnit.SECONDS)); assertTrue(saving.get(20, TimeUnit.SECONDS) in setOf(200, 404))
            assertTrue(settings.get(user.id!!).familyProfileIds.isEmpty()); assertTrue(families.list(user.id!!).isEmpty())
        } finally { start.countDown(); pool.shutdownNow() }
    }

    @Test fun `account deletion removes selection and does not touch another account`() {
        val a = account(); val b = account(); val af = family(a); val bf = family(b)
        settings.replace(a.id!!, body(ids = listOf(af.id))); settings.replace(b.id!!, body(ids = listOf(bf.id)))
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_feedback (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_logs (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
        userService.deleteUser(a.id!!)
        assertFalse(settingsRepository.existsById(a.id!!)); assertFalse(users.existsById(a.id!!))
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM account_analysis_selection_families WHERE owner_id=?", Int::class.java, a.id))
        assertEquals(listOf(bf.id), settings.get(b.id!!).familyProfileIds)
    }

    companion object { private val ids = AtomicLong(91_000_000_000L) }
}
