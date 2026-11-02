package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.chat.dto.ChatRequestDto
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.Test
import tools.jackson.databind.json.JsonMapper
import kotlin.test.*

class ExternalAiConsentSignerTest {
    private val mapper = JsonMapper.builder().findAndAddModules().build()
    private val fixture = mapper.readTree(javaClass.getResourceAsStream("/chat-external-ai-consent-v1.json"))

    @Test fun `Kotlin matches the AI Python verifier golden UTF8 proof`() {
        val headers = ExternalAiConsentSigner(fixture["secret"].asText()).headers(
            fixture["body"].asText().toByteArray(Charsets.UTF_8), 42, true,
            fixture["timestamp"].asLong(), fixture["nonce"].asText())
        assertEquals(fixture["signature"].asText(), headers["X-Food-Chatbot-External-AI-Signature"])
        assertEquals("42", headers["X-Food-Chatbot-User-Id"])
        assertEquals("granted", headers["X-Food-Chatbot-External-AI-Consent"])
    }

    @Test fun `body owner and denied consent each change the signature`() {
        val signer = ExternalAiConsentSigner(fixture["secret"].asText())
        fun proof(body: String = "가족", owner: Long = 42, granted: Boolean = true) =
            signer.headers(body.toByteArray(Charsets.UTF_8), owner, granted, 1000, "fixed-test-nonce-1234")
        assertEquals(4, setOf(proof(), proof("가족 "), proof(owner = 43), proof(granted = false)).size)
        assertEquals("denied", proof(granted = false)["X-Food-Chatbot-External-AI-Consent"])
        assertNotEquals(signer.headers(byteArrayOf(), 42, true), signer.headers(byteArrayOf(), 42, true))
    }

    @Test fun `missing short or multiline secrets fail closed even for denied consent`() {
        for (secret in listOf("", "short", "x".repeat(32) + "\n")) {
            for (granted in listOf(false, true)) {
                val error = assertFailsWith<CustomException> {
                    ExternalAiConsentSigner(secret).headers(byteArrayOf(), 42, granted)
                }
                assertEquals("AI_AUTH_UNAVAILABLE", error.code)
            }
        }
    }

    @Test fun `omission null and false deny while only literal true grants consent`() {
        for (suffix in listOf("", ",\"externalAiConsent\":false", ",\"externalAiConsent\":null")) {
            assertFalse(mapper.readValue("""{"message":"질문"$suffix}""", ChatRequestDto::class.java).externalAiConsent)
        }
        assertTrue(mapper.readValue("""{"message":"질문","externalAiConsent":true}""", ChatRequestDto::class.java).externalAiConsent)
        for (value in listOf("1", "0", "\"true\"", "\"false\"", "{}", "[]")) {
            assertFails { mapper.readValue("""{"message":"질문","externalAiConsent":$value}""", ChatRequestDto::class.java) }
        }
    }
}
