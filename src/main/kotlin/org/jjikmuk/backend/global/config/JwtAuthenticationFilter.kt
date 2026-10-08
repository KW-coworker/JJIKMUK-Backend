package org.jjikmuk.backend.global.config

import io.jsonwebtoken.ExpiredJwtException
import io.jsonwebtoken.JwtException
import io.jsonwebtoken.Jwts
import io.jsonwebtoken.security.Keys
import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.springframework.beans.factory.annotation.Value
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.authority.SimpleGrantedAuthority
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter
import javax.crypto.SecretKey

@Component
class JwtAuthenticationFilter(
    @Value("\${jwt.secret}") secretKey: String,
    private val userRepository: UserRepository
) : OncePerRequestFilter() {
    private val key: SecretKey = Keys.hmacShaKeyFor(secretKey.toByteArray())

    override fun doFilterInternal(
        request: HttpServletRequest,
        response: HttpServletResponse,
        filterChain: FilterChain
    ) {
        val authHeader = request.getHeader("Authorization")
        if (authHeader == null || !authHeader.startsWith("Bearer ")) {
            filterChain.doFilter(request, response)
            return
        }

        val token = authHeader.substring(7)
        try {
            val claims = Jwts.parser().verifyWith(key).build().parseSignedClaims(token).payload
            val userId = claims.subject.toLong()
            val tokenVersion = (claims["tokenVersion"] as? Number)?.toInt()
                ?: return writeUnauthorized(
                    response,
                    ApiErrorCode.AUTH_TOKEN_INVALID,
                    "이전 형식의 로그인 토큰입니다. 다시 로그인해주세요."
                )
            val user = userRepository.findById(userId).orElse(null)
                ?: return writeUnauthorized(
                    response,
                    ApiErrorCode.AUTH_TOKEN_INVALID,
                    "사용자 정보를 확인할 수 없습니다. 다시 로그인해주세요."
                )
            if (user.tokenVersion != tokenVersion) {
                return writeUnauthorized(
                    response,
                    ApiErrorCode.AUTH_TOKEN_INVALID,
                    "로그인 세션이 무효화되었습니다. 다시 로그인해주세요."
                )
            }

            val authorities = listOf(SimpleGrantedAuthority("ROLE_${user.role.name}"))
            SecurityContextHolder.getContext().authentication =
                UsernamePasswordAuthenticationToken(requireNotNull(user.id), null, authorities)
        } catch (_: ExpiredJwtException) {
            writeUnauthorized(
                response,
                ApiErrorCode.AUTH_TOKEN_EXPIRED,
                "로그인 토큰이 만료되었습니다. 다시 로그인해주세요."
            )
            return
        } catch (_: JwtException) {
            writeUnauthorized(
                response,
                ApiErrorCode.AUTH_TOKEN_INVALID,
                "로그인 토큰이 유효하지 않습니다."
            )
            return
        } catch (_: Exception) {
            writeUnauthorized(
                response,
                ApiErrorCode.AUTH_TOKEN_INVALID,
                "로그인 토큰이 유효하지 않습니다."
            )
            return
        }
        filterChain.doFilter(request, response)
    }

    private fun writeUnauthorized(response: HttpServletResponse, code: String, message: String) {
        response.status = HttpServletResponse.SC_UNAUTHORIZED
        response.characterEncoding = Charsets.UTF_8.name()
        response.contentType = "application/json"
        response.writer.write(
            """{"status":401,"code":"$code","message":"$message"}"""
        )
    }
}
