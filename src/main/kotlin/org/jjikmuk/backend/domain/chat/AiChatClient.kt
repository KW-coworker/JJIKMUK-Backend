package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.chat.dto.AiChatRequestDto
import org.jjikmuk.backend.domain.chat.dto.ChatAnalysisContext
import org.jjikmuk.backend.global.exception.CustomException
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.beans.factory.annotation.Value
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.http.client.SimpleClientHttpRequestFactory
import org.springframework.stereotype.Component
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClient
import org.springframework.web.client.RestClientException
import tools.jackson.databind.json.JsonMapper
import java.net.HttpURLConnection
import java.net.URI

@Configuration
class AiChatClientConfig {
    @Bean("aiChatRestClient")
    fun aiChatRestClient(): RestClient {
        val factory = object : SimpleClientHttpRequestFactory() {
            override fun prepareConnection(connection: HttpURLConnection, httpMethod: String) {
                super.prepareConnection(connection, httpMethod)
                connection.instanceFollowRedirects = false
            }
        }.apply {
            setConnectTimeout(5000)
            setReadTimeout(30000)
        }
        return RestClient.builder().requestFactory(factory).build()
    }
}

/** Version/context acknowledgements prevent an old AI service silently ignoring new decisions.
 * They do not prove that generated prose is factually consistent with the decision.
 */
@Component
class AiChatClient(
    @Qualifier("aiChatRestClient") private val restClient: RestClient,
    @Value("\${chat.ai.url:http://localhost:8000/chat}") private val url: String,
    private val consentSigner: ExternalAiConsentSigner,
    @Value("\${chatbot.api-token:}") private val apiToken: String,
    @Value("\${chatbot.developer-test-auto-consent:false}") private val developerTestAutoConsent: Boolean = false
) {
    private val mapper = JsonMapper.builder().findAndAddModules().build()

    init {
        if (developerTestAutoConsent) {
            LoggerFactory.getLogger(AiChatClient::class.java).warn(
                "Developer test policy grants external AI processing for all authenticated chat requests; this is not per-user consent collection."
            )
        }
    }

    fun ask(request: AiChatRequestDto, ownerId: Long, externalAiConsent: Boolean): String {
        val endpoint = runCatching { URI(url) }.getOrNull()
        if (apiToken.isBlank() || apiToken.any { it.code !in 33..126 } || endpoint == null ||
            endpoint.scheme !in setOf("http", "https") || endpoint.host.isNullOrBlank() ||
            endpoint.userInfo != null || endpoint.rawPath != "/chat" || endpoint.rawQuery != null || endpoint.rawFragment != null) {
            throw CustomException(HttpStatus.SERVICE_UNAVAILABLE, "AI 서비스 인증 설정을 확인해주세요.", "AI_AUTH_UNAVAILABLE")
        }
        // Serialize once: hashing a DTO and then letting an HTTP converter serialize again can break the proof.
        val bytes = mapper.writeValueAsBytes(request)
        if (bytes.size > 1024 * 1024) {
            throw CustomException(HttpStatus.PAYLOAD_TOO_LARGE, "AI 요청 크기가 너무 큽니다.", "AI_REQUEST_TOO_LARGE")
        }
        // Temporary operator-approved developer test policy. Disabled by default.
        // Keep the original request value and all signature/identity checks intact.
        val proof = consentSigner.headers(bytes, ownerId, externalAiConsent || developerTestAutoConsent)
        val response = try {
            restClient.post().uri(url).contentType(MediaType.APPLICATION_JSON).accept(MediaType.APPLICATION_JSON)
                .header(CONTRACT_HEADER, request.analysisContext.contractVersion)
                .header(CONTEXT_HEADER, request.analysisContext.contextId)
                .header("X-Food-Chatbot-Token", apiToken)
                .headers { headers -> proof.forEach { (name, value) -> headers.set(name, value) } }
                .body(bytes).retrieve().toEntity(String::class.java)
        } catch (exception: ResourceAccessException) {
            throw CustomException(HttpStatus.SERVICE_UNAVAILABLE, "AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", "AI_SERVICE_UNAVAILABLE")
        } catch (exception: RestClientException) {
            // Do not expose upstream response bodies, URLs, profiles or credentials.
            throw CustomException(HttpStatus.BAD_GATEWAY, "AI 서비스 응답을 처리할 수 없습니다.", "AI_UPSTREAM_ERROR")
        }
        if (!response.statusCode.is2xxSuccessful) {
            throw CustomException(HttpStatus.BAD_GATEWAY, "AI 서비스 응답을 처리할 수 없습니다.", "AI_UPSTREAM_ERROR")
        }
        if (response.headers.getFirst(CONTRACT_HEADER) != ChatAnalysisContext.VERSION ||
            response.headers.getFirst(CONTEXT_HEADER) != request.analysisContext.contextId) {
            throw CustomException(HttpStatus.BAD_GATEWAY,
                "AI 서비스의 분석 계약 버전 확인이 필요합니다.", "AI_ANALYSIS_CONTRACT_MISMATCH")
        }
        val body = response.body
        if (body.isNullOrBlank() || !runCatching { mapper.readTree(body).isObject }.getOrDefault(false)) {
            throw CustomException(HttpStatus.BAD_GATEWAY, "AI 서비스가 올바른 JSON 응답을 반환하지 않았습니다.", "AI_RESPONSE_INVALID")
        }
        return body
    }

    companion object {
        const val CONTRACT_HEADER = "X-Jjikmuk-Analysis-Contract"
        const val CONTEXT_HEADER = "X-Jjikmuk-Analysis-Context"
    }
}
