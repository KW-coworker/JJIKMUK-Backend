package org.jjikmuk.backend.global.config

import org.jjikmuk.backend.domain.auth.AuthSessionRepository
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.Test
import org.mockito.Mockito.*
import org.springframework.dao.DataAccessResourceFailureException
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse
import org.springframework.security.core.context.SecurityContextHolder
import kotlin.test.*

class JwtAuthenticationFailureTest {
    @Test fun `database outage is retryable 503 not a revoked login`() {
        val secret = "test-only-0123456789abcdef0123456789abcdef0123456789abcdef"
        val users = mock(UserRepository::class.java)
        val sessions = mock(AuthSessionRepository::class.java)
        `when`(users.findById(17L)).thenThrow(DataAccessResourceFailureException("test outage"))
        val filter = JwtAuthenticationFilter(secret, users, sessions)
        val token = JwtProvider(secret, 60000).createToken(17, "unit@example.com", "USER", 0).token
        val request = MockHttpServletRequest("GET", "/api/users/me")
        request.addHeader("Authorization", "Bearer $token")
        val response = MockHttpServletResponse()
        try {
            filter.doFilter(request, response) { _, _ -> fail("A failed authentication lookup must not enter the controller") }
            assertEquals(503, response.status)
            assertTrue(response.contentAsString.contains("AUTH_SERVICE_UNAVAILABLE"))
            assertFalse(response.contentAsString.contains("test outage"))
        } finally { SecurityContextHolder.clearContext() }
    }
}
