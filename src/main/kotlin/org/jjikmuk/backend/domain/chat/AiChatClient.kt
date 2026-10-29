package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.chat.dto.AiChatRequestDto
import org.jjikmuk.backend.domain.chat.dto.ChatAnalysisContext
import org.jjikmuk.backend.global.exception.CustomException
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

@Configuration
class AiChatClientConfig {
    @Bean("aiChatRestClient")
    fun aiChatRestClient(): RestClient {
        val factory = SimpleClientHttpRequestFactory().apply {
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
    @Value("\${chat.ai.url:http://localhost:8000/chat}") private val url: String
) {
    private val mapper = JsonMapper.builder().build()

    fun ask(request: AiChatRequestDto): String {
        val response = try {
            restClient.post().uri(url).contentType(MediaType.APPLICATION_JSON).accept(MediaType.APPLICATION_JSON)
                .header(CONTRACT_HEADER, request.analysisContext.contractVersion)
                .header(CONTEXT_HEADER, request.analysisContext.contextId)
                .body(request).retrieve().toEntity(String::class.java)
        } catch (exception: ResourceAccessException) {
            throw CustomException(HttpStatus.SERVICE_UNAVAILABLE, "AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", "AI_SERVICE_UNAVAILABLE")
        } catch (exception: RestClientException) {
            // Do not expose upstream response bodies, URLs, profiles or credentials.
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
