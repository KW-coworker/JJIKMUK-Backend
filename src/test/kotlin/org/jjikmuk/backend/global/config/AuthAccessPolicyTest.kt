package org.jjikmuk.backend.global.config

import org.junit.jupiter.api.Test
import org.springframework.mock.web.MockHttpServletRequest
import kotlin.test.*

class AuthAccessPolicyTest {
    @Test fun `proof authentication is POST only and never a prefix match`() {
        for (path in AuthAccessPolicy.proofAuthenticatedPaths) {
            assertTrue(AuthAccessPolicy.authenticatesOwnProof(MockHttpServletRequest("POST", path)))
            assertFalse(AuthAccessPolicy.authenticatesOwnProof(MockHttpServletRequest("GET", path)))
            assertFalse(AuthAccessPolicy.authenticatesOwnProof(MockHttpServletRequest("POST", "$path/extra")))
        }
    }

    @Test fun `onboarding allows only exact methods and owned deletion`() {
        for ((method, path) in listOf(
            "GET" to "/api/users/me", "PATCH" to "/api/users/me",
            "POST" to "/api/users/me/profile/complete", "PUT" to "/api/users/me/photo",
            "DELETE" to "/api/users/me/photo", "DELETE" to "/api/users/17",
            "GET" to "/api/auth/nicknames/availability", "GET" to "/api/products/classifications"
        )) assertTrue(AuthAccessPolicy.allowsIncompleteProfile(MockHttpServletRequest(method, path), 17), "$method $path")
        for ((method, path) in listOf(
            "PUT" to "/api/users/me", "DELETE" to "/api/users/18", "GET" to "/api/users/17",
            "POST" to "/api/users/me/family-profiles", "GET" to "/api/products/filter",
            "GET" to "/api/products/search", "POST" to "/api/users/me/profile/complete/extra",
            "PATCH" to "/api/users/me/photo", "GET" to "/api/auth/logout/refresh"
        )) assertFalse(AuthAccessPolicy.allowsIncompleteProfile(MockHttpServletRequest(method, path), 17), "$method $path")
    }

    @Test fun `servlet and context paths resolve to the same policy`() {
        val request = MockHttpServletRequest("POST", "/backend/api/auth/logout/refresh")
        request.contextPath = "/backend"
        assertTrue(AuthAccessPolicy.authenticatesOwnProof(request))
        request.servletPath = "/api/auth/logout/refresh"
        assertTrue(AuthAccessPolicy.authenticatesOwnProof(request))
    }
}
