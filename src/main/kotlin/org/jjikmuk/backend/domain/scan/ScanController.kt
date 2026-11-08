package org.jjikmuk.backend.domain.scan

import jakarta.servlet.http.HttpServletRequest
import org.jjikmuk.backend.global.exception.ErrorResponse
import org.springframework.beans.factory.annotation.Value
import org.springframework.http.ResponseEntity
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.multipart.MultipartHttpServletRequest

@RestController
class ScanController(private val proxy: ScanProxy, private val catalog: ScanCatalog,
                     @param:Value("\${scan.image-fallback.enabled:false}") private val fallbackEnabled: Boolean,
                     @param:Value("\${scan.image-fallback.approved-user-ids:}") approvedUsers: String) {
    // Explicit, operator-approved developer accounts only. No inferred user consent.
    private val fallbackUsers = approvedUsers.split(',').filter { it.isNotBlank() }.map { it.trim().toLong().also { id -> require(id > 0) } }.toSet()

    @PostMapping("/api/product-scans", consumes = ["multipart/form-data"], produces = ["application/json"])
    fun scan(request: MultipartHttpServletRequest): ScanResponse {
        val id = request.getHeader("Idempotency-Key").orEmpty()
        if (!validScanId(id)) throw ScanFailure(400, "INVALID_REQUEST")
        val owner = SecurityContextHolder.getContext().authentication?.principal as? Long
            ?: throw ScanFailure(401, "AUTHENTICATION_REQUIRED")
        val files = request.multiFileMap.values.flatten()
        if (request.parameterMap.isNotEmpty() || files.size != 1 || files[0].name != "image") throw ScanFailure(400, "INVALID_REQUEST")
        val image = files.single()
        if (image.size > 10 * 1024 * 1024) throw ScanFailure(413, "IMAGE_TOO_LARGE")
        val bytes = image.inputStream.use { it.readNBytes(10 * 1024 * 1024 + 1) }
        val requestId = request.getAttribute("scanRequestId") as String
        val version = catalog.verifiedVersion()
        val value = proxy.scan(bytes, image.contentType.orEmpty(), owner, id, requestId, version,
            fallbackEnabled && owner in fallbackUsers)
        val response = catalog.hydrate(value, requestId)
        // Explicit public byte cap, including DB text (never truncate a product silently).
        if (tools.jackson.databind.json.JsonMapper.builder().build().writeValueAsBytes(response).size > 1024 * 1024)
            throw ScanFailure(502, "SCAN_UPSTREAM_INVALID_RESPONSE")
        return response
    }

    @ExceptionHandler(ScanFailure::class)
    fun failure(error: ScanFailure, request: HttpServletRequest): ResponseEntity<ErrorResponse> =
        ResponseEntity.status(error.status).header("Cache-Control", "no-store")
            .header("X-Request-ID", request.getAttribute("scanRequestId") as? String ?: java.util.UUID.randomUUID().toString())
            .body(ErrorResponse(error.status, error.code, "상품 스캔 요청을 완료하지 못했습니다. 자동 재시도하지 마세요."))
}
