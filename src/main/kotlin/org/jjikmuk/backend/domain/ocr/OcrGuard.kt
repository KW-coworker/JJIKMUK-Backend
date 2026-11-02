package org.jjikmuk.backend.domain.ocr

import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.slf4j.LoggerFactory
import org.springframework.web.filter.OncePerRequestFilter
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.security.authentication.AnonymousAuthenticationToken
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

class OcrFailure(val status: Int, val code: String) : RuntimeException(code)

fun writeOcrError(response: HttpServletResponse, status: Int, code: String, id: String) {
    response.status = status
    response.contentType = "application/json"
    response.characterEncoding = "UTF-8"
    response.writer.write("""{"error":{"requestId":"$id","code":"$code","message":"OCR request could not be completed; do not automatically retry."}}""")
}

class OcrGuard(private val enabled: Boolean, private val debugAllowed: (Long) -> Boolean = { false }) : OncePerRequestFilter() {
    private val busy = AtomicBoolean(false)
    private var nextAllowed = 0L
    private val auditLogger = LoggerFactory.getLogger(OcrGuard::class.java)

    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        val id = UUID.randomUUID().toString()
        val started = System.nanoTime()
        var acquired = false
        request.setAttribute("ocrRequestId", id)
        response.setHeader("X-Request-ID", id)
        response.setHeader("Cache-Control", "no-store")
        response.setHeader("X-Content-Type-Options", "nosniff")
        try {
            val auth = SecurityContextHolder.getContext().authentication
            if (auth == null || !auth.isAuthenticated || auth is AnonymousAuthenticationToken || auth.principal !is Long)
                throw OcrFailure(401, "AUTHENTICATION_REQUIRED")
            if (!enabled) throw OcrFailure(503, "OCR_DISABLED")
            val path = request.servletPath.ifEmpty { request.requestURI.removePrefix(request.contextPath) }
            if (path == "/api/ocr/debug" && !debugAllowed(auth.principal as Long))
                throw OcrFailure(403, "OCR_DEBUG_FORBIDDEN")
            if (request.method != "POST") throw OcrFailure(405, "METHOD_NOT_ALLOWED")
            val length = request.getHeader("Content-Length")
            if (length != null) {
                val bytes = length.toLongOrNull() ?: throw OcrFailure(400, "INVALID_REQUEST")
                if (bytes < 0) throw OcrFailure(400, "INVALID_REQUEST")
                if (bytes > 10L * 1024 * 1024 + 65536) throw OcrFailure(413, "IMAGE_TOO_LARGE")
            }
            if (!request.contentType.orEmpty().lowercase().startsWith("multipart/form-data;"))
                throw OcrFailure(415, "INVALID_CONTENT_TYPE")
            if (!busy.compareAndSet(false, true)) throw OcrFailure(429, "OCR_BUSY")
            acquired = true
            if (System.nanoTime() < nextAllowed) throw OcrFailure(429, "RATE_LIMITED")
            nextAllowed = System.nanoTime() + 3_000_000_000L
            chain.doFilter(request, response)
        } catch (error: OcrFailure) {
            if (error.status == 429) response.setHeader("Retry-After", "3")
            writeOcrError(response, error.status, error.code, id)
        } finally {
            if (acquired) busy.set(false)
            auditLogger.info("ocr_proxy requestId={} status={} durationMs={}", id, response.status,
                (System.nanoTime() - started) / 1_000_000)
        }
    }
}
