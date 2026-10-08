package org.jjikmuk.backend.global.config

import io.jsonwebtoken.Jwts
import io.jsonwebtoken.security.Keys
import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component
import java.util.*
import java.time.Instant
import javax.crypto.SecretKey

data class IssuedAccessToken(
    val token: String,
    val expiresAt: Instant,
    val expiresInSeconds: Long
)

@Component
class JwtProvider(
    @Value("\${jwt.secret}") private val secretKey: String,
    @Value("\${jwt.expiration-time}") private val expirationTime: Long
) {
    // String으로 된 시크릿 키를 JWT 전용 규격(SecretKey)으로 변환
    private val key: SecretKey = Keys.hmacShaKeyFor(secretKey.toByteArray())

    fun createToken(
        userId: Long,
        email: String,
        role: String,
        tokenVersion: Int
    ): IssuedAccessToken {
        val now = Date()
        val validity = Date(now.time + expirationTime)

        val token = Jwts.builder()
            .subject(userId.toString())
            .claim("email", email)
            .claim("role", role)
            .claim("tokenVersion", tokenVersion)
            .issuedAt(now)
            .expiration(validity)
            .signWith(key)
            .compact()
        return IssuedAccessToken(
            token = token,
            expiresAt = validity.toInstant(),
            expiresInSeconds = expirationTime / 1_000
        )
    }
}
