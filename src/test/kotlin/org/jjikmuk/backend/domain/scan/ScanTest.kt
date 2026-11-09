package org.jjikmuk.backend.domain.scan

import com.sun.net.httpserver.HttpServer
import jakarta.servlet.FilterChain
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.global.config.ProductDatasetMarker
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.*
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse
import org.springframework.mock.web.MockMultipartFile
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.authority.SimpleGrantedAuthority
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import tools.jackson.databind.json.JsonMapper
import java.net.InetSocketAddress
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

class ScanTest {
    private val scanId = UUID.randomUUID().toString()
    private val requestId = UUID.randomUUID().toString()
    private val version = "fixture-v1"
    private val sha = "a".repeat(64)
    private val mapper = JsonMapper.builder().build()
    private val image = byteArrayOf(255.toByte(), 216.toByte(), 255.toByte(), 0)
    private fun candidateJson() = """{"schemaVersion":"scan-candidates-v1","scanId":"$scanId","requestId":"$requestId","catalogVersion":"$version","status":"MATCHES_FOUND","method":"LOCAL_OCR_MATCHING","gptUsed":false,"dbAbsenceConfirmed":false,"candidates":[{"productId":2,"barcode":"NO_BARCODE_ROW_2","sourceProductName":"새우칩","sourceManufacturer":"제조사"}]}"""
    private fun decoded() = parseCandidates(mapper.readTree(candidateJson()), scanId, requestId, version)
    private fun login() { SecurityContextHolder.getContext().authentication = UsernamePasswordAuthenticationToken(7L, null, listOf(SimpleGrantedAuthority("ROLE_USER"))) }
    @AfterEach fun clear() { SecurityContextHolder.clearContext() }

