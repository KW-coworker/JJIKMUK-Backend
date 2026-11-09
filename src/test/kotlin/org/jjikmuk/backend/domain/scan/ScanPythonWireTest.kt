package org.jjikmuk.backend.domain.scan

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.global.config.ProductDatasetMarker
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable
import org.mockito.Mockito.*
import org.springframework.jdbc.core.JdbcTemplate
import tools.jackson.databind.json.JsonMapper
import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import java.nio.file.Files
import java.nio.file.Path
import javax.imageio.ImageIO

/** Optional loopback test with the separately launched Python service. No real DB/model/API. */
@EnabledIfEnvironmentVariable(named="SCAN_TEST_OCR_URL",matches="http://127\\.0\\.0\\.1:[0-9]+")
class ScanPythonWireTest {
    @Test fun `Python decoder matcher ledger to Kotlin proxy hydration generates Android fixture`() {
        val scanId="d4e760c2-977a-4f06-989e-3ee1f3716268"
        val requestId="f360f06f-04f5-44a8-a053-6c754dc98829"
        val bytes=ByteArrayOutputStream().also { ImageIO.write(BufferedImage(20,20,BufferedImage.TYPE_INT_RGB),"jpg",it) }.toByteArray()
        val proxy=ScanProxy(System.getenv("SCAN_TEST_OCR_URL"),"fixture-internal-token-32-characters")
        val value=proxy.scan(bytes,"image/jpeg",7,scanId,requestId,"fixture-v1",false)
        assertEquals("MATCHES_FOUND",value.status); assertFalse(value.gptUsed)
        assertEquals(listOf(2L,3L),value.candidates.map { it.productId })
        val repeated=proxy.scan(bytes,"image/jpeg",7,scanId,requestId,"fixture-v1",false)
        assertEquals(value,repeated)
        val jdbc=mock(JdbcTemplate::class.java);val repository=mock(ProductRepository::class.java)
        `when`(jdbc.queryForObject(anyString(),eq(String::class.java))).thenReturn(ProductDatasetMarker("fixture-v1","a".repeat(64),2).encode())
        `when`(repository.findAllById(value.candidates.map { it.barcode })).thenReturn(value.candidates.reversed().map {
            Product(it.barcode,productName=it.sourceProductName,manufacturer=it.sourceManufacturer,productId=it.productId)
        })
        val result=ScanCatalog(jdbc,repository,"fixture-v1","a".repeat(64),2).hydrate(value,requestId)
        assertEquals(value.candidates.map { it.barcode },result.data.products.map { it.product.barcode })
        val output=Path.of(requireNotNull(System.getenv("SCAN_TEST_PUBLIC_OUTPUT")))
        Files.createDirectories(output.parent)
        Files.write(output,JsonMapper.builder().build().writeValueAsBytes(result))
    }
}
