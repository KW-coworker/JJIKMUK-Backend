package org.jjikmuk.backend.domain.product

import jakarta.persistence.*
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.domain.Pageable
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.core.ConnectionCallback
import org.springframework.stereotype.Service
import org.springframework.transaction.PlatformTransactionManager
import org.springframework.transaction.TransactionDefinition
import org.springframework.transaction.support.TransactionTemplate
import tools.jackson.databind.json.JsonMapper
import java.security.MessageDigest
import java.time.LocalDateTime

@Entity
@Table(name = "product_id_sequence")
class ProductIdSequence(
    @Id @Column(name = "sequence_name", length = 32) val name: String = "products",
    @Column(name = "next_id", nullable = false) val nextId: Long = 1
)

/** Immutable observation history, NOT a claim that a physical product was renewed. */
@Entity
@Table(name = "product_attribute_snapshots", indexes = [Index(name = "idx_attribute_product", columnList = "product_id,id")])
class ProductAttributeSnapshot(
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) val id: Long? = null,
    @Column(name = "product_id", nullable = false) val productId: Long,
    @Column(name = "previous_snapshot_id") val previousSnapshotId: Long? = null,
    @Column(name = "dataset_version", nullable = false, length = 128) val datasetVersion: String,
    @Column(name = "observed_at", nullable = false) val observedAt: LocalDateTime = LocalDateTime.now(),
    @Column(name = "observed_by", nullable = false, length = 128) val observedBy: String = "IMPORT_JOB",
    @Column(name = "rule_version", nullable = false, length = 64) val ruleVersion: String = "catalog-observation-v1",
    @Column(name = "change_reason", nullable = false, length = 500) val changeReason: String,
    @Column(name = "changed_fields", nullable = false, columnDefinition = "TEXT") val changedFields: String,
    @Column(name = "payload_hash", nullable = false, length = 64) val payloadHash: String,
    @Column(name = "payload_json", nullable = false, columnDefinition = "LONGTEXT") val payloadJson: String
)

interface ProductAttributeSnapshotRepository : JpaRepository<ProductAttributeSnapshot, Long> {
    fun findByProductIdOrderByIdDesc(productId: Long, pageable: Pageable): List<ProductAttributeSnapshot>
}

data class IdBackfillResult(val attempted: Int, val assigned: Int)
data class AttributeCaptureResult(val scanned: Int, val changed: Int, val nextAfterBarcode: String?)

