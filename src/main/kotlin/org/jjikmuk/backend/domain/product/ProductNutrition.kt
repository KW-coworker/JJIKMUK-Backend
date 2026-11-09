package org.jjikmuk.backend.domain.product

import java.math.BigDecimal
import java.math.RoundingMode
import java.text.Normalizer
import java.util.Locale

data class NutritionQuantity(val amount: BigDecimal, val unit: String)
data class NutritionBasis(val raw: String?, val status: String, val amount: BigDecimal?, val unit: String?)

data class NutrientValues(
    val energyKcal: Double?, val carbsG: Double?, val proteinG: Double?, val fatG: Double?,
    val sugarG: Double?, val sodiumMg: Double?, val cholesterolMg: Double?
) {
    internal fun scaled(factor: BigDecimal): NutrientValues {
        fun convert(value: Double?): Double? = value?.takeIf { it.isFinite() && it >= 0 }?.let {
            BigDecimal.valueOf(it).multiply(factor).setScale(4, RoundingMode.HALF_UP).toDouble()
                .takeIf(Double::isFinite)
        }
        return NutrientValues(convert(energyKcal), convert(carbsG), convert(proteinG), convert(fatG),
            convert(sugarG), convert(sodiumMg), convert(cholesterolMg))
    }

    /** Reference percentages, not personalized daily targets. Missing values stay null. */
    fun dailyReferencePercents(): Map<String, Long?> = mapOf(
        "energyPercent" to percent(energyKcal, 2000.0), "carbsPercent" to percent(carbsG, 324.0),
        "proteinPercent" to percent(proteinG, 55.0), "fatPercent" to percent(fatG, 54.0),
        "sugarPercent" to percent(sugarG, 100.0), "sodiumPercent" to percent(sodiumMg, 2000.0),
        "cholesterolPercent" to percent(cholesterolMg, 300.0)
    )
    private fun percent(value: Double?, reference: Double): Long? =
        value?.takeIf { it.isFinite() && it >= 0 }?.let { Math.round(it / reference * 100) }
}

data class NutritionPortion(val amount: BigDecimal, val unit: String, val values: NutrientValues,
    val dailyReferencePercents: Map<String, Long?> = values.dailyReferencePercents())

data class ProductNutrition(
    val contractVersion: String = "nutrition-v1",
    val sourceBasis: NutritionBasis,
    val sourceValues: NutrientValues,
    val packageQuantity: NutritionQuantity?,
    val per100g: NutritionPortion?,
    val per100ml: NutritionPortion?,
    val perPackage: NutritionPortion?,
    val packageCalculationStatus: String,
    val packageCalculationReason: String?
) {
    companion object {
        fun from(product: Product): ProductNutrition {
            val source = NutrientValues(product.energyKcal, product.carbsG, product.proteinG, product.fatG,
                product.sugarG, product.sodiumMg, product.cholesterolMg)
            val basis = NutritionBasisParser.parse(product.nutritionBasisRaw)
            val capacity = ProductCapacity.parse(product.totalWeight)
            val quantity = capacity.amount?.let { NutritionQuantity(it, requireNotNull(capacity.unit)) }
            fun portion(amount: BigDecimal, unit: String): NutritionPortion? {
                if (basis.status != "KNOWN" || basis.unit != unit) return null
                val factor = amount.divide(requireNotNull(basis.amount), 16, RoundingMode.HALF_UP)
                return NutritionPortion(amount, unit, source.scaled(factor))
            }
            val reason = when {
                basis.status != "KNOWN" -> "NUTRITION_BASIS_UNKNOWN"
                quantity == null -> "PACKAGE_QUANTITY_UNKNOWN"
                basis.unit != quantity.unit -> "UNIT_MISMATCH"
                else -> null
            }
            return ProductNutrition(sourceBasis = basis, sourceValues = source, packageQuantity = quantity,
                per100g = portion(BigDecimal(100), "g"), per100ml = portion(BigDecimal(100), "ml"),
                perPackage = if (reason == null) portion(quantity!!.amount, quantity.unit) else null,
                packageCalculationStatus = if (reason == null) "CALCULATED" else "UNAVAILABLE",
                packageCalculationReason = reason)
        }
    }
}

/** Explicit source basis only. Never infer 100g from calorie magnitude, package weight or raw label prose. */
object NutritionBasisParser {
    private val SINGLE = Regex("^(?:100g당|100ml당)$")
    fun parse(raw: String?): NutritionBasis {
        val unknown = NutritionBasis(raw, "UNKNOWN", null, null)
        if (raw.isNullOrBlank() || raw.length > 255) return unknown
        val text = Normalizer.normalize(raw, Normalizer.Form.NFKC).lowercase(Locale.ROOT)
            .filterNot(Char::isWhitespace)
        // Only a single explicit mass/volume. Reject ambiguous multiple bases, packs and serving counts.
        val cleaned = if (SINGLE.matches(text)) text.removeSuffix("당") else text
        if (cleaned.any { it in "x×*" } || cleaned.startsWith("총")) return unknown
        val parsed = ProductCapacity.parse(cleaned)
        return parsed.amount?.let { NutritionBasis(raw, "KNOWN", it, parsed.unit) } ?: unknown
    }
}
