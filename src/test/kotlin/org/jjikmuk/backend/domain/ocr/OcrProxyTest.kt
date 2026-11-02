package org.jjikmuk.backend.domain.ocr

import com.sun.net.httpserver.HttpServer
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.springframework.mock.web.MockMultipartFile
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart
import org.springframework.test.web.servlet.setup.MockMvcBuilders
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicInteger

class OcrProxyTest {
    private val image = byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 0x00)
    private val json = """{"message":"OCR done","data":{"status":"OK","productName":"tea","searchKeyword":"tea","requestId":"abc"}}"""
    private fun upstream(status: Int = 200, body: String = json, path: String = "/ocr", inspectBody: (String) -> Unit = {}, block: (OcrProxy, AtomicInteger) -> Unit) {
        val count = AtomicInteger()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/ocr") { exchange ->
            count.incrementAndGet()
            assertEquals("POST", exchange.requestMethod)
            assertEquals(path, exchange.requestURI.path)
            assertEquals("internal-test-service-token-32chars", exchange.requestHeaders.getFirst("X-OCR-Service-Token"))
            assertNull(exchange.requestHeaders.getFirst("X-OCR-Test-Token"))
            assertNull(exchange.requestHeaders.getFirst("Authorization"))
            inspectBody(exchange.requestBody.readAllBytes().toString(Charsets.UTF_8))
            exchange.responseHeaders.set("Content-Type", "application/json")
            val bytes = body.toByteArray()
            exchange.sendResponseHeaders(status, bytes.size.toLong())
            try { exchange.responseBody.use { it.write(bytes) } } catch (_: Exception) { }
            exchange.close()
        }
        server.start()
        try { block(OcrProxy("http://127.0.0.1:${server.address.port}", "internal-test-service-token-32chars"), count) }
        finally { server.stop(0) }
    }

    @Test fun `valid image returns one wrapper and only internal token reaches upstream`() = upstream { proxy, count ->
        val result = proxy.scan(image, "image/jpeg")
        assertEquals("tea", result["data"]["searchKeyword"].stringValue())
        assertEquals(1, count.get())
    }

    @Test fun `debug route returns partial failures without retrying OCR`() = upstream(body=
        """{"message":"diagnostic","data":{"schemaVersion":"ocr-debug-v1","status":"FAILED","ocr":{"candidates":[]},"selector":{},"error":{"stage":"selector","code":"LLM_TIMEOUT"}}}""",
        path="/ocr/debug") { proxy, count ->
        val result=proxy.scan(image,"image/jpeg",true)
        assertEquals("FAILED",result["data"]["status"].stringValue())
        assertEquals(1,count.get())
    }

    @Test fun `invalid images and content types never call upstream`() = upstream { proxy, count ->
        for ((bytes, type) in listOf(byteArrayOf() to "image/jpeg", image to "text/plain", byteArrayOf(1,2,3) to "image/png")) {
            assertThrows(OcrFailure::class.java) { proxy.scan(bytes, type) }
        }
        assertEquals(0, count.get())
    }

    @Test fun `upstream failures redirects malformed JSON and huge bodies are not retried`() {
        for ((status, body) in listOf(503 to "private detail", 302 to "redirect", 200 to "{broken", 200 to "{\"data\":{}}", 200 to "x".repeat(1024*1024+1))) {
            upstream(status, body) { proxy, count ->
                val error = assertThrows(OcrFailure::class.java) { proxy.scan(image, "image/jpeg") }
                assertTrue(error.status in listOf(502, 503))
                assertFalse(error.message!!.contains("private"))
                assertEquals(1, count.get())
            }
        }
    }

    @Test fun `multipart endpoint rejects fields and extra files and accepts image`() = upstream { proxy, count ->
        val mvc = MockMvcBuilders.standaloneSetup(OcrController(proxy)).build()
        val file = MockMultipartFile("image", "scan.jpg", "image/jpeg", image)
        val good = mvc.perform(multipart("/api/ocr").file(file)).andReturn().response
        assertEquals(200, good.status)
        assertTrue(good.contentAsString.contains("searchKeyword"))
        val extra = mvc.perform(multipart("/api/ocr").file(file).param("keyword", "forged")).andReturn().response
        assertEquals(422, extra.status)
        val two = mvc.perform(multipart("/api/ocr").file(file).file(file)).andReturn().response
        assertEquals(422, two.status)
        assertEquals(1, count.get())
    }

    @Test fun `URL config forbids credentials metadata public plaintext and extra path`() {
        for (url in listOf("http://169.254.169.254", "http://8.8.8.8", "https://user:pass@example.com", "http://127.0.0.1/path")) {
            assertThrows(IllegalArgumentException::class.java) { OcrProxy(url, "test-token") }
        }
    }

    @Test fun `snapshot replay sends one selected model and no image`() = upstream(body=
        """{"message":"debug","data":{"schemaVersion":"ocr-debug-v1","status":"OK","ocr":{},"selector":{}}}""",
        path="/ocr/debug", inspectBody={ body ->
            assertTrue(body.contains("gpt-6.1-sol"))
            assertTrue(body.contains("name=\"snapshot\""))
            assertFalse(body.contains("filename="))
        }) { proxy, count ->
        val mvc=MockMvcBuilders.standaloneSetup(OcrController(proxy)).build()
        assertEquals(200,mvc.perform(multipart("/api/ocr/debug").param("model","gpt-6.1-sol").param("snapshot","signed-fixture")).andReturn().response.status)
        assertEquals(1,count.get())
    }

    @Test fun `model injection and mixed replay inputs fail without upstream calls`() = upstream { proxy, count ->
        val mvc=MockMvcBuilders.standaloneSetup(OcrController(proxy)).build()
        val file=MockMultipartFile("image","scan.jpg","image/jpeg",image)
        assertEquals(422,mvc.perform(multipart("/api/ocr").file(file).param("model","gpt-6.1-sol")).andReturn().response.status)
        assertEquals(422,mvc.perform(multipart("/api/ocr/debug").file(file).param("model","unknown")).andReturn().response.status)
        assertEquals(422,mvc.perform(multipart("/api/ocr/debug").file(file).param("model","gpt-6-luna").param("snapshot","x")).andReturn().response.status)
        assertEquals(422,mvc.perform(multipart("/api/ocr/debug").param("model","gpt-6-luna","gpt-6.1-sol").param("snapshot","x")).andReturn().response.status)
        assertThrows(OcrFailure::class.java) { proxy.scan(image,"image/jpeg",false,"gpt-6.1-sol") }
        assertEquals(0,count.get())
    }
}
