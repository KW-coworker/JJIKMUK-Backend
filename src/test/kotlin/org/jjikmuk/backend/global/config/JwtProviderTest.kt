package org.jjikmuk.backend.global.config

import io.jsonwebtoken.Jwts
import io.jsonwebtoken.security.Keys
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class JwtProviderTest {
    @Test
    fun `issued token documents user id expiry and session version`() {
        val secret = "0123456789abcdef0123456789abcdef0123456789abcdef"
        val provider = JwtProvider(secret, 60_000)

        val issued = provider.createToken(
            userId = 17,
            email = "user@example.com",
            role = "USER",
            tokenVersion = 3
        )
        val claims = Jwts.parser()
            .verifyWith(Keys.hmacShaKeyFor(secret.toByteArray()))
            .build()
            .parseSignedClaims(issued.token)
            .payload

        assertEquals("17", claims.subject)
        assertEquals("user@example.com", claims["email"])
        assertEquals(3, (claims["tokenVersion"] as Number).toInt())
        assertEquals(60L, issued.expiresInSeconds)
        assertTrue(issued.expiresAt.isAfter(java.time.Instant.now()))
    }
}
