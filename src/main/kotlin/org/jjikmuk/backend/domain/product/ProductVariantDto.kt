package org.jjikmuk.backend.domain.product

import java.math.BigDecimal

data class ProductVariantResponse(
    val referenceBarcode: String,
    val selectedOptionKey: String,
    val optionCount: Int,
    val hasSelectableOptions: Boolean,
    val options: List<ProductCapacityOption>
)

data class ProductCapacityOption(
    val key: String,
    val label: String,
    val amount: BigDecimal?,
    val unit: String?,
    val barcode: String,
    val sourceRowCount: Int,
    val hasSafetyDifferences: Boolean,
    val analysisScope: String = "CAPACITY_GROUP",
    /** Same product/nutrientPercents/analysis layout as product detail, with aggregated safety. */
    val data: Map<String, Any>
)
