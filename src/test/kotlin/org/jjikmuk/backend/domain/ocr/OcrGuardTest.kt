package org.jjikmuk.backend.domain.ocr

import jakarta.servlet.FilterChain
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.AfterEach
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.authority.SimpleGrantedAuthority
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse

class OcrGuardTest {
    private val token = "test-only-team-token-32-characters"
    private fun request(value: String? = token) = MockHttpServletRequest("POST", "/api/ocr").apply {
        if (value != null) addHeader("X-OCR-Test-Token", value)
        contentType = "multipart/form-data; boundary=test"
    }

    @BeforeEach fun login() { SecurityContextHolder.getContext().authentication = UsernamePasswordAuthenticationToken(1L,null,listOf(SimpleGrantedAuthority("ROLE_USER"))) }
    @AfterEach fun cleanup() { SecurityContextHolder.clearContext() }
    @Test fun `team token does not replace member authentication`() {
        SecurityContextHolder.clearContext()
        val response=MockHttpServletResponse()
        OcrGuard(true).doFilter(request(),response,FilterChain { _, _ -> fail("anonymous") })
        assertEquals(401,response.status)
    }

    @Test fun `disabled or missing configuration fails closed`() {
        for (guard in listOf(OcrGuard(false))) {
            val response = MockHttpServletResponse()
            guard.doFilter(request(), response, FilterChain { _, _ -> fail("disabled") })
            assertEquals(503, response.status)
        }
    }

    @Test fun `authenticated request reaches handler with member login then cooldown applies`() {
        val guard = OcrGuard(true)
        val first = MockHttpServletResponse()
        guard.doFilter(request(), first, FilterChain { _, res -> res.writer.write("accepted") })
        assertEquals("accepted", first.contentAsString)
        assertEquals("no-store", first.getHeader("Cache-Control"))
        val second = MockHttpServletResponse()
        guard.doFilter(request(), second, FilterChain { _, _ -> fail("cooldown") })
        assertEquals(429, second.status)
    }

    @Test fun `oversized or wrong method or content type is rejected before handler`() {
        val cases = listOf(
            request().apply { addHeader("Content-Length", 11 * 1024 * 1024) } to 413,
            request().apply { method = "GET" } to 405,
            request().apply { contentType = "application/json" } to 415
        )
        for ((req, expected) in cases) {
            val response = MockHttpServletResponse()
            OcrGuard(true).doFilter(req, response, FilterChain { _, _ -> fail("invalid") })
            assertEquals(expected, response.status)
        }
    }

    @Test fun `concurrent request is rejected while original remains in flight`() {
        val guard = OcrGuard(true)
        guard.doFilter(request(), MockHttpServletResponse(), FilterChain { _, _ ->
            val response = MockHttpServletResponse()
            guard.doFilter(request(), response, FilterChain { _, _ -> fail("concurrent") })
            assertEquals(429, response.status)
        })
    }
}
