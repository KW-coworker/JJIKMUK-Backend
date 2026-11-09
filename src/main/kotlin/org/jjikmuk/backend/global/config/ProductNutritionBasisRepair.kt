package org.jjikmuk.backend.global.config

import org.jjikmuk.backend.domain.product.Product

/** Metadata-only repair. Barcode/row position alone must never authorize borrowing another basis. */
internal object ProductNutritionBasisRepair {
    fun basisIfMatching(live: Product, row: ProductCsvRecord): String? {
        if (!live.nutritionBasisRaw.isNullOrBlank()) return null
        val basis = row.text(ProductCsvColumn.NUTRITION_BASIS_RAW)?.takeIf { it.length <= 255 } ?: return null
        fun same(value: String?, column: ProductCsvColumn) = value.orEmpty().trim() == row.text(column).orEmpty()
        if (!same(live.productName, ProductCsvColumn.PRODUCT_NAME) ||
            !same(live.manufacturer, ProductCsvColumn.MANUFACTURER) ||
            !same(live.reportNo, ProductCsvColumn.REPORT_NO) || !same(live.source, ProductCsvColumn.SOURCE) ||
            !same(live.totalWeight, ProductCsvColumn.TOTAL_WEIGHT)) return null
        val pairs = listOf(live.energyKcal to ProductCsvColumn.ENERGY_KCAL, live.carbsG to ProductCsvColumn.CARBS_G,
            live.proteinG to ProductCsvColumn.PROTEIN_G, live.fatG to ProductCsvColumn.FAT_G,
            live.sugarG to ProductCsvColumn.SUGAR_G, live.sodiumMg to ProductCsvColumn.SODIUM_MG,
            live.cholesterolMg to ProductCsvColumn.CHOLESTEROL_MG)
        if (pairs.any { (value, column) -> value != row.number(column) }) return null
        return basis
    }
}
