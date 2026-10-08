package org.jjikmuk.backend.domain.product.search

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ProductSearchKeywordBuilderTest {
    @Test
    fun `stores original and compact product search terms`() {
        val keywords = ProductSearchKeywordBuilder.build(
            productName = " 단백질 칩 (매운맛) ",
            cleanProductName = "단백질 칩",
            manufacturer = "ABC 푸드"
        )

        assertTrue(keywords.contains("단백질 칩 (매운맛)"))
        assertTrue(keywords.contains("단백질칩매운맛"))
        assertTrue(keywords.contains("단백질칩"))
        assertTrue(keywords.contains("abc 푸드"))
        assertTrue(keywords.contains("abc푸드"))
    }

    @Test
    fun `normalizes no-space search input without boolean operators`() {
        assertEquals("매운새우깡", ProductSearchKeywordBuilder.normalizeQuery(" 매운-새우깡 "))
        assertEquals("두유바", ProductSearchKeywordBuilder.normalizeQuery("두유 바"))
        assertEquals("", ProductSearchKeywordBuilder.normalizeQuery(" +-* "))
        assertEquals("+\"매운새우깡\"", ProductSearchKeywordBuilder.toBooleanPhrase("매운 새우깡"))
    }

    @Test
    fun `normalizes display text separately from compact matching text`() {
        assertEquals("매운 새우깡", ProductSearchKeywordBuilder.normalizeForLog("  매운   새우깡  "))
    }

    @Test
    fun `does not include ingredient or allergy text`() {
        val keywords = ProductSearchKeywordBuilder.build(
            productName = "두유 바",
            cleanProductName = null,
            manufacturer = null
        )

        assertEquals("두유 바 두유바", keywords)
        assertFalse(keywords.contains("알레르기"))
    }
}
