package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.beans.factory.annotation.Value
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Component
import java.security.MessageDigest
import java.time.Instant
import java.util.HexFormat
import java.util.UUID
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** v1 consent proof for the exact bytes of a v2 analysis request. No credentials in the body. */
@Component
class ExternalAiConsentSigner(
    @param:Value("\${chatbot.external-ai-consent-secret:}") private val secret: String
) {
    fun headers(body: ByteArray, ownerId: Long, granted: Boolean,
                timestamp: Long = Instant.now().epochSecond,
                nonce: String = UUID.randomUUID().toString()): Map<String, String> {
        if (secret.length < 32 || secret.any { it.code !in 33..126 }) {
            throw CustomException(HttpStatus.SERVICE_UNAVAILABLE,
                "AI 서비스 인증 설정을 확인해주세요.", "AI_AUTH_UNAVAILABLE")
        }
        require(ownerId > 0)
        val consent = if (granted) "granted" else "denied"
        val hex = HexFormat.of()
        val digest = hex.formatHex(MessageDigest.getInstance("SHA-256").digest(body))
        val canonical = listOf("v1", timestamp.toString(), "POST", "/chat", ownerId.toString(),
            consent, nonce, digest).joinToString("\n")
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return mapOf(
            "X-Food-Chatbot-User-Id" to ownerId.toString(),
            "X-Food-Chatbot-External-AI-Consent" to consent,
            "X-Food-Chatbot-External-AI-Timestamp" to timestamp.toString(),
            "X-Food-Chatbot-External-AI-Nonce" to nonce,
            "X-Food-Chatbot-External-AI-Signature" to hex.formatHex(mac.doFinal(canonical.toByteArray(Charsets.UTF_8)))
        )
    }
}
