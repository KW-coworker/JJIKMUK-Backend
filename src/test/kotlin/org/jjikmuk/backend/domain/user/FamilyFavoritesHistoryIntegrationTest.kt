package org.jjikmuk.backend.domain.user

import jakarta.servlet.Filter
import org.jjikmuk.backend.domain.auth.AuthService
import org.jjikmuk.backend.domain.auth.LoginRequest
import org.jjikmuk.backend.domain.history.*
import org.jjikmuk.backend.domain.product.*
import org.jjikmuk.backend.domain.recommendation.*
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import org.springframework.test.web.servlet.setup.DefaultMockMvcBuilder
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import org.springframework.web.context.WebApplicationContext
import tools.jackson.databind.ObjectMapper
import java.time.LocalDateTime
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlin.test.*

/** Real HTTP security + real transactions, isolated H2 only; no Google/mail/MySQL/AWS. */
@SpringBootTest(properties = [
    "spring.datasource.url=jdbc:h2:mem:family-favorites-history;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false",
    "spring.config.import="
])
@ActiveProfiles("test")
class FamilyFavoritesHistoryIntegrationTest @Autowired constructor(
    private val context: WebApplicationContext,
    private val users: UserRepository,
    private val userService: UserService,
    private val families: FamilyProfileService,
    private val favorites: ProductFavoriteService,
    private val favoriteRepository: ProductFavoriteRepository,
    private val histories: HistoryRepository,
    private val historyService: HistoryService,
    private val products: ProductRepository,
    private val auth: AuthService,
    private val encoder: BCryptPasswordEncoder,
    private val mapper: ObjectMapper,
    private val recommendations: RecommendationService,
    private val neighbors: ProductNeighborSetRepository,
    private val jdbc: JdbcTemplate
) {
    private lateinit var mvc: MockMvc
    @BeforeEach fun setup() {
        mvc = MockMvcBuilders.webAppContextSetup(context)
            .addFilters<DefaultMockMvcBuilder>(context.getBean("springSecurityFilterChain", Filter::class.java)).build()
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_feedback (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
        jdbc.execute("CREATE TABLE IF NOT EXISTS product_recommendation_logs (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT)")
    }
    private fun user(complete: Boolean = true, role: UserRole = UserRole.USER): User {
        val unique = UUID.randomUUID().toString().replace("-", "").take(12)
        return users.saveAndFlush(User(email = "$unique@example.com", nickname = "u$unique",
            password = encoder.encode("Example123!")!!, profileCompleted = complete, role = role))
    }
    private fun bearer(user: User) = "Bearer ${auth.login(LoginRequest(user.email, "Example123!")).token}"
    private fun product(): Product {
        val id = ids.incrementAndGet()
        return products.saveAndFlush(Product(barcode = "MY-$id", productId = id, productName = "상품$id",
            manufacturer = "테스트", totalWeight = "100g", rawMaterials = "쌀, 소금",
            allergyEvidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL))
    }
    private fun events(owner: User) = histories.findByUserIdOrderByCreatedAtDesc(owner.id!!)

    @Test fun `family metadata persists across sessions with omission clear and optimistic locking`() {
        val owner = user(); val firstDevice = bearer(owner); val secondDevice = bearer(owner)
        val created = mvc.perform(post("/api/users/me/family-profiles").header("Authorization", firstDevice)
            .contentType(MediaType.APPLICATION_JSON)
            .content("""{"nickname":"엄마","relation":"어머니","emoji":"👩🏽‍🦱","allergies":"peanut"}"""))
            .andExpect(status().isCreated).andExpect(jsonPath("$.data.relation").value("어머니"))
            .andExpect(jsonPath("$.data.relationship").doesNotExist())
            .andExpect(jsonPath("$.data.emoji").value("👩🏽‍🦱")).andReturn()
        val data = mapper.readTree(created.response.contentAsString).get("data")
        val id = data.get("id").asLong(); val version = data.get("version").asLong()
        mvc.perform(get("/api/users/me/family-profiles").header("Authorization", secondDevice))
            .andExpect(status().isOk).andExpect(jsonPath("$.data[0].emoji").value("👩🏽‍🦱"))
            .andExpect(jsonPath("$.data[0].relation").value("어머니"))
        mvc.perform(get("/api/users/me/family-profiles/$id").header("Authorization", secondDevice))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.relation").value("어머니"))
        mvc.perform(patch("/api/users/me/family-profiles/$id").header("Authorization", secondDevice)
            .contentType(MediaType.APPLICATION_JSON).content("""{"version":$version,"relation":"보호자"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.emoji").value("👩🏽‍🦱"))
            .andExpect(jsonPath("$.data.relation").value("보호자"))
            .andExpect(jsonPath("$.data.allergies").value("peanut"))
        mvc.perform(patch("/api/users/me/family-profiles/$id").header("Authorization", firstDevice)
            .contentType(MediaType.APPLICATION_JSON).content("""{"version":$version,"emoji":"👨"}"""))
            .andExpect(status().isConflict).andExpect(jsonPath("$.code").value("PROFILE_VERSION_CONFLICT"))
        val current = families.owned(owner.id!!, id)
        mvc.perform(patch("/api/users/me/family-profiles/$id").header("Authorization", firstDevice)
            .contentType(MediaType.APPLICATION_JSON).content("""{"version":${current.version},"relation":null,"emoji":" "}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.relation").isEmpty)
            .andExpect(jsonPath("$.data.emoji").isEmpty)
        assertEquals("peanut", families.owned(owner.id!!, id).allergies)
    }

    @Test fun `family metadata validation is scoped to family and ownership remains enforced`() {
        val owner = user(); val token = bearer(owner); val other = bearer(user())
        val family = families.create(owner.id!!, mapOf("nickname" to "가족"))
        assertNull(family.relation); assertNull(family.emoji)
        for ((field, value) in listOf("relation" to 5, "emoji" to listOf("👩"),
            "emoji" to "👨".repeat(33), "relation" to "엄마\n아빠")) {
            mvc.perform(patch("/api/users/me/family-profiles/${family.id}").header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(mapOf("version" to family.version, field to value))))
                .andExpect(status().isBadRequest).andExpect(jsonPath("$.field").value(field))
        }
        mvc.perform(get("/api/users/me/family-profiles/${family.id}").header("Authorization", other))
            .andExpect(status().isNotFound)
        mvc.perform(patch("/api/users/me/family-profiles/${family.id}").header("Authorization", other)
            .contentType(MediaType.APPLICATION_JSON).content("""{"version":0,"relation":"친구"}"""))
            .andExpect(status().isNotFound)
        mvc.perform(patch("/api/users/me").header("Authorization", token)
            .contentType(MediaType.APPLICATION_JSON).content("""{"relation":"엄마"}"""))
            .andExpect(status().isBadRequest)
    }

    @Test fun `family relation is the sole wire field and omission preserves stored metadata`() {
        val owner = user(); val token = bearer(owner)
        val family = families.create(owner.id!!, mapOf("nickname" to "가족", "relation" to "자녀", "emoji" to "🧒"))
        for (path in listOf("/api/users/me/family-profiles", "/api/users/me/family-profiles/${family.id}")) {
            val isPatch = path.endsWith("/${family.id}")
            val body = if (isPatch) """{"version":${family.version},"relationship":"부모"}"""
                else """{"nickname":"가족","relationship":"부모"}"""
            val request = if (isPatch) patch(path) else post(path)
            mvc.perform(request.header("Authorization", token).contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isBadRequest).andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.field").value("relationship"))
        }
        mvc.perform(patch("/api/users/me/family-profiles/${family.id}").header("Authorization", token)
            .contentType(MediaType.APPLICATION_JSON).content("""{"version":${family.version},"nickname":"자녀이름"}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.relation").value("자녀"))
            .andExpect(jsonPath("$.data.emoji").value("🧒"))
        assertEquals("자녀", families.owned(owner.id!!, family.id).relation)
    }

    @Test fun `favorite state is shared by sessions isolated by account and idempotent with atomic events`() {
        val owner = user(); val first = bearer(owner); val second = bearer(owner); val other = bearer(user())
        val item = product(); val path = "/api/users/me/favorites/${item.productId}"
        mvc.perform(get(path).header("Authorization", first)).andExpect(status().isOk)
            .andExpect(jsonPath("$.data.isFavorite").value(false))
        repeat(2) {
            mvc.perform(put(path).header("Authorization", first)).andExpect(status().isOk)
                .andExpect(jsonPath("$.data.isFavorite").value(true))
        }
        assertEquals(listOf(UserActionType.FAVORITE), events(owner).map { it.actionType })
        mvc.perform(get(path).header("Authorization", second)).andExpect(status().isOk)
            .andExpect(jsonPath("$.data.isFavorite").value(true))
        mvc.perform(get("/api/users/me/favorites").header("Authorization", second)).andExpect(status().isOk)
            .andExpect(jsonPath("$.data.items[0].productId").value(item.productId!!))
            .andExpect(jsonPath("$.data.items[0].product.barcode").value(item.barcode))
        mvc.perform(delete(path).header("Authorization", other)).andExpect(status().isOk)
        assertTrue(favorites.state(owner.id!!, item.productId!!).isFavorite)
        mvc.perform(get("/api/users/me/favorites").header("Authorization", other))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items").isEmpty)
        repeat(2) { mvc.perform(delete(path).header("Authorization", second)).andExpect(status().isOk)
            .andExpect(jsonPath("$.data.isFavorite").value(false)) }
        assertEquals(1, events(owner).count { it.actionType == UserActionType.UNFAVORITE })
        assertFalse(favorites.state(owner.id!!, item.productId!!).isFavorite)
        assertTrue(historyService.getRecentProducts(owner.id!!, 0, 20).items.isEmpty())
    }

    @Test fun `favorites validate ids pages authentication and incomplete profiles`() {
        val token = bearer(user()); val incomplete = bearer(user(complete = false)); val item = product()
        val path = "/api/users/me/favorites/${item.productId}"
        for (request in listOf(get(path), put(path), delete(path), get("/api/users/me/favorites"))) {
            mvc.perform(request).andExpect(status().isUnauthorized)
        }
        mvc.perform(put(path).header("Authorization", incomplete)).andExpect(status().isForbidden)
            .andExpect(jsonPath("$.code").value("PROFILE_INCOMPLETE"))
        mvc.perform(put("/api/users/me/favorites/0").header("Authorization", token)).andExpect(status().isBadRequest)
        mvc.perform(put("/api/users/me/favorites/9223372036854775807").header("Authorization", token))
            .andExpect(status().isNotFound).andExpect(jsonPath("$.code").value("PRODUCT_NOT_FOUND"))
        for ((key, value) in listOf("page" to "-1", "page" to "10001", "size" to "0", "size" to "51")) {
            mvc.perform(get("/api/users/me/favorites").param(key, value).header("Authorization", token))
                .andExpect(status().isBadRequest).andExpect(jsonPath("$.field").value(key))
        }
    }

    @Test fun `concurrent add and concurrent remove each create exactly one transition event`() {
        val owner = user(); val item = product(); val executor = Executors.newFixedThreadPool(4)
        try {
            for (add in listOf(true, false)) {
                val ready = CountDownLatch(4); val start = CountDownLatch(1)
                val tasks = (1..4).map { executor.submit<FavoriteState> {
                    ready.countDown(); check(start.await(10, TimeUnit.SECONDS))
                    if (add) favorites.add(owner.id!!, item.productId!!) else favorites.remove(owner.id!!, item.productId!!)
                } }
                assertTrue(ready.await(10, TimeUnit.SECONDS)); start.countDown()
                tasks.forEach { assertEquals(add, it.get(20, TimeUnit.SECONDS).isFavorite) }
            }
        } finally { executor.shutdownNow() }
        assertEquals(1, events(owner).count { it.actionType == UserActionType.FAVORITE })
        assertEquals(1, events(owner).count { it.actionType == UserActionType.UNFAVORITE })
    }

    @Test fun `favorites survive catalogue absence never attach to reused barcode and can be removed`() {
        val owner = user(); val item = product(); favorites.add(owner.id!!, item.productId!!)
        products.deleteById(item.barcode); products.flush()
        products.saveAndFlush(Product(barcode = item.barcode, productId = ids.incrementAndGet(), productName = "다른 상품"))
        val favorite = favorites.list(owner.id!!, 0, 20).items.single()
        assertNull(favorite.product); assertEquals("NOT_IN_ACTIVE_DATASET", favorite.identityStatus)
        assertTrue(favorites.add(owner.id!!, item.productId!!).isFavorite)
        assertFalse(favorites.remove(owner.id!!, item.productId!!).isFavorite)
    }

    @Test fun `favorites page order is stable and account deletion removes state and events`() {
        val owner = user(); val a = product(); val b = product()
        val now = LocalDateTime.of(2026, 11, 2, 1, 0)
        favoriteRepository.saveAndFlush(ProductFavorite(userId = owner.id!!, productId = a.productId!!, barcode = a.barcode, createdAt = now))
        favoriteRepository.saveAndFlush(ProductFavorite(userId = owner.id!!, productId = b.productId!!, barcode = b.barcode, createdAt = now))
        val first = favorites.list(owner.id!!, 0, 1); val second = favorites.list(owner.id!!, 1, 1)
        assertTrue(first.hasNext); assertFalse(second.hasNext)
        assertEquals(b.productId, first.items.single().productId); assertEquals(a.productId, second.items.single().productId)
        historyService.recordAction(owner.id!!, UserActionEventRequest(a.barcode, "DETAIL_VIEW"))
        userService.deleteUser(owner.id!!)
        assertFalse(users.existsById(owner.id!!)); assertTrue(favorites.list(owner.id!!, 0, 20).items.isEmpty())
        assertTrue(events(owner).isEmpty())
    }

    @Test fun `self family none views record once per request but recent products deduplicate without favorites`() {
        val owner = user(); val token = bearer(owner); val a = product(); val b = product()
        val family = families.create(owner.id!!, mapOf("nickname" to "가족", "allergies" to "peanut"))
        mvc.perform(get("/api/products/${a.barcode}").header("Authorization", token)).andExpect(status().isOk)
        mvc.perform(get("/api/products/id/${b.productId}").header("Authorization", token)
            .param("analysisMode", "selected").param("familyProfileIds", family.id.toString())).andExpect(status().isOk)
        mvc.perform(get("/api/products/${a.barcode}").header("Authorization", token).param("analysisMode", "none"))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.analysis.status").value("NOT_EVALUATED"))
        assertEquals(3, events(owner).size)
        assertEquals(1, events(owner).count { it.personalizationAllowed })
        assertEquals(setOf("self", "selected", "none"), events(owner).map { it.analysisMode }.toSet())
        mvc.perform(get("/api/products/${a.barcode}/variants").header("Authorization", token)).andExpect(status().isOk)
        mvc.perform(get("/api/products/search").param("keyword", a.productName!!).header("Authorization", token)).andExpect(status().isOk)
        mvc.perform(get("/api/products/${a.barcode}")).andExpect(status().isOk)
        mvc.perform(get("/api/products/MISSING").header("Authorization", token)).andExpect(status().isNotFound)
        assertEquals(3, events(owner).size)
        favorites.add(owner.id!!, b.productId!!)
        mvc.perform(get("/api/histories/user/${owner.id}").param("view", "recent").param("size", "1").header("Authorization", token))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.items[0].productId").value(a.productId!!))
            .andExpect(jsonPath("$.data.items[0].analysisMode").value("none"))
            .andExpect(jsonPath("$.data.items[0].personalizationAllowed").value(false))
            .andExpect(jsonPath("$.data.hasNext").value(true))
        val second = historyService.getRecentProducts(owner.id!!, 1, 1)
        assertEquals(b.productId, second.items.single().productId); assertFalse(second.hasNext)
        mvc.perform(get("/api/histories/user/${owner.id}").header("Authorization", token)).andExpect(status().isOk)
            .andExpect(jsonPath("$.data").isArray).andExpect(jsonPath("$.data.length()").value(4))
    }

    @Test fun `recent view access validation stable ties and legacy anonymous ids remain safe`() {
        val owner = user(); val other = user(); val token = bearer(owner); val item = product()
        val now = LocalDateTime.of(2026, 11, 2, 1, 0)
        repeat(2) { histories.saveAndFlush(History(user = owner, barcode = item.barcode, actionType = UserActionType.DETAIL_VIEW, createdAt = now)) }
        val latest = histories.saveAndFlush(History(user = owner, barcode = "NO_BARCODE_ROW_1", actionType = UserActionType.SCAN, createdAt = now))
        val rows = historyService.getRecentProducts(owner.id!!, 0, 20).items
        assertEquals(2, rows.size); assertEquals(latest.id, rows.first().id); assertNull(rows.first().product)
        assertEquals(item.barcode, rows.last().product?.barcode)
        mvc.perform(get("/api/histories/user/${owner.id}").param("view", "recent").header("Authorization", bearer(other)))
            .andExpect(status().isForbidden)
        for (query in listOf("view=invalid", "view=recent&size=51", "view=recent&page=-1")) {
            mvc.perform(get("/api/histories/user/${owner.id}?$query").header("Authorization", token)).andExpect(status().isBadRequest)
        }
    }

    @Test fun `manual events preserve contract but do not change favorite state and respect family scope`() {
        val owner = user(); val other = user(); val item = product(); val token = bearer(owner)
        val ownFamily = families.create(owner.id!!, mapOf("nickname" to "가족"))
        val otherFamily = families.create(other.id!!, mapOf("nickname" to "다른가족"))
        mvc.perform(post("/api/histories/events").header("Authorization", token).contentType(MediaType.APPLICATION_JSON)
            .content("""{"productId":${item.productId},"actionType":"DETAIL_VIEW","analysisMode":"selected","familyProfileIds":[${ownFamily.id}]}"""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.personalizationAllowed").value(false))
        mvc.perform(post("/api/histories/events").header("Authorization", token).contentType(MediaType.APPLICATION_JSON)
            .content("""{"productId":${item.productId},"actionType":"DETAIL_VIEW","analysisMode":"selected","familyProfileIds":[${otherFamily.id}]}"""))
            .andExpect(status().isNotFound)
        historyService.recordAction(owner.id!!, UserActionEventRequest(item.barcode, "FAVORITE"))
        assertFalse(favorites.state(owner.id!!, item.productId!!).isFavorite)
        assertEquals(2, events(owner).size)
    }

    @Test fun `admin on behalf view is recorded for actor not the analysed account`() {
        val admin = user(role = UserRole.ADMIN); val target = user(); val item = product()
        mvc.perform(get("/api/products/id/${item.productId}").param("userId", target.id.toString()).header("Authorization", bearer(admin)))
            .andExpect(status().isOk)
        assertTrue(events(target).isEmpty()); assertFalse(events(admin).single().personalizationAllowed)
    }

    @Test fun `recommendation excludes family views and cancelled or repeated likes from preference signals`() {
        val owner = user(); val reference = product(); val candidate = product()
        neighbors.saveAndFlush(ProductNeighborSet(reference.barcode, "test", 1, "${candidate.barcode}|0.9"))
        histories.saveAndFlush(History(user = owner, barcode = candidate.barcode, productId = candidate.productId,
            actionType = UserActionType.SCAN, analysisMode = "none", personalizationAllowed = false))
        fun signalCount() = recommendations.recommendAlternatives(reference.barcode, owner.id!!, 1, 0.0).userContext.usableHistorySignals
        assertEquals(0, signalCount())
        favorites.add(owner.id!!, candidate.productId!!); assertEquals(1, signalCount())
        favorites.remove(owner.id!!, candidate.productId!!); assertEquals(0, signalCount())
        favorites.add(owner.id!!, candidate.productId!!); assertEquals(1, signalCount())
    }

    companion object { private val ids = AtomicLong(90_000_000_000L) }
}
