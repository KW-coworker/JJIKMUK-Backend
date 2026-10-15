package org.jjikmuk.backend.domain.product

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class ProductCapacityTest {
    @Test
    fun `equal mass capacities collapse across units case spaces and decimal scales`() {
        val expected = ProductCapacity.parse("1000g")
        listOf("1kg", "1,000 g", "1000.000G", "１０００ｇ", "1㎏", "총 내용량: 1000그램", "1000000mg")
            .forEach { assertEquals(expected, ProductCapacity.parse(it), it) }
        assertEquals("g:1000", expected.key)
        assertEquals("1000g", expected.label)
    }

    @Test
    fun `volume is normalized but never converted to mass`() {
        assertEquals(ProductCapacity.parse("1L"), ProductCapacity.parse("1000 ml"))
        assertEquals(ProductCapacity.parse("1ℓ"), ProductCapacity.parse("1000밀리리터"))
        assertNotEquals(ProductCapacity.parse("1000ml"), ProductCapacity.parse("1000g"))
        assertEquals("ml:1000", ProductCapacity.parse("1L").key)
    }

    @Test
    fun `only explicit multipacks are reduced to total capacity`() {
        listOf("50g x 2", "50g×2개", "50g*2봉", "총중량 0.1kg").forEach {
            assertEquals(ProductCapacity.parse("100g"), ProductCapacity.parse(it), it)
        }
        assertEquals("g:0.25", ProductCapacity.parse("250mg").key)
    }

    @Test
    fun `missing invalid or ambiguous values share one unknown option`() {
        listOf(null, "", " ", "정보없음", "100", "0g", "-1g", "50~100g", "10,00g", "1e3g",
            "100g(50gx2)", "50gx0", "50g+50g", "약100g", "a".repeat(129)).forEach {
            assertEquals("unknown", ProductCapacity.parse(it).key, it)
        }
        assertEquals("용량 정보 없음", ProductCapacity.parse(null).label)
    }
}
