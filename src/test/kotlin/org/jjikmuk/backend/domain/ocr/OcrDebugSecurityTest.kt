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
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.transaction.annotation.Transactional

@ActiveProfiles("test")
@SpringBootTest(properties = ["spring.config.import=", "ocr.proxy.enabled=true", "ocr.debug.enabled=true",
    "ocr.debug.allowed-emails=debug-allowed@example.invalid"])
@AutoConfigureMockMvc
@Transactional
class OcrDebugSecurityTest @Autowired constructor(private val mvc: MockMvc, private val users: UserRepository, private val jwt: JwtProvider) {
    private fun token(email: String): String {
        val user = users.saveAndFlush(User(email=email,nickname="test_"+email.substringBefore('@'),password="test-only"))
        return jwt.createToken(requireNotNull(user.id),user.email,user.role.name,user.tokenVersion).token
    }
    @Test fun `debug rejects anonymous and other members before image processing`() {
        assertEquals(401,mvc.perform(post("/api/ocr/debug")).andReturn().response.status)
        val token = token("debug-other@example.invalid")
        assertEquals(403,mvc.perform(post("/api/ocr/debug").header("Authorization","Bearer $token")).andReturn().response.status)
        assertEquals(415,mvc.perform(post("/api/ocr").header("Authorization","Bearer $token")).andReturn().response.status)
    }
    @Test fun `allowlisted member reaches existing upload guards`() {
        val token = token("debug-allowed@example.invalid")
        assertEquals(415,mvc.perform(post("/api/ocr/debug").header("Authorization","Bearer $token")).andReturn().response.status)
    }
}
