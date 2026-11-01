package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.chat.dto.*
import org.jjikmuk.backend.domain.user.AnalysisSelectionResponse
import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.Test
import org.springframework.http.HttpMethod
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.test.web.client.MockRestServiceServer
import org.springframework.test.web.client.match.MockRestRequestMatchers.*
import org.springframework.test.web.client.response.MockRestResponseCreators.*
import org.springframework.web.client.RestClient
import java.io.IOException
import kotlin.test.*

class AiChatClientTest {
    private val builder = RestClient.builder()
    private val server = MockRestServiceServer.bindTo(builder).build()
    private val client = AiChatClient(builder.build(), "http://ai.invalid/chat")
    private val request = AiChatRequestDto(null, emptyList(), null, "질문", emptyList(), ChatAnalysisContext(
        contextId = "context-test", policyVersion = "policy-test",
        selection = AnalysisSelectionResponse("none", false, false, emptyList()),
        effectiveConditions = null, productResolution = "NOT_PROVIDED", analysis = null, dataEvidence = null))
    private fun acknowledged(body: String = """{"answer":"확인해주세요"}""") = withSuccess(body, MediaType.APPLICATION_JSON)
        .header(AiChatClient.CONTRACT_HEADER, ChatAnalysisContext.VERSION)
        .header(AiChatClient.CONTEXT_HEADER, request.analysisContext.contextId)
    private fun error(code: String) {
        assertEquals(code, assertFailsWith<CustomException> { client.ask(request) }.code)
        server.verify()
    }

    @Test fun `sends structured JSON and returns acknowledged JSON unchanged`() {
        server.expect(requestTo("http://ai.invalid/chat")).andExpect(method(HttpMethod.POST))
            .andExpect(header(AiChatClient.CONTRACT_HEADER, ChatAnalysisContext.VERSION))
            .andExpect(header(AiChatClient.CONTEXT_HEADER, "context-test"))
            .andExpect(jsonPath("$.analysisContext.selection.mode").value("none"))
            .andExpect(jsonPath("$.analysisContext.historyIsAuthoritative").value(false))
            .andExpect(jsonPath("$.analysisContext.decisionAuthority").value("BACKEND"))
            .andRespond(acknowledged())
        assertEquals("""{"answer":"확인해주세요"}""", client.ask(request))
        server.verify()
    }
    @Test fun `legacy AI silently ignoring contract is blocked`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(withSuccess("""{"answer":"안전"}""", MediaType.APPLICATION_JSON))
        error("AI_ANALYSIS_CONTRACT_MISMATCH")
    }
    @Test fun `wrong version is blocked`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(withSuccess("{}", MediaType.APPLICATION_JSON)
            .header(AiChatClient.CONTRACT_HEADER, "old-v0").header(AiChatClient.CONTEXT_HEADER, "context-test"))
        error("AI_ANALYSIS_CONTRACT_MISMATCH")
    }
    @Test fun `v1 acknowledgement cannot silently accept the new individual snapshot contract`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(withSuccess("{}", MediaType.APPLICATION_JSON)
            .header(AiChatClient.CONTRACT_HEADER, "chat-analysis-v1").header(AiChatClient.CONTEXT_HEADER, "context-test"))
        error("AI_ANALYSIS_CONTRACT_MISMATCH")
    }
    @Test fun `real outgoing JSON carries names allergies request source and unique non-account profile identifiers`() {
        val profiles = listOf(
            ProfileDto(null, "엄마", "우유", null, null, null, "request:0", "CLIENT_REQUEST", 1, "provided"),
            ProfileDto(null, "아빠", "대두", null, null, null, "request:1", "CLIENT_REQUEST", 2, "provided"))
        val body = request.copy(profiles = profiles, analysisContext = request.analysisContext.copy(
            profileSource = "CLIENT_REQUEST", selection = AnalysisSelectionResponse("provided", true, false, emptyList())))
        server.expect(requestTo("http://ai.invalid/chat"))
            .andExpect(header(AiChatClient.CONTRACT_HEADER, "chat-analysis-v2"))
            .andExpect(jsonPath("$.profiles[0].nickname").value("엄마"))
            .andExpect(jsonPath("$.profiles[0].allergies").value("우유"))
            .andExpect(jsonPath("$.profiles[0].id").doesNotExist())
            .andExpect(jsonPath("$.profiles[0].profile_id").value(1))
            .andExpect(jsonPath("$.profiles[1].nickname").value("아빠"))
            .andExpect(jsonPath("$.profiles[1].target_type").value("provided"))
            .andExpect(jsonPath("$.analysisContext.profileSource").value("CLIENT_REQUEST"))
            .andRespond(acknowledged())
        client.ask(body); server.verify()
    }
    @Test fun `stale response context is blocked`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(withSuccess("{}", MediaType.APPLICATION_JSON)
            .header(AiChatClient.CONTRACT_HEADER, ChatAnalysisContext.VERSION).header(AiChatClient.CONTEXT_HEADER, "previous-question"))
        error("AI_ANALYSIS_CONTRACT_MISMATCH")
    }
    @Test fun `malformed body is blocked even with acknowledged contract`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(acknowledged("not json"))
        error("AI_RESPONSE_INVALID")
    }
    @Test fun `empty body is blocked`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(acknowledged(""))
        error("AI_RESPONSE_INVALID")
    }
    @Test fun `network failure becomes service unavailable`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(withException(IOException("private upstream detail")))
        val failure = assertFailsWith<CustomException> { client.ask(request) }
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, failure.status)
        assertEquals("AI_SERVICE_UNAVAILABLE", failure.code)
        assertFalse(failure.message.contains("private")); server.verify()
    }
    @Test fun `upstream errors do not expose upstream body`() {
        server.expect(requestTo("http://ai.invalid/chat")).andRespond(withServerError().body("private upstream detail"))
        val failure = assertFailsWith<CustomException> { client.ask(request) }
        assertEquals(HttpStatus.BAD_GATEWAY, failure.status)
        assertEquals("AI_UPSTREAM_ERROR", failure.code)
        assertFalse(failure.message.contains("private")); server.verify()
    }
}
