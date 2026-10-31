package org.jjikmuk.backend.domain.auth

import com.google.api.client.json.gson.GsonFactory
import java.nio.charset.StandardCharsets.UTF_8
import java.security.KeyPairGenerator
import java.security.PrivateKey
import java.security.Signature
import java.time.Instant
import java.util.Base64

/** Ephemeral test keys only. Never reads Google credentials or contacts a remote service. */
internal object GoogleSignedTokenFixtures {
    const val CLIENT_ID = "unit-test-web.apps.googleusercontent.com"
    val json = GsonFactory.getDefaultInstance()
    val keys = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
    val otherKeys = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
    private val encoder = Base64.getUrlEncoder().withoutPadding()

    fun token(
        overrides: Map<String, Any?> = emptyMap(),
        now: Long = Instant.now().epochSecond,
        key: PrivateKey = keys.private,
        algorithm: String = "RS256"
    ): String {
        val claims = mutableMapOf<String, Any>(
            "iss" to "https://accounts.google.com", "aud" to CLIENT_ID,
            "sub" to "google-test-subject", "iat" to now - 10, "exp" to now + 3600,
            "email" to "google-test@example.com", "email_verified" to true
        )
        overrides.forEach { (field, value) -> if (value == null) claims.remove(field) else claims[field] = value }
        val header = encoder.encodeToString(json.toString(mapOf("alg" to algorithm, "typ" to "JWT", "kid" to "test-key")).toByteArray(UTF_8))
        val payload = encoder.encodeToString(json.toString(claims).toByteArray(UTF_8))
        val content = "$header.$payload"
        val signature = Signature.getInstance("SHA256withRSA").run {
            initSign(key)
            update(content.toByteArray(UTF_8))
            sign()
        }
        return "$content.${encoder.encodeToString(signature)}"
    }
}
