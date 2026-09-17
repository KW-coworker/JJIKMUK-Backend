package org.jjikmuk.backend.domain.product

/** Describes how a stored value was obtained, without claiming that it is correct. */
enum class ProductDataOrigin {
    SOURCE,
    NORMALIZED,
    INFERRED,
    IMPUTED,
    CALCULATED,
    UNKNOWN
}

/**
 * Reliability category for the evidence used by allergy evaluation.
 * UNKNOWN is deliberately the default for legacy rows.
 */
enum class AllergyEvidenceLevel {
    VERIFIED_SOURCE,
    DECLARED_LABEL,
    INGREDIENT_DERIVED,
    INFERRED,
    UNKNOWN
}

/** Conservative classification for legacy rows that do not carry lineage columns. */
object ProductDataQualityClassifier {
    fun classifyAllergyEvidence(
        allergyWarning: String?,
        rawMaterials: String?,
        normalizedAllergy: String?
    ): AllergyEvidenceLevel = when {
        !allergyWarning.isNullOrBlank() -> AllergyEvidenceLevel.DECLARED_LABEL
        !rawMaterials.isNullOrBlank() -> AllergyEvidenceLevel.INGREDIENT_DERIVED
        !normalizedAllergy.isNullOrBlank() -> AllergyEvidenceLevel.INFERRED
        else -> AllergyEvidenceLevel.UNKNOWN
    }

    fun allergyConfidence(
        evidenceLevel: AllergyEvidenceLevel,
        rawMaterialMatchScore: Double?
    ): Double? = when (evidenceLevel) {
        AllergyEvidenceLevel.VERIFIED_SOURCE -> 1.0
        AllergyEvidenceLevel.DECLARED_LABEL -> 0.95
        AllergyEvidenceLevel.INGREDIENT_DERIVED ->
            rawMaterialMatchScore?.asRatio()?.coerceIn(0.50, 0.90) ?: 0.70
        AllergyEvidenceLevel.INFERRED -> 0.50
        AllergyEvidenceLevel.UNKNOWN -> null
    }

    fun nutritionOrigin(
        hasNutrition: Boolean,
        mergeBasis: String?,
        matchMethod: String?,
        parsedItemCount: Int?
    ): ProductDataOrigin = when {
        !hasNutrition -> ProductDataOrigin.UNKNOWN
        matchMethod.equals("barcode_text_parsed", ignoreCase = true) ||
            (parsedItemCount ?: 0) > 0 -> ProductDataOrigin.NORMALIZED
        !matchMethod.isNullOrBlank() || mergeBasis.equals("nutrition_source", ignoreCase = true) ->
            ProductDataOrigin.SOURCE
        else -> ProductDataOrigin.UNKNOWN
    }

    fun nutritionConfidence(
        origin: ProductDataOrigin,
        matchScore: Double?,
        parsedItemCount: Int?
    ): Double? = when (origin) {
        ProductDataOrigin.SOURCE -> matchScore?.asRatio()?.coerceIn(0.50, 1.0) ?: 0.90
        ProductDataOrigin.NORMALIZED -> matchScore?.asRatio()
            ?: ((parsedItemCount ?: 0) / 7.0).coerceIn(0.40, 0.90)
        ProductDataOrigin.INFERRED -> matchScore?.asRatio()?.coerceIn(0.40, 0.80) ?: 0.55
        ProductDataOrigin.IMPUTED -> matchScore?.asRatio()?.coerceIn(0.30, 0.70) ?: 0.45
        ProductDataOrigin.CALCULATED -> 0.90
        ProductDataOrigin.UNKNOWN -> null
    }

    fun dietaryConfidence(hasRawMaterials: Boolean, nutritionValueCount: Int): Double? = when {
        hasRawMaterials && nutritionValueCount >= 3 -> 0.80
        hasRawMaterials -> 0.70
        nutritionValueCount >= 3 -> 0.60
        else -> null
    }

    private fun Double.asRatio(): Double = if (this > 1.0) this / 100.0 else this
}
