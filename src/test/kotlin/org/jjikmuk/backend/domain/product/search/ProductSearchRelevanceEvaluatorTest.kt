package org.jjikmuk.backend.domain.product.search

import org.jjikmuk.backend.domain.product.Product
import kotlin.test.Test
import kotlin.test.assertEquals

class ProductSearchRelevanceEvaluatorTest {
    @Test
    fun `calculates hit rate reciprocal rank latency and pair overlap`() {
        val cases = listOf(
            ProductSearchRelevanceCase("compact", "두유바", setOf("두유바"), pairGroup = "soy"),
            ProductSearchRelevanceCase("spaced", "두유 바", setOf("두유바"), pairGroup = "soy"),
            ProductSearchRelevanceCase("miss", "없는상품", setOf("없는상품"))
        )
        val exact = Product(barcode = "A", productName = "두유 바")
        val noise = Product(barcode = "B", productName = "초콜릿")

        val report = ProductSearchRelevanceEvaluator.evaluate(cases) { case ->
            when (case.caseId) {
                "compact" -> TimedProducts(listOf(noise, exact), 100)
                "spaced" -> TimedProducts(listOf(exact), 200)
                else -> TimedProducts(emptyList(), 300)
            }
        }

        assertEquals(2.0 / 3.0, report.hitRateAtK)
        assertEquals(0.5, report.meanReciprocalRank)
        assertEquals(1.0 / 3.0, report.zeroResultRate)
        assertEquals(200.0, report.averageLatencyMicros)
        assertEquals(300, report.p95LatencyMicros)
        assertEquals(0.5, report.pairTopKOverlap.getValue("soy"))
    }

    @Test
    fun `space variants create the same telemetry query hash`() {
        val compact = ProductSearchPerformedEvent.create(
            userId = 1,
            endpoint = "SEARCH",
            query = "두유바",
            filters = emptySet(),
            matchMode = null,
            searchMode = "fulltext",
            resultCount = 3,
            latencyNanos = 1_000_000
        )
        val spaced = ProductSearchPerformedEvent.create(
            userId = 1,
            endpoint = "SEARCH",
            query = " 두유 바 ",
            filters = emptySet(),
            matchMode = null,
            searchMode = "fulltext",
            resultCount = 3,
            latencyNanos = 1_000_000
        )

        assertEquals(compact.compactQueryHash, spaced.compactQueryHash)
        assertEquals("두유 바", spaced.normalizedQuery)
        assertEquals(1_000, spaced.latencyMicros)
    }
}
