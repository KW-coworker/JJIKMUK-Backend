package org.jjikmuk.backend.domain.scan

import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.global.config.ProductDatasetMarker
import org.springframework.beans.factory.annotation.Value
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

/** SELECT only. Does not call the detail/history or personalized-analysis services. */
@Service
class ScanCatalog(private val jdbc: JdbcTemplate, private val products: ProductRepository,
                  @param:Value("\${scan.catalog.version:}") private val version: String,
                  @param:Value("\${scan.catalog.source-sha256:}") private val sourceSha: String,
                  @param:Value("\${scan.catalog.row-count:0}") private val rowCount: Long) {
    fun verifiedVersion(): String {
        if (version.isBlank() || version.length > 200 || !sourceSha.matches(Regex("[0-9a-f]{64}")) || rowCount <= 0)
            throw ScanFailure(503, "INDEX_NOT_READY")
        val comment = jdbc.queryForObject("SELECT TABLE_COMMENT FROM information_schema.TABLES " +
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'", String::class.java)
        val marker = ProductDatasetMarker.decode(comment)
        if (marker?.version != version || marker.sha256 != sourceSha || marker.rowCount != rowCount)
            throw ScanFailure(503, "CATALOG_MISMATCH")
        return version
    }

    @Transactional(readOnly = true)
    fun hydrate(value: ScanCandidates, requestId: String): ScanResponse {
        if (verifiedVersion() != value.catalogVersion) throw ScanFailure(503, "CATALOG_MISMATCH")
        val indexed = if (value.candidates.isEmpty()) emptyMap() else
            products.findAllById(value.candidates.map { it.barcode }).associateBy { it.barcode }
        val items = value.candidates.map { candidate ->
            val p = indexed[candidate.barcode] ?: throw ScanFailure(503, "CATALOG_MISMATCH")
            if (p.productId != candidate.productId || p.productName != candidate.sourceProductName ||
                p.manufacturer != candidate.sourceManufacturer) throw ScanFailure(503, "CATALOG_MISMATCH")
            ScanItem(ScanProduct(candidate.productId, p.barcode, candidate.sourceProductName,
                p.manufacturer, p.imageUrl, p.allergy))
        }
        if (verifiedVersion() != value.catalogVersion) throw ScanFailure(503, "CATALOG_MISMATCH")
        return ScanResponse(data = ScanData(scanId = value.scanId, requestId = requestId,
            catalogVersion = value.catalogVersion, status = value.status, method = value.method,
            gptUsed = value.gptUsed, products = items))
    }
}
