package org.jjikmuk.backend.domain.scan

import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component
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

@Component
class ScanProxy(@param:Value("\${ocr.proxy.base-url:}") baseUrl: String,
                @param:Value("\${ocr.proxy.service-token:}") private val token: String) {
    private val target = if (baseUrl.isBlank()) null else URI(baseUrl).let { uri ->
        val internal = uri.host.orEmpty().matches(Regex("[0-9.]+")) &&
            InetAddress.getByName(uri.host).let { it.isLoopbackAddress || it.isSiteLocalAddress }
        require(uri.host != null && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null &&
            uri.path in listOf("", "/") && (uri.scheme == "https" || (uri.scheme == "http" && internal)))
        uri.resolve("/scan-products")
    }
    private val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10))
        .followRedirects(HttpClient.Redirect.NEVER).version(HttpClient.Version.HTTP_1_1).build()
    private val mapper = JsonMapper.builder().build()

    fun scan(image: ByteArray, mime: String, owner: Long, scanId: String, requestId: String,
             version: String, allowImageFallback: Boolean): ScanCandidates {
        if (target == null || token.length < 32) throw ScanFailure(503, "INDEX_NOT_READY")
        if (image.isEmpty()) throw ScanFailure(422, "INVALID_IMAGE")
        if (image.size > 10 * 1024 * 1024) throw ScanFailure(413, "IMAGE_TOO_LARGE")
        val jpeg = image.take(3) == listOf(255, 216, 255).map { it.toByte() }
        val png = image.take(8) == listOf(137,80,78,71,13,10,26,10).map { it.toByte() }
        if (!((mime == "image/jpeg" && jpeg) || (mime == "image/png" && png))) throw ScanFailure(415, "UNSUPPORTED_IMAGE")
        val boundary = "scan-" + UUID.randomUUID()
        val prefix = "--$boundary\r\nContent-Disposition: form-data; name=\"image\"; filename=\"scan\"\r\nContent-Type: $mime\r\n\r\n".toByteArray()
        val suffix = "\r\n--$boundary--\r\n".toByteArray()
        val request = HttpRequest.newBuilder(target).timeout(Duration.ofSeconds(130))
            .header("X-OCR-Service-Token", token).header("X-Request-ID", requestId)
            .header("Idempotency-Key", scanId).header("X-Scan-Owner-ID", owner.toString())
            .header("X-Scan-Catalog-Version", version)
            .header("X-Scan-Allow-Image-Fallback", allowImageFallback.toString())
            .header("Content-Type", "multipart/form-data; boundary=$boundary")
            .POST(HttpRequest.BodyPublishers.ofByteArrays(listOf(prefix, image, suffix))).build()
        val pending = client.sendAsync(request) { ScanLimitedBody() }
        val response = try { pending.get(135, TimeUnit.SECONDS) }
        catch (_: TimeoutException) { pending.cancel(true); throw ScanFailure(504, "SCAN_TIMEOUT_OUTCOME_UNKNOWN") }
        catch (_: InterruptedException) { pending.cancel(true); Thread.currentThread().interrupt(); throw ScanFailure(503, "SCAN_UPSTREAM_FAILED") }
        catch (_: Exception) { pending.cancel(true); throw ScanFailure(502, "SCAN_UPSTREAM_FAILED") }
        val root = try { mapper.readTree(response.body()) } catch (_: Exception) { throw ScanFailure(502, "SCAN_UPSTREAM_INVALID_RESPONSE") }
        if (response.statusCode() != 200) {
            // Whitelist status/code pairs: private 401 must never log the user out.
            val code = root?.get("error")?.get("code")?.stringValue()
            val allowed = mapOf("INVALID_REQUEST" to 400, "IDEMPOTENCY_KEY_REUSED" to 409,
                "SCAN_IN_PROGRESS" to 409, "SCAN_OUTCOME_UNKNOWN" to 409, "IMAGE_TOO_LARGE" to 413,
                "UNSUPPORTED_IMAGE" to 415, "INVALID_IMAGE" to 422, "SCAN_BUSY" to 429,
                "INDEX_NOT_READY" to 503, "CATALOG_MISMATCH" to 503, "SCAN_DISABLED" to 503,
                "SCAN_TIMEOUT_OUTCOME_UNKNOWN" to 504)
            if (code in allowed && allowed[code] == response.statusCode()) throw ScanFailure(response.statusCode(), code!!)
            throw ScanFailure(502, "SCAN_UPSTREAM_FAILED")
        }
        return parseCandidates(root ?: throw ScanFailure(502, "SCAN_UPSTREAM_INVALID_RESPONSE"), scanId, requestId, version)
    }
}

private class ScanLimitedBody : HttpResponse.BodySubscriber<ByteArray> {
    private val delegate = HttpResponse.BodySubscribers.ofByteArray()
    private lateinit var subscription: Flow.Subscription
    private var bytes = 0L
    override fun getBody(): CompletionStage<ByteArray> = delegate.body
    override fun onSubscribe(value: Flow.Subscription) { subscription = value; delegate.onSubscribe(value) }
    override fun onNext(items: List<ByteBuffer>) {
        bytes += items.sumOf { it.remaining().toLong() }
        if (bytes > 1024 * 1024) { subscription.cancel(); delegate.onError(IllegalStateException("Scan response limit")) }
        else delegate.onNext(items)
    }
    override fun onError(error: Throwable) = delegate.onError(error)
    override fun onComplete() = delegate.onComplete()
}