    @Test fun `UUID must be canonical v4`() {
        assertTrue(validScanId(scanId))
        for (bad in listOf("foo", "1-1-1-1-1", UUID(0, 0).toString(), scanId.uppercase())) assertFalse(validScanId(bad))
    }
    @Test fun `strict private response rejects mismatches coercion duplicate and absent candidates`() {
        assertEquals(2L, decoded().candidates.single().productId)
        val original = candidateJson()
        val bad = listOf(original.replace(scanId, UUID.randomUUID().toString()),
            original.replace(requestId, UUID.randomUUID().toString()), original.replace(version, "other"),
            original.replace("\"productId\":2", "\"productId\":2.1"), original.replace("\"productId\":2", "\"productId\":\"2\""),
            original.replace("\"gptUsed\":false", "\"gptUsed\":true"), original.replace("\"dbAbsenceConfirmed\":false", "\"dbAbsenceConfirmed\":true"),
            original.replace("MATCHES_FOUND", "MANUAL_SEARCH_REQUIRED"), original.replace("NO_BARCODE_ROW_2", ""))
        for (json in bad) assertEquals(502, assertThrows(ScanFailure::class.java) { parseCandidates(mapper.readTree(json), scanId, requestId, version) }.status)
        val duplicate = mapper.readTree(original) as tools.jackson.databind.node.ObjectNode
        val rows = duplicate["candidates"] as tools.jackson.databind.node.ArrayNode
        rows.add(rows[0])
        assertThrows(ScanFailure::class.java) { parseCandidates(duplicate, scanId, requestId, version) }
    }
    @Test fun `private authentication and malformed or oversized replies never retry`() {
        for ((status, body) in listOf(401 to "{}", 302 to "{}", 500 to "private-secret", 200 to "{}", 200 to "x".repeat(1048577))) {
            upstream(status, body) { proxy, count ->
                val error = assertThrows(ScanFailure::class.java) { proxy.scan(image,"image/jpeg",7,scanId,requestId,version,false) }
                assertEquals(502,error.status); assertEquals(1,count.get()); assertFalse(error.message!!.contains("private-secret"))
            }
        }
    }
    @Test fun `trusted owner request metadata and fallback flag reach private route once`() = upstream(200,candidateJson()) { proxy,count ->
        assertEquals(decoded(),proxy.scan(image,"image/jpeg",7,scanId,requestId,version,false))
        assertEquals(1,count.get())
    }
    private fun upstream(status:Int,body:String,block:(ScanProxy,AtomicInteger)->Unit) {
        val count=AtomicInteger(); val server=HttpServer.create(InetSocketAddress("127.0.0.1",0),0)
        server.createContext("/scan-products") { exchange ->
            count.incrementAndGet()
            assertEquals("7",exchange.requestHeaders.getFirst("X-Scan-Owner-ID"))
            assertEquals(scanId,exchange.requestHeaders.getFirst("Idempotency-Key"))
            assertEquals(requestId,exchange.requestHeaders.getFirst("X-Request-ID"))
            assertEquals("false",exchange.requestHeaders.getFirst("X-Scan-Allow-Image-Fallback"))
            assertNull(exchange.requestHeaders.getFirst("Authorization"))
            exchange.requestBody.readAllBytes()
            val bytes=body.toByteArray(); exchange.sendResponseHeaders(status,bytes.size.toLong())
            try { exchange.responseBody.use { it.write(bytes) } } catch (_:Exception) {} finally { exchange.close() }
        }; server.start()
        try { block(ScanProxy("http://127.0.0.1:${server.address.port}","fixture-internal-token-32-characters"),count) }
        finally { server.stop(0) }
    }
    private fun catalog(): Triple<ScanCatalog,ProductRepository,JdbcTemplate> {
        val jdbc=mock(JdbcTemplate::class.java); val repo=mock(ProductRepository::class.java)
        `when`(jdbc.queryForObject(anyString(),eq(String::class.java))).thenReturn(ProductDatasetMarker(version,sha,2).encode())
        return Triple(ScanCatalog(jdbc,repo,version,sha,2),repo,jdbc)
    }
    @Test fun `batch hydration restores rank and rejects changed names ids missing rows and marker`() {
        val (cat,repo,jdbc)=catalog()
        val first=Product("NO_BARCODE_ROW_2",productName="새우칩",manufacturer="제조사",productId=2)
        val second=Product("123",productName="새우칩 매운맛",productId=3)
        `when`(repo.findAllById(listOf(first.barcode,second.barcode))).thenReturn(listOf(second,first))
        val input=decoded().copy(candidates=decoded().candidates+ScanCandidate(3,"123","새우칩 매운맛",null))
        val result=cat.hydrate(input,requestId)
        assertEquals(listOf(2L,3L),result.data.products.map { it.product.productId }); assertTrue(result.data.products.all { it.analysis==null })
        verify(repo,times(1)).findAllById(listOf(first.barcode,second.barcode)); verifyNoMoreInteractions(repo)
        val serialized = mapper.readTree(mapper.writeValueAsBytes(result))
        assertTrue(serialized["data"]["products"][0]["analysis"].isNull)
        assertTrue(serialized["data"]["products"][0]["product"]["imageUrl"].isNull)
        for (changed in listOf(Product(first.barcode,productName="다른상품",manufacturer="제조사",productId=2),
            Product(first.barcode,productName="새우칩",manufacturer="제조사",productId=200),
            Product(first.barcode,productName="새우칩",manufacturer="다른제조사",productId=2))) {
            `when`(repo.findAllById(listOf(first.barcode,second.barcode))).thenReturn(listOf(changed,second))
            assertEquals("CATALOG_MISMATCH",assertThrows(ScanFailure::class.java){cat.hydrate(input,requestId)}.code)
        }
        `when`(repo.findAllById(listOf(first.barcode,second.barcode))).thenReturn(listOf(first))
        assertEquals("CATALOG_MISMATCH",assertThrows(ScanFailure::class.java){cat.hydrate(input,requestId)}.code)
        `when`(jdbc.queryForObject(anyString(),eq(String::class.java))).thenReturn("")
        assertEquals("CATALOG_MISMATCH",assertThrows(ScanFailure::class.java){cat.verifiedVersion()}.code)
    }
    @Test fun `new guard requires JWT and flag with safe flat failures`() {
        val request=MockHttpServletRequest("POST","/api/product-scans").apply {
            contentType="multipart/form-data; boundary=x"; addHeader("Idempotency-Key",scanId)
        }
        val unauthorized=MockHttpServletResponse()
        ScanGuard(true).doFilter(request,unauthorized,FilterChain{_,_->fail("anonymous")})
        assertEquals(401,unauthorized.status); assertTrue(unauthorized.contentAsString.contains("\"status\":401"))
        login(); val disabled=MockHttpServletResponse()
        ScanGuard(false).doFilter(request,disabled,FilterChain{_,_->fail("disabled")})
        assertEquals(503,disabled.status)
        val guard=ScanGuard(true); val ok=MockHttpServletResponse()
        guard.doFilter(request,ok,FilterChain{_,_->})
        val busy=MockHttpServletResponse(); guard.doFilter(request,busy,FilterChain{_,_->fail("cooldown")})
        assertEquals(429,busy.status); assertEquals("no-store",ok.getHeader("Cache-Control"))
    }
    @Test fun `controller rejects extra user fields before calling OCR`() {
        login()
        val proxy=mock(ScanProxy::class.java); val (catalog,_,_)=catalog()
        val mvc=MockMvcBuilders.standaloneSetup(ScanController(proxy,catalog,false,"")).build()
        val result=mvc.perform(multipart("/api/product-scans").file(MockMultipartFile("image","a.jpg","image/jpeg",image))
            .header("Idempotency-Key",scanId).param("model","arbitrary")).andReturn().response
        assertEquals(400,result.status); verifyNoInteractions(proxy)
    }
}
