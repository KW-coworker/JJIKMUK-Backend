package org.jjikmuk.backend.global.config

import io.jsonwebtoken.Jwts
import io.jsonwebtoken.security.Keys
import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.springframework.beans.factory.annotation.Value
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter
import javax.crypto.SecretKey
import org.springframework.security.core.authority.SimpleGrantedAuthority
@Component
class JwtAuthenticationFilter(
    @Value("\${jwt.secret}") secretKey: String
) : OncePerRequestFilter() {

    private val key: SecretKey = Keys.hmacShaKeyFor(secretKey.toByteArray())

    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, filterChain: FilterChain) {
        val authHeader = request.getHeader("Authorization")

        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            val token = authHeader.substring(7)
            try {
                val claims = Jwts.parser().verifyWith(key).build().parseSignedClaims(token).payload
                val userId = claims.subject.toLong()

                // 🚀 1. 토큰에서 role 꺼내기 (null일 수 있으니 안전하게 처리)
                val role = claims.get("role", String::class.java) ?: "USER"

                // 🚀 2. 권한 정보를 스프링 시큐리티가 이해하는 객체로 변환
                val authorities = listOf(SimpleGrantedAuthority("ROLE_$role"))

                // 🚀 3. authorities를 담아서 인증 객체 생성
                val auth = UsernamePasswordAuthenticationToken(userId, null, authorities)
                SecurityContextHolder.getContext().authentication = auth
            } catch (e: Exception) {
                // 예외 처리
            }
        }
        filterChain.doFilter(request, response)
    }
}