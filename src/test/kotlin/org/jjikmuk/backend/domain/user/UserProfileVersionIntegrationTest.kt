package org.jjikmuk.backend.domain.user

import org.jjikmuk.backend.domain.auth.AuthSessionService
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.ResultActions
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.*
import tools.jackson.databind.json.JsonMapper
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.test.*

/** Actual security chain + committed transactions in isolated H2. No MySQL or AWS access. */
@SpringBootTest(properties = ["spring.config.import=",
    "spring.datasource.url=jdbc:h2:mem:user-profile-version;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@AutoConfigureMockMvc @ActiveProfiles("test")
class UserProfileVersionIntegrationTest @Autowired constructor(
    private val mvc: MockMvc, private val users: UserRepository, private val sessions: AuthSessionService,
    private val familyService: FamilyProfileService
) {
    private val mapper = JsonMapper.builder().findAndAddModules().build()
    private fun account(complete: Boolean = true, role: UserRole = UserRole.USER): User {
        val key = UUID.randomUUID().toString().replace("-", "").take(12)
        return users.saveAndFlush(User(email = "$key@example.invalid", nickname = "u$key", password = "unused",
            allergies = "milk", specialDiet = "lowSugar", profileCompleted = complete, role = role))
    }
    private fun token(user: User) = "Bearer ${sessions.issue(user, false, "test").token}"
    private fun stored(user: User) = users.findById(user.id!!).orElseThrow()
    private fun edit(auth: String, body: Map<String, Any?>, method: String = "PATCH", path: String = "/api/users/me"): ResultActions {
        val builder = when (method) { "PUT" -> put(path); "POST" -> post(path); else -> patch(path) }
        return mvc.perform(builder.header("Authorization", auth).contentType("application/json")
            .content(mapper.writeValueAsString(body)))
    }
    private fun me(auth: String) = mvc.perform(get("/api/users/me").header("Authorization", auth))

    @Test fun `profile responses include initial revision and retain existing contract`() {
        val user = account(); val auth = token(user)
        for (path in listOf("/api/users/me", "/api/users/${user.id}"))
            mvc.perform(get(path).header("Authorization", auth)).andExpect(status().isOk)
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.data.version").value(0))
                .andExpect(jsonPath("$.data.hasPassword").value(true))
                .andExpect(jsonPath("$.data.password").doesNotExist())
        mvc.perform(get("/api/users").header("Authorization", token(account(role = UserRole.ADMIN))))
            .andExpect(status().isOk).andExpect(jsonPath("$.data[0].version").isNumber)
    }

    @Test fun `two devices cannot overwrite a newer profile and reloading permits deliberate retry`() {
        val user = account(); val a = token(user); val b = token(user)
        me(a).andExpect(jsonPath("$.data.version").value(0))
        me(b).andExpect(jsonPath("$.data.version").value(0))
        edit(a, mapOf("version" to 0, "allergies" to "peanut"))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(1))
        edit(b, mapOf("version" to 0, "allergies" to null, "specialDiet" to null))
            .andExpect(status().isConflict).andExpect(jsonPath("$.code").value("PROFILE_VERSION_CONFLICT"))
            .andExpect(jsonPath("$.field").value("version"))
        assertEquals("peanut", stored(user).allergies)
        assertEquals("lowSugar", stored(user).specialDiet)
        me(b).andExpect(jsonPath("$.data.version").value(1)).andExpect(jsonPath("$.data.allergies").value("peanut"))
        edit(b, mapOf("version" to 1, "specialDiet" to "lowSodium"))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(2))
            .andExpect(jsonPath("$.data.allergies").value("peanut"))
    }

    @Test fun `concurrent HTTP updates with the same revision have exactly one winner`() {
        val user = account(); val tokens = listOf(token(user), token(user))
        val ready = CountDownLatch(2); val start = CountDownLatch(1)
        val pool = Executors.newFixedThreadPool(2)
        try {
            val futures = tokens.mapIndexed { i, auth -> pool.submit<Pair<Int, String>> {
                ready.countDown(); check(start.await(10, TimeUnit.SECONDS))
                val allergy = if (i == 0) "peanut" else "soy"
                val response = edit(auth, mapOf("version" to 0, "allergies" to allergy)).andReturn().response
                if (response.status == 409) assertEquals("PROFILE_VERSION_CONFLICT", mapper.readTree(response.contentAsString)["code"].asText())
                response.status to allergy
            } }
            assertTrue(ready.await(10, TimeUnit.SECONDS)); start.countDown()
            val results = futures.map { it.get(20, TimeUnit.SECONDS) }
            assertEquals(listOf(200, 409), results.map { it.first }.sorted())
            assertEquals(results.single { it.first == 200 }.second, stored(user).allergies)
            assertEquals(1, stored(user).profileVersion)
        } finally { start.countDown(); pool.shutdownNow() }
    }

    @Test fun `full replacement and legacy admin endpoint cannot bypass revision checks`() {
        val user = account(); val auth = token(user); val admin = token(account(role = UserRole.ADMIN))
        edit(auth, mapOf("version" to 0, "allergies" to "peanut"))
            .andExpect(status().isOk)
        for ((path, credential) in listOf("/api/users/me" to auth, "/api/users/${user.id}" to auth, "/api/users/${user.id}" to admin)) {
            edit(credential, mapOf("version" to 0, "nickname" to user.nickname), "PUT", path)
                .andExpect(status().isConflict).andExpect(jsonPath("$.code").value("PROFILE_VERSION_CONFLICT"))
        }
        edit(admin, mapOf("version" to 1, "nickname" to user.nickname), "PUT", "/api/users/${user.id}")
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(2))
            .andExpect(jsonPath("$.data.allergies").isEmpty).andExpect(jsonPath("$.data.specialDiet").isEmpty)
        edit(auth, mapOf("version" to 2, "nickname" to user.nickname, "allergies" to "egg"), "PUT")
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(3))
    }

    @Test fun `all write paths reject missing null coerced fractional negative and oversized revisions`() {
        val user = account(); val auth = token(user)
        val invalid = listOf(null, -1, 0.0, 1.5, "0", true, emptyList<Int>(), mapOf("n" to 0), java.math.BigInteger("9223372036854775808"))
        for ((method, path) in listOf("PATCH" to "/api/users/me", "PUT" to "/api/users/me",
            "PUT" to "/api/users/${user.id}", "POST" to "/api/users/me/profile/complete")) {
            for (value in invalid) {
                edit(auth, mapOf("nickname" to user.nickname, "version" to value), method, path)
                    .andExpect(status().isBadRequest).andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                    .andExpect(jsonPath("$.field").value("version"))
            }
            edit(auth, mapOf("nickname" to user.nickname), method, path)
                .andExpect(status().isBadRequest).andExpect(jsonPath("$.field").value("version"))
        }
        assertEquals(0, stored(user).profileVersion); assertEquals("milk", stored(user).allergies)
    }

    @Test fun `failed validation does not consume a revision or partially change the profile`() {
        val user = account(); val other = account(); val auth = token(user)
        edit(auth, mapOf("version" to 0, "nickname" to other.nickname, "allergies" to null))
            .andExpect(status().isConflict).andExpect(jsonPath("$.code").value("NICKNAME_ALREADY_EXISTS"))
        edit(auth, mapOf("version" to 0, "nickname" to "다른이름", "allergies" to "unsupported"))
            .andExpect(status().isBadRequest)
        assertEquals(0, stored(user).profileVersion); assertEquals(user.nickname, stored(user).nickname)
        assertEquals("milk", stored(user).allergies)
        edit(auth, mapOf("version" to 0, "allergies" to "egg, 밀"))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(1))
            .andExpect(jsonPath("$.data.allergies").value("egg,wheat"))
    }

    @Test fun `profile completion checks revision before changing fields or completion flag`() {
        val user = account(complete = false); val auth = token(user)
        edit(auth, mapOf("version" to 0, "allergies" to "peanut"))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.profileCompleted").value(false))
        edit(auth, mapOf("version" to 0, "nickname" to user.nickname), "POST", "/api/users/me/profile/complete")
            .andExpect(status().isConflict)
        assertFalse(stored(user).profileCompleted); assertEquals("peanut", stored(user).allergies)
        edit(auth, mapOf("version" to 1, "nickname" to user.nickname, "allergies" to "peanut"), "POST", "/api/users/me/profile/complete")
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(2))
            .andExpect(jsonPath("$.data.profileCompleted").value(true))
        edit(auth, mapOf("version" to 1, "nickname" to user.nickname), "POST", "/api/users/me/profile/complete")
            .andExpect(status().isConflict)
        assertEquals(2, stored(user).profileVersion)
    }

    @Test fun `omission preserves clear removes and even a no-op consumes one revision`() {
        val user = account(); val auth = token(user)
        edit(auth, mapOf("version" to 0, "nickname" to user.nickname))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(1))
            .andExpect(jsonPath("$.data.allergies").value("milk"))
        edit(auth, mapOf("version" to 1, "allergies" to null, "specialDiet" to ""))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(2))
            .andExpect(jsonPath("$.data.allergies").isEmpty).andExpect(jsonPath("$.data.specialDiet").isEmpty)
        edit(auth, mapOf("version" to 1, "allergies" to null, "specialDiet" to ""))
            .andExpect(status().isConflict)
    }

    @Test fun `session refresh and family edits do not invalidate self profile revision`() {
        val user = account(); val issued = sessions.issue(user, false, "test")
        val family = familyService.create(user.id!!, mapOf("nickname" to "가족"))
        familyService.patch(user.id!!, family.id, mapOf("version" to family.version, "allergies" to "soy"))
        val fresh = sessions.refresh(issued.refreshToken)
        assertEquals(0, stored(user).profileVersion)
        edit("Bearer ${fresh.token}", mapOf("version" to 0, "allergies" to "peanut"))
            .andExpect(status().isOk).andExpect(jsonPath("$.data.version").value(1))
        assertEquals(user.tokenVersion, stored(user).tokenVersion)
    }

    @Test fun `other accounts cannot edit a profile even with the right version`() {
        val a = account(); val b = account()
        edit(token(b), mapOf("version" to 0, "nickname" to "잘못된수정"), "PUT", "/api/users/${a.id}")
            .andExpect(status().isForbidden)
        mvc.perform(patch("/api/users/me").contentType("application/json").content("""{"version":0,"allergies":null}"""))
            .andExpect(status().isUnauthorized)
        assertEquals(0, stored(a).profileVersion); assertEquals("milk", stored(a).allergies)
    }
}
