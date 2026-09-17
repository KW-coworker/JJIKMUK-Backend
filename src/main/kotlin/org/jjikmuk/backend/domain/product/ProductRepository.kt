package org.jjikmuk.backend.domain.product

import org.springframework.data.jpa.repository.JpaRepository

interface ProductRepository : JpaRepository<Product, String> {
    fun findFirstByBarcode(barcode: String): Product?
}
