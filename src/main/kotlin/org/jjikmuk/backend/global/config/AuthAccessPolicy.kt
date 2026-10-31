package org.jjikmuk.backend.global.config

import jakarta.servlet.http.HttpServletRequest

/** Exact method/path rules; no prefix-based user or auth bypass. */
object AuthAccessPolicy {
    // These POST handlers verify their own proof, independently of an optional Access header.
    val proofAuthenticatedPaths = setOf(
        "/api/auth/login", "/api/auth/google", "/api/auth/refresh",
        "/api/auth/google/link", "/api/auth/google/link/cancel", "/api/auth/logout/refresh"
    )

    fun authenticatesOwnProof(request: HttpServletRequest): Boolean =
        request.method == "POST" && path(request) in proofAuthenticatedPaths

    fun allowsIncompleteProfile(request: HttpServletRequest, userId: Long): Boolean {
        val path = path(request)
        return when (request.method) {
            "GET", "HEAD" -> path in setOf(
                "/api/users/me", "/api/users/me/photo", "/api/auth/nicknames/availability",
                // Catalog metadata is needed to complete the dietary preference form.
                "/api/products/filters", "/api/products/classifications"
            )
            "PATCH" -> path == "/api/users/me"
            "PUT" -> path == "/api/users/me/photo"
            "DELETE" -> path == "/api/users/me/photo" || path == "/api/users/$userId"
            "POST" -> path in proofAuthenticatedPaths || path in setOf(
                "/api/users/me/profile/complete", "/api/auth/logout", "/api/auth/signup",
                "/api/auth/email/send", "/api/auth/email/verify", "/api/auth/password/reset"
            )
            else -> false
        }
    }

    // servletPath is empty for some mock/default servlet mappings. Keep the context path out.
    private fun path(request: HttpServletRequest): String = request.servletPath.ifEmpty {
        request.requestURI.removePrefix(request.contextPath)
    }
}
