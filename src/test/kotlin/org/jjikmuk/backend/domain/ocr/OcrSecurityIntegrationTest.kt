package org.jjikmuk.backend.domain.ocr
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.config.JwtProvider
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.transaction.annotation.Transactional

@ActiveProfiles("test")
@SpringBootTest(properties = ["spring.config.import=", "jwt.secret=unit-test-only-jwt-secret-32-characters-long", "ocr.proxy.enabled=true"])
@AutoConfigureMockMvc
@Transactional
class OcrSecurityIntegrationTest @Autowired constructor(private val mvc: MockMvc, private val users: UserRepository, private val jwt: JwtProvider) {
    @Test fun `anonymous and team token alone cannot reach OCR`() {
        assertEquals(401, mvc.perform(post("/api/ocr")).andReturn().response.status)
        assertEquals(401, mvc.perform(post("/api/ocr").header("X-OCR-Test-Token", "integration-test-token-32-characters")).andReturn().response.status)
    }
    @Test fun `valid member JWT reaches input validation without team token`() {
        val user = users.saveAndFlush(User(email="ocr-test@example.invalid",nickname="ocr_jwt_test",password="test-only"))
        val token = jwt.createToken(requireNotNull(user.id),user.email,user.role.name,user.tokenVersion).token
        assertEquals(403,mvc.perform(post("/api/ocr/debug").header("Authorization","Bearer $token")).andReturn().response.status)
        assertEquals(415,mvc.perform(post("/api/ocr").header("Authorization","Bearer $token")).andReturn().response.status)
        user.tokenVersion += 1
        users.saveAndFlush(user)
        assertEquals(401,mvc.perform(post("/api/ocr").header("Authorization","Bearer $token")).andReturn().response.status)
    }
    @Test fun `invalid JWT and deleted users cannot reach OCR`() {
        assertEquals(401,mvc.perform(post("/api/ocr").header("Authorization","Bearer broken")).andReturn().response.status)
        val token = jwt.createToken(987654321L,"absent@example.invalid","USER",0).token
        assertEquals(401,mvc.perform(post("/api/ocr").header("Authorization","Bearer $token")).andReturn().response.status)
    }
    @Test fun `public filters and unrelated authentication remain intact`() {
        assertEquals(200,mvc.perform(get("/api/products/filters")).andReturn().response.status)
        assertEquals(401,mvc.perform(get("/private-not-an-ocr-endpoint")).andReturn().response.status)
    }
}
