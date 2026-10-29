package org.jjikmuk.backend.domain.product

import org.junit.jupiter.api.Test
import kotlin.test.*

class ProductCategoryPolicyTest {
    @Test fun `multi label categories keep all matches and unclassified is exclusive`() {
        assertEquals(listOf("convenience", "meat"), ProductClassificationCatalog.foodCategoryIds("convenience|meat|미분류"))
        assertEquals(listOf("unclassified"), ProductClassificationCatalog.foodCategoryIds("invalid"))
        assertEquals(listOf("unclassified"), ProductClassificationCatalog.foodCategoryIds(null))
    }
    @Test fun `sauce is not pickle and dumpling is not meat ingredient`() {
        assertEquals(CategoryCompatibility.MISMATCH, ProductCategoryPolicy.compare(
            Product("a", productName = "초고추장", foodType = "소스"), Product("b", productName = "고추장아찌무침", foodType = "절임식품")).status)
        assertEquals(CategoryCompatibility.MISMATCH, ProductCategoryPolicy.compare(
            Product("a", productName = "닭가슴살물만두"), Product("b", productName = "닭가슴살", foodType = "양념육")).status)
    }
    @Test fun `cross category drinks may substitute and unknown is not forced into a category`() {
        assertEquals(CategoryCompatibility.MATCH, ProductCategoryPolicy.compare(
            Product("a", foodType = "가공유", foodCategories = "dairy"), Product("b", foodType = "두유", foodCategories = "beverage")).status)
        val unknown = Product("u", productName = "King Bowl(김치)", foodCategories = "sides")
        assertEquals(ProductUse.UNKNOWN, unknown.categoryAssessment.usage)
        assertTrue(unknown.categoryAssessment.needsReview)
        assertEquals(CategoryCompatibility.UNKNOWN, ProductCategoryPolicy.compare(unknown, Product("b", foodType = "과자")).status)
    }
    @Test fun `conflicting name and type stays reviewable without discarding raw categories`() {
        val item = Product("a", productName = "아이스크림", foodType = "어묵", foodCategories = "dessert|bad")
        assertEquals(ProductUse.UNKNOWN, item.categoryAssessment.usage)
        assertEquals("SOURCE_NAME_TYPE_CONFLICT", item.categoryAssessment.evidence)
        assertEquals(listOf("bad"), item.categoryAssessment.unknownStoredValues)
        assertEquals("dessert|bad", item.foodCategories)
    }
}
