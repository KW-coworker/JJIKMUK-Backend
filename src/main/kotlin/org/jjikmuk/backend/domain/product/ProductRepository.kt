package org.jjikmuk.backend.domain.product

import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.domain.Pageable

interface ProductRepository : JpaRepository<Product, String> {
    fun findFirstByBarcode(barcode: String): Product?

    /**
     * Keyset-based catalogue traversal for randomised home recommendations.
     * Using the barcode index avoids ORDER BY RAND() and large OFFSET scans.
     */
    fun findByBarcodeGreaterThanOrderByBarcodeAsc(
        barcode: String,
        pageable: Pageable
    ): List<Product>

    fun findByBarcodeGreaterThanAndBarcodeLessThanEqualOrderByBarcodeAsc(
        barcode: String,
        upperBound: String,
        pageable: Pageable
    ): List<Product>
}
