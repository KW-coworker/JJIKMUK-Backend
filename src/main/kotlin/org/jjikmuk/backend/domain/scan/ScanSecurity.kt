package org.jjikmuk.backend.domain.scan

import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.jjikmuk.backend.global.config.JwtAuthenticationFilter
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.security.authentication.AnonymousAuthenticationToken
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.security.web.SecurityFilterChain
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter
import org.springframework.web.filter.OncePerRequestFilter
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

internal fun scanError(response: HttpServletResponse, status: Int, code: String) {
    response.status = status
    response.contentType = "application/json"
    response.characterEncoding = "UTF-8"
    if (status == 429) response.setHeader("Retry-After", "3")
    response.writer.write("""{"status":$status,"code":"$code","message":"상품 스캔을 완료하지 못했습니다. 자동 재시도하지 마세요."${if (status == 429) ",\"retryAfterSeconds\":3" else ""}}""")
}

internal class ScanGuard(private val enabled: Boolean) : OncePerRequestFilter() {
    private val busy = AtomicBoolean(false)
    private var nextAllowed = 0L
    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        val requestId = request.getAttribute("scanRequestId") as? String ?: UUID.randomUUID().toString()
        request.setAttribute("scanRequestId", requestId)
        response.setHeader("X-Request-ID", requestId)
        response.setHeader("Cache-Control", "no-store")
        response.setHeader("X-Content-Type-Options", "nosniff")
        var acquired = false
        val started = System.nanoTime()
        try {
            val auth = SecurityContextHolder.getContext().authentication
            if (auth == null || !auth.isAuthenticated || auth is AnonymousAuthenticationToken || auth.principal !is Long)
                throw ScanFailure(401, "AUTHENTICATION_REQUIRED")
            if (!enabled) throw ScanFailure(503, "SCAN_DISABLED")
            if (request.method != "POST") throw ScanFailure(405, "METHOD_NOT_ALLOWED")
            if (!validScanId(request.getHeader("Idempotency-Key").orEmpty())) throw ScanFailure(400, "INVALID_REQUEST")
            val raw = request.getHeader("Content-Length")
            if (raw != null) {
                val length = raw.toLongOrNull() ?: throw ScanFailure(400, "INVALID_REQUEST")
                if (length < 0) throw ScanFailure(400, "INVALID_REQUEST")
                if (length > 10 * 1024 * 1024 + 65536) throw ScanFailure(413, "IMAGE_TOO_LARGE")
            }
            if (!request.contentType.orEmpty().lowercase().startsWith("multipart/form-data;")) throw ScanFailure(400, "INVALID_REQUEST")
            if (!busy.compareAndSet(false, true)) throw ScanFailure(429, "SCAN_BUSY")
            acquired = true
            if (System.nanoTime() < nextAllowed) throw ScanFailure(429, "RATE_LIMITED")
            nextAllowed = System.nanoTime() + 3_000_000_000L
            chain.doFilter(request, response)
        } catch (error: ScanFailure) { scanError(response, error.status, error.code) }
        finally {
            if (acquired) busy.set(false)
            LoggerFactory.getLogger(ScanGuard::class.java).info("product_scan requestId={} status={} durationMs={}",
                requestId, response.status, (System.nanoTime() - started) / 1_000_000)
        }
    }
}

/** Trace even authentication failures, without logging tokens, user IDs or bodies. */
private class ScanTrace : OncePerRequestFilter() {
    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        val id = UUID.randomUUID().toString()
        request.setAttribute("scanRequestId", id)
        response.setHeader("X-Request-ID", id)
        response.setHeader("Cache-Control", "no-store")
        chain.doFilter(request, response)
    }
}

@Configuration
class ScanSecurity {
    @Bean @Order(0)
    fun scanSecurityChain(http: HttpSecurity, jwtFilter: JwtAuthenticationFilter,
                          @Value("\${scan.enabled:false}") enabled: Boolean): SecurityFilterChain {
        http.securityMatcher("/api/product-scans")
            .csrf { it.disable() }.formLogin { it.disable() }.httpBasic { it.disable() }
            .sessionManagement { it.sessionCreationPolicy(SessionCreationPolicy.STATELESS) }
            .authorizeHttpRequests { it.anyRequest().authenticated() }
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter::class.java)
            .addFilterBefore(ScanTrace(), JwtAuthenticationFilter::class.java)
            .addFilterAfter(ScanGuard(enabled), UsernamePasswordAuthenticationFilter::class.java)
        return http.build()
    }
}
