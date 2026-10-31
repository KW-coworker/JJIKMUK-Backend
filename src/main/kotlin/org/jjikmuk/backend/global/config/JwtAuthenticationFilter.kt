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
    private val userRepository: UserRepository,
    private val sessions: org.jjikmuk.backend.domain.auth.AuthSessionRepository
) : OncePerRequestFilter() {
    private val key: SecretKey = Keys.hmacShaKeyFor(secretKey.toByteArray())

    override fun doFilterInternal(
        request: HttpServletRequest,
        response: HttpServletResponse,
        filterChain: FilterChain
    ) {
        // These endpoints authenticate their own password/Google/refresh proof. An expired access
        // header must not prevent refresh or signing in again.
        if (AuthAccessPolicy.authenticatesOwnProof(request)) {
            filterChain.doFilter(request, response)
            return
        }
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
            val sessionId = claims["sid"] as? String
            if (sessionId != null) {
                val session = sessions.findById(sessionId).orElse(null)
                if (session == null || session.userId != userId || session.revokedAt != null ||
                    !session.expiresAt.isAfter(java.time.Instant.now()) || session.tokenVersion != user.tokenVersion) {
                    writeUnauthorized(response, ApiErrorCode.AUTH_TOKEN_INVALID, "로그인 세션이 무효화되었습니다.")
                    return
                }
            }
            // Read live DB state, not a stale claim: profile completion unlocks the same session.
            if (!user.profileCompleted && !AuthAccessPolicy.allowsIncompleteProfile(request, userId)) {
                response.status = HttpServletResponse.SC_FORBIDDEN
                response.characterEncoding = Charsets.UTF_8.name()
                response.contentType = "application/json"
                response.writer.write(
                    """{"status":403,"code":"${ApiErrorCode.PROFILE_INCOMPLETE}","message":"추가 프로필 입력을 완료해주세요."}"""
                )
                return
            }
            SecurityContextHolder.getContext().authentication =
                UsernamePasswordAuthenticationToken(requireNotNull(user.id), null, authorities).apply { details = sessionId }
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
        } catch (_: IllegalArgumentException) {
            writeUnauthorized(response, ApiErrorCode.AUTH_TOKEN_INVALID, "로그인 토큰이 유효하지 않습니다.")
            return
        } catch (_: Exception) {
            response.status = HttpServletResponse.SC_SERVICE_UNAVAILABLE
            response.characterEncoding = "UTF-8"
            response.contentType = "application/json"
            response.writer.write("""{"status":503,"code":"AUTH_SERVICE_UNAVAILABLE","message":"로그인 상태 확인에 실패했습니다. 세션을 유지하고 다시 시도해주세요."}""")
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
