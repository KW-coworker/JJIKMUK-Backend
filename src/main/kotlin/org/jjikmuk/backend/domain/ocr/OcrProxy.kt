package org.jjikmuk.backend.domain.ocr

import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper
import java.net.InetAddress
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.ByteBuffer
import java.time.Duration
import java.util.UUID
import java.util.concurrent.CompletionStage
import java.util.concurrent.Flow
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

class OcrProxy(baseUrl: String, private val serviceToken: String) {
    companion object { val DEBUG_MODELS = setOf("gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol") }
    private val endpoint: URI?
    private val mapper = JsonMapper.builder().build()
    private val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10))
        .followRedirects(HttpClient.Redirect.NEVER).version(HttpClient.Version.HTTP_1_1).build()

    init {
        endpoint = if (baseUrl.isBlank()) null else {
            val uri = URI(baseUrl)
            val host = uri.host.orEmpty()
            val internal = host.matches(Regex("[0-9.]+")) &&
                InetAddress.getByName(host).let { it.isLoopbackAddress || it.isSiteLocalAddress }
            require(host.isNotBlank() && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null &&
                uri.path in listOf("", "/") && (uri.scheme == "https" || (uri.scheme == "http" && internal)))
            URI(baseUrl.trimEnd('/') + "/ocr")
        }
    }

    fun scan(bytes: ByteArray, mime: String, debug: Boolean = false, model: String? = null): JsonNode {
        if (model != null && (!debug || model !in DEBUG_MODELS)) throw OcrFailure(422, "INVALID_DEBUG_MODEL")
        if (bytes.isEmpty()) throw OcrFailure(422, "INVALID_IMAGE")
        if (bytes.size > 10 * 1024 * 1024) throw OcrFailure(413, "IMAGE_TOO_LARGE")
        val jpeg = bytes.size >= 3 && bytes[0] == 0xff.toByte() && bytes[1] == 0xd8.toByte() && bytes[2] == 0xff.toByte()
        val png = bytes.size >= 8 && bytes.take(8) == listOf(137,80,78,71,13,10,26,10).map { it.toByte() }
        if (!((mime == "image/jpeg" && jpeg) || (mime == "image/png" && png))) throw OcrFailure(415, "INVALID_IMAGE_TYPE")
        val target = endpoint ?: throw OcrFailure(503, "OCR_NOT_CONFIGURED")
        if (serviceToken.length < 32) throw OcrFailure(503, "OCR_NOT_CONFIGURED")
        val boundary = "ocr-" + UUID.randomUUID()
        val selectorPart = if (model == null) "" else "--$boundary\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n$model\r\n"
        val prefix = (selectorPart + "--$boundary\r\nContent-Disposition: form-data; name=\"image\"; filename=\"scan\"\r\nContent-Type: $mime\r\n\r\n").toByteArray()
        val suffix = "\r\n--$boundary--\r\n".toByteArray()
        val request = HttpRequest.newBuilder(if (debug) target.resolve("/ocr/debug") else target).timeout(Duration.ofSeconds(130))
            .header("X-OCR-Service-Token", serviceToken)
            .header("Content-Type", "multipart/form-data; boundary=$boundary")
            .POST(HttpRequest.BodyPublishers.ofByteArrays(listOf(prefix, bytes, suffix))).build()
        return execute(request, debug)
    }

    fun replay(snapshot: String, model: String): JsonNode {
        if (model !in DEBUG_MODELS) throw OcrFailure(422, "INVALID_DEBUG_MODEL")
        if (snapshot.isBlank() || snapshot.length > 330_000) throw OcrFailure(422, "INVALID_REQUEST")
        val target = endpoint ?: throw OcrFailure(503, "OCR_NOT_CONFIGURED")
        if (serviceToken.length < 32) throw OcrFailure(503, "OCR_NOT_CONFIGURED")
        val boundary = "ocr-" + UUID.randomUUID()
        val body = "--$boundary\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n$model\r\n" +
            "--$boundary\r\nContent-Disposition: form-data; name=\"snapshot\"\r\n\r\n$snapshot\r\n--$boundary--\r\n"
        val request = HttpRequest.newBuilder(target.resolve("/ocr/debug")).timeout(Duration.ofSeconds(130))
            .header("X-OCR-Service-Token", serviceToken).header("Content-Type", "multipart/form-data; boundary=$boundary")
            .POST(HttpRequest.BodyPublishers.ofString(body)).build()
        return execute(request, true)
    }

    private fun execute(request: HttpRequest, debug: Boolean): JsonNode {
        // Bound both body size and full completion time. No redirect or retry loop.
        val pending = client.sendAsync(request) { LimitedBody(1024 * 1024) }
        val response = try { pending.get(135, TimeUnit.SECONDS) }
        catch (_: TimeoutException) { pending.cancel(true); throw OcrFailure(504, "OCR_TIMEOUT_OUTCOME_UNKNOWN") }
        catch (_: InterruptedException) { pending.cancel(true); Thread.currentThread().interrupt(); throw OcrFailure(503, "OCR_INTERRUPTED") }
        catch (_: Exception) { pending.cancel(true); throw OcrFailure(502, "OCR_UPSTREAM_FAILED") }
        if (response.statusCode() != 200) {
            val status = response.statusCode().takeIf { it in setOf(400,408,413,415,422,429,503,504) } ?: 502
            throw OcrFailure(status, "OCR_UPSTREAM_REJECTED")
        }
        try {
            val root = mapper.readTree(response.body())
            require(root.isObject && root["message"]?.isString == true && root["data"]?.isObject == true)
            val data = root["data"]
            if (debug) {
                require(data["schemaVersion"]?.stringValue() == "ocr-debug-v1")
                require(data["status"]?.stringValue() in setOf("OK", "NO_TEXT", "FAILED"))
                require(data["ocr"]?.isObject == true && data["selector"]?.isObject == true)
                return root
            }
            require(data["status"]?.stringValue() in setOf("OK", "NO_TEXT", "NO_SEARCH_KEYWORD"))
            for (key in listOf("productName", "brand", "flavor", "totalWeight", "searchKeyword")) {
                val value = data[key]
                require(value == null || value.isNull || (value.isString && value.stringValue().length <= 3000))
            }
            val keyword = data["searchKeyword"]
            if (data["status"].stringValue() == "OK") require(keyword?.isString == true && keyword.stringValue().length in 2..100)
            return root
        } catch (_: Exception) { throw OcrFailure(502, "INVALID_OCR_RESPONSE") }
    }
}

private class LimitedBody(private val limit: Int) : HttpResponse.BodySubscriber<ByteArray> {
    private val delegate = HttpResponse.BodySubscribers.ofByteArray()
    private lateinit var subscription: Flow.Subscription
    private var received = 0L
    override fun getBody(): CompletionStage<ByteArray> = delegate.body
    override fun onSubscribe(value: Flow.Subscription) { subscription = value; delegate.onSubscribe(value) }
    override fun onNext(items: List<ByteBuffer>) {
        received += items.sumOf { it.remaining().toLong() }
        if (received > limit) {
            subscription.cancel()
            delegate.onError(IllegalStateException("Response size limit"))
        } else delegate.onNext(items)
    }
    override fun onError(error: Throwable) = delegate.onError(error)
    override fun onComplete() = delegate.onComplete()
}
