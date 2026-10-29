package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.history.*
import org.jjikmuk.backend.domain.user.*
import org.jjikmuk.backend.domain.recommendation.*
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.data.domain.PageRequest
import java.util.concurrent.Executors
import kotlin.test.*

@SpringBootTest(properties = ["spring.datasource.url=jdbc:h2:mem:catalog-evolution;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_UPPER=false"])
@ActiveProfiles("test")
class CatalogEvolutionTest @Autowired constructor(
    private val evolution: CatalogEvolutionService,
    private val products: ProductRepository,
    private val snapshots: ProductAttributeSnapshotRepository,
    private val history: HistoryRepository,
    private val histories: HistoryService,
    private val users: UserRepository,
    private val neighbors: ProductNeighborSetRepository,
    private val recommendations: RecommendationService,
    private val jdbc: JdbcTemplate
) {
    @BeforeEach fun reset() {
        history.deleteAll(); neighbors.deleteAll(); products.deleteAll(); snapshots.deleteAll(); users.deleteAll()
        jdbc.update("UPDATE product_id_sequence SET next_id=1 WHERE sequence_name='products'")
    }
    private fun product(code: String, id: Long? = null) = Product(barcode = code, productName = "쌀과자", rawMaterials = "쌀",
        foodType = "과자", foodCategories = "snack|미분류", productId = id, dietaryDataConfidence = null)

    @Test fun `backfill preserves existing IDs is bounded and does not reuse IDs after deletion`() {
        products.saveAllAndFlush(listOf(product("001", 90), product("002"), product("003")))
        assertEquals(1, evolution.assignMissingIds(1).assigned)
        assertEquals(90L, products.findFirstByBarcode("001")!!.productId)
        val issued = products.findFirstByBarcode("002")!!.productId!!
        assertTrue(issued > 90)
        products.deleteById("002")
        evolution.assignMissingIds(1)
        assertTrue(products.findFirstByBarcode("003")!!.productId!! > issued)
        assertEquals(0, evolution.assignMissingIds().assigned)
    }

    @Test fun `parallel reservations never overlap`() {
        val executor = Executors.newFixedThreadPool(4)
        try {
            val starts = (1..8).map { executor.submit<Long> { evolution.reserveIds(10) } }.map { it.get() }
            val ids = starts.flatMap { (it until it + 10).toList() }
            assertEquals(80, ids.distinct().size)
        } finally { executor.shutdownNow() }
    }

    @Test fun `initial backfill reserves above IDs in legacy rollback table`() {
        jdbc.execute("CREATE TABLE products_rollback (product_id BIGINT)")
        try {
            jdbc.update("INSERT INTO products_rollback(product_id) VALUES (5000)")
            products.saveAndFlush(product("001"))
            evolution.assignMissingIds()
            assertTrue(products.findFirstByBarcode("001")!!.productId!! > 5000)
        } finally { jdbc.execute("DROP TABLE products_rollback") }
    }

    @Test fun `attribute change appends provenance and unchanged captures do not duplicate`() {
        products.saveAndFlush(product("001", 10))
        assertEquals(1, evolution.captureAttributes("v1", "BASELINE", observedBy = "ADMIN:1").changed)
        val first = products.findByProductId(10)!!.attributeSnapshotId!!
        assertEquals(0, evolution.captureAttributes("v1", "RETRY").changed)
        jdbc.update("UPDATE products SET raw_materials=?,dietary_data_confidence=? WHERE product_id=10", "쌀, 우유", .8)
        assertEquals(1, evolution.captureAttributes("v2", "SOURCE_REFRESH").changed)
        val entries = snapshots.findByProductIdOrderByIdDesc(10, PageRequest.of(0, 10))
        assertEquals(2, entries.size)
        assertEquals(first, entries[0].previousSnapshotId)
        assertContains(entries[0].changedFields, "raw_materials")
        assertContains(entries[0].payloadJson, "우유")
        assertContains(entries[1].payloadJson, "\"dietary_data_confidence\":null")
        assertEquals("ADMIN:1", entries[1].observedBy)
    }

    @Test fun `identity snapshot mismatch rolls back capture`() {
        products.saveAllAndFlush(listOf(product("001", 1), product("002", 2)))
        evolution.captureAttributes("v1", "BASELINE")
        val first = products.findByProductId(1)!!.attributeSnapshotId!!
        jdbc.update("UPDATE products SET attribute_snapshot_id=? WHERE product_id=2", first)
        assertFailsWith<IllegalArgumentException> { evolution.captureAttributes("v2", "CHECK") }
        assertEquals(2L, snapshots.count())
    }

    @Test fun `events accept ID and preserve snapshot and never retarget retired synthetic barcode`() {
        val owner = users.saveAndFlush(User(email = "catalog@example.invalid", nickname = "catalog", password = "DISABLED"))
        products.saveAndFlush(product("NO_BARCODE_ROW_1", 1))
        evolution.captureAttributes("v1", "BASELINE")
        val event = histories.recordAction(owner.id!!, UserActionEventRequest(actionType = "FAVORITE", productId = 1))
        assertEquals(1L, event.productId)
        assertNotNull(event.attributeSnapshotId)
        assertFails { histories.recordAction(owner.id!!, UserActionEventRequest("other", "FAVORITE", 1)) }
        products.deleteById("NO_BARCODE_ROW_1")
        products.saveAndFlush(product("NO_BARCODE_ROW_1", 2))
        assertNull(histories.getUserHistory(owner.id!!).first().product)
        history.saveAndFlush(History(user = owner, barcode = "NO_BARCODE_ROW_1", actionType = UserActionType.SCAN))
        assertTrue(histories.getUserHistory(owner.id!!).all { it.product == null })
    }

    @Test fun `known wrong-purpose candidates cannot enter strict or fallback recommendations`() {
        val owner = users.saveAndFlush(User(email = "purpose@example.invalid", nickname = "purpose", password = "DISABLED"))
        products.saveAllAndFlush(listOf(Product("ref", productName = "꽈배기 아이스크림", foodCategories = "dessert"),
            Product("wrong", productName = "꽈배기", foodType = "어묵", rawMaterials = "연육"),
            Product("mix", productName = "아이스크림용파우더", foodCategories = "dessert"),
            Product("right", productName = "딸기아이스", foodType = "빙과")))
        neighbors.saveAndFlush(ProductNeighborSet("ref", "test", 3, "wrong|0.99,mix|0.98,right|0.50"))
        val result = recommendations.recommendAlternatives("ref", owner.id!!, 10, .2)
        assertEquals(listOf("right"), result.items.map { it.product.barcode })
        assertEquals(2, result.excluded.categoryMismatch)
        assertEquals(CategoryCompatibility.MATCH, result.items.single().categoryCompatibility!!.status)
        neighbors.saveAndFlush(ProductNeighborSet("ref", "test", 1, "wrong|0.01"))
        val empty = recommendations.recommendAlternatives("ref", owner.id!!, 10, .2)
        assertEquals(RecommendationResultMode.ACTION_REQUIRED, empty.resultMode)
        assertTrue(empty.items.isEmpty() && empty.fallbackItems.isEmpty())
    }
}