/** Explicit bounded maintenance only. Never an application startup runner and never called by GET. */
@Service
class CatalogEvolutionService(
    private val jdbc: JdbcTemplate,
    private val snapshots: ProductAttributeSnapshotRepository,
    transactionManager: PlatformTransactionManager
) {
    private val tx = TransactionTemplate(transactionManager)
    private val allocationTx = TransactionTemplate(transactionManager).apply {
        propagationBehavior = TransactionDefinition.PROPAGATION_REQUIRES_NEW
    }
    private val mapper = JsonMapper.builder().findAndAddModules().build()

    /** Reservation survives a dataset rollback. Gaps are allowed; reusing a prior ID is not. */
    fun reserveIds(count: Long, minimumNextId: Long = 1): Long {
        require(count >= 0 && minimumNextId > 0)
        return allocationTx.execute {
            val next = jdbc.queryForObject("SELECT next_id FROM product_id_sequence WHERE sequence_name='products' FOR UPDATE", Long::class.java)
                ?: error("Product ID sequence is not initialized; apply V15 first")
            val start = maxOf(next, minimumNextId)
            require(start <= Long.MAX_VALUE - count) { "Product ID sequence exhausted" }
            jdbc.update("UPDATE product_id_sequence SET next_id=? WHERE sequence_name='products'", start + count)
            start
        }!!
    }

    fun assignMissingIds(batchSize: Int = 500, table: String = "products"): IdBackfillResult {
        require(batchSize in 1..1000)
        checkTable(table)
        val barcodes = jdbc.queryForList("SELECT barcode FROM $table WHERE product_id IS NULL ORDER BY barcode LIMIT ?", String::class.java, batchSize)
        if (barcodes.isEmpty()) return IdBackfillResult(0, 0)
        val maxId = maxKnownId()
        require(maxId < Long.MAX_VALUE)
        val start = reserveIds(barcodes.size.toLong(), maxId + 1)
        // Concurrent batches may select the same rows; the predicate prevents reassignment.
        val assigned = tx.execute {
            barcodes.mapIndexed { i, barcode -> jdbc.update(
                "UPDATE $table SET product_id=? WHERE barcode=? AND product_id IS NULL", start + i, barcode) }.sum()
        }!!
        return IdBackfillResult(barcodes.size, assigned)
    }

    fun maxId(table: String): Long {
        checkTable(table)
        return jdbc.queryForObject("SELECT COALESCE(MAX(product_id),0) FROM $table", Long::class.java) ?: 0
    }

    /** Bootstrap above legacy rollback/staging IDs too; after V15 the durable sequence is authoritative. */
    fun maxKnownId(): Long = jdbc.execute(ConnectionCallback { connection ->
        listOf("products", "products_staging", "products_rollback", "product_attribute_snapshots").maxOf { table ->
            val present = connection.metaData.getColumns(connection.catalog, null, table, "product_id").use { columns ->
                var found = false
                while (columns.next()) {
                    if (columns.getString("TABLE_NAME").equals(table, true) &&
                        columns.getString("COLUMN_NAME").equals("product_id", true)) found = true
                }
                found
            }
            if (!present) 0L else connection.createStatement().use { statement ->
                statement.executeQuery("SELECT COALESCE(MAX(product_id),0) FROM $table").use { result ->
                    result.next(); result.getLong(1)
                }
            }
        }
    }) ?: 0L

    /** One transaction per page; callers must use the returned keyset cursor, not OFFSET. */
    fun captureAttributes(datasetVersion: String, reason: String, afterBarcode: String = "", batchSize: Int = 200,
                          table: String = "products", observedBy: String = "IMPORT_JOB"): AttributeCaptureResult {
        checkTable(table)
        require(datasetVersion.isNotBlank() && datasetVersion.length <= 128)
        require(reason.isNotBlank() && reason.length <= 500)
        require(observedBy.isNotBlank() && observedBy.length <= 128)
        require(batchSize in 1..1000 && afterBarcode.length <= 255)
        return tx.execute {
            val rows = jdbc.queryForList("SELECT barcode,product_id,attribute_snapshot_id,${FIELDS.joinToString()} FROM $table WHERE barcode>? ORDER BY barcode LIMIT ? FOR UPDATE", afterBarcode, batchSize)
            var changed = 0
            for (row in rows) {
                val productId = (row["product_id"] as? Number)?.toLong()
                    ?: error("Assign internal IDs before capturing attributes")
                require(productId > 0) { "Internal product ID must be positive" }
                val previousId = (row["attribute_snapshot_id"] as? Number)?.toLong()
                val previous = previousId?.let { snapshots.findById(it).orElseThrow { IllegalStateException("Missing prior attribute snapshot") } }
                require(previous == null || previous.productId == productId) { "Attribute snapshot identity mismatch" }
                val payload = FIELDS.associateWith { key ->
                    val value = row[key]
                    if (key.startsWith("is_")) when (value) {
                        is Boolean -> value
                        is Number -> value.toInt() != 0
                        is ByteArray -> value.any { it.toInt() != 0 }
                        else -> value
                    } else value
                }
                val encoded = mapper.writeValueAsString(payload)
                val hash = MessageDigest.getInstance("SHA-256").digest(encoded.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
                if (previous?.payloadHash == hash) continue
                val old = previous?.let { mapper.readTree(it.payloadJson) }
                val now = mapper.readTree(encoded)
                val fields = FIELDS.filter { old?.get(it) != now.get(it) }
                val saved = snapshots.saveAndFlush(ProductAttributeSnapshot(productId = productId, previousSnapshotId = previousId,
                    datasetVersion = datasetVersion, observedBy = observedBy, changeReason = reason, changedFields = fields.joinToString(","), payloadHash = hash, payloadJson = encoded))
                jdbc.update("UPDATE $table SET attribute_snapshot_id=? WHERE barcode=? AND product_id=?", saved.id, row["barcode"], productId)
                changed++
            }
            AttributeCaptureResult(rows.size, changed, rows.lastOrNull()?.get("barcode") as? String)
        }!!
    }

    private fun checkTable(table: String) = require(table in setOf("products", "products_staging"))

    companion object {
        // Preserve raw fields + derived flags + provenance; no computed classification overwrites the source.
        val FIELDS = listOf("product_name", "clean_product_name", "manufacturer", "source", "report_no", "image_url",
            "total_weight", "food_type", "raw_materials", "allergy", "allergy_warning", "allergy_classification", "food_categories",
            "energy_kcal", "carbs_g", "protein_g", "fat_g", "sugar_g", "sodium_mg", "cholesterol_mg",
            "allergy_evidence_level", "allergy_data_confidence", "nutrition_data_origin", "nutrition_data_confidence",
            "dietary_data_origin", "dietary_data_confidence", "is_vegan", "is_lacto_vegetarian", "is_ovo_vegetarian",
            "is_lacto_ovo_vegetarian", "is_pescatarian", "is_pollotarian", "is_low_sugar", "is_low_sodium", "is_gluten_free",
            "is_low_calorie", "is_low_fat", "is_high_protein")
    }
}
