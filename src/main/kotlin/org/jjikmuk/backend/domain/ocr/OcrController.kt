package org.jjikmuk.backend.domain.ocr

import jakarta.servlet.http.HttpServletResponse
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.multipart.MultipartHttpServletRequest
import java.util.UUID

@RestController
class OcrController(private val proxy: OcrProxy) {
    @PostMapping("/api/ocr", consumes = ["multipart/form-data"], produces = ["application/json"])
    fun scan(request: MultipartHttpServletRequest) = scanFile(request, false)

    @PostMapping("/api/ocr/debug", consumes = ["multipart/form-data"], produces = ["application/json"])
    fun debug(request: MultipartHttpServletRequest) = scanFile(request, true)

    private fun scanFile(request: MultipartHttpServletRequest, debug: Boolean): tools.jackson.databind.JsonNode {
        val files = request.multiFileMap.values.flatten()
        val parameters = request.parameterMap
        if ((!debug && parameters.isNotEmpty()) || parameters.keys.any { it !in setOf("model", "snapshot") } ||
            parameters.values.any { it.size != 1 }) throw OcrFailure(422, "INVALID_REQUEST")
        val model = request.getParameter("model")
        if (model != null && model !in OcrProxy.DEBUG_MODELS) throw OcrFailure(422, "INVALID_DEBUG_MODEL")
        val snapshot = request.getParameter("snapshot")
        if (snapshot != null) {
            if (!debug || model == null || files.isNotEmpty()) throw OcrFailure(422, "INVALID_REQUEST")
            return proxy.replay(snapshot, model)
        }
        if (files.size != 1 || files[0].name != "image")
            throw OcrFailure(422, "INVALID_REQUEST")
        val file = files.single()
        if (file.size > 10L * 1024 * 1024) throw OcrFailure(413, "IMAGE_TOO_LARGE")
        val bytes = file.inputStream.use { it.readNBytes(10 * 1024 * 1024 + 1) }
        return proxy.scan(bytes, file.contentType.orEmpty(), debug, model)
    }

    @ExceptionHandler(OcrFailure::class)
    fun failure(error: OcrFailure, request: jakarta.servlet.http.HttpServletRequest, response: HttpServletResponse) {
        writeOcrError(response, error.status, error.code,
            request.getAttribute("ocrRequestId") as? String ?: UUID.randomUUID().toString())
    }
}
