package org.jjikmuk.backend.global.config

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ProductDatasetMarkerTest {
    @Test
    fun `round trips versions containing Korean and separators`() {
        val marker = ProductDatasetMarker(
            version = "V4|한글 상품 데이터",
            sha256 = "a".repeat(64),
            rowCount = 1_348_425
        )

        assertEquals(marker, ProductDatasetMarker.decode(marker.encode()))
    }

    @Test
    fun `does not treat unrelated table comments as dataset markers`() {
        assertNull(ProductDatasetMarker.decode("legacy products table"))
        assertNull(ProductDatasetMarker.decode("jjikmuk-product-v1|broken"))
    }
}
