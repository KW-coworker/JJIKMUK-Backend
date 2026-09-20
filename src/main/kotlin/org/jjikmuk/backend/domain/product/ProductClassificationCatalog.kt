package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.FoodAllergy
import java.text.Normalizer

/** Stable API IDs for the non-exclusive, consumer-facing food categories. */
enum class ProductFoodCategory(
    val id: String,
    val displayName: String,
    private val aliases: Set<String> = emptySet()
) {
    SNACK("snack", "과자·스낵", setOf("과자/스낵")),
    DESSERT("dessert", "디저트·빙과", setOf("디저트/빙과")),
    CONVENIENCE("convenience", "간편·즉석식품", setOf("간편/즉석식품")),
    BEVERAGE("beverage", "음료"),
    DAIRY("dairy", "유제품"),
    BAKERY("bakery", "베이커리·떡", setOf("베이커리/떡")),
    NOODLES("noodles", "면류"),
    MEAT("meat", "육류·가공육", setOf("정육/가공육")),
    SEAFOOD("seafood", "수산물·해조류"),
    PLANT("plant", "농산·곡물·두부류"),
    SIDES("sides", "김치·절임·반찬"),
    CONDIMENTS("condiments", "소스·조미료·식용유", setOf("소스/조미료")),
    SPECIAL("special", "특수영양·건강기능식품", setOf("특수/건강식")),
    UNCLASSIFIED("unclassified", "미분류");

    private val acceptedKeys = (aliases + id + name + displayName)
        .map(::normalizeClassificationKey)
        .toSet()

    fun toMetadata(): Map<String, String> = mapOf("id" to id, "label" to displayName)

    companion object {
        fun resolve(value: String): ProductFoodCategory? {
            val normalized = normalizeClassificationKey(value)
            return entries.firstOrNull { normalized in it.acceptedKeys }
        }
    }
}

enum class AllergyClassificationState(val id: String, val displayName: String) {
    DETECTED("detected", "검출"),
    NOT_DETECTED("not_detected", "미검출"),
    NO_INFORMATION("no_information", "정보없음")
}

data class ParsedAllergyClassification(
    val allergens: List<FoodAllergy>,
    val state: AllergyClassificationState
)

/**
 * Parses the pipe-separated values stored in Product.csv/DB without treating
 * `미검출` as proof that a product is safe.
 */
object ProductClassificationCatalog {
    const val DELIMITER = "|"

    fun splitStored(value: String?): List<String> = value.orEmpty()
        .split(DELIMITER)
        .map(String::trim)
        .filter(String::isNotBlank)

    fun parseFoodCategories(value: String?): List<ProductFoodCategory> =
        splitStored(value).mapNotNull(ProductFoodCategory::resolve).distinct()

    fun parseAllergyClassification(value: String?): ParsedAllergyClassification {
        val tokens = splitStored(value)
        val allergens = tokens.mapNotNull(AllergyCatalog::resolve).distinct()
        val state = when {
            allergens.isNotEmpty() -> AllergyClassificationState.DETECTED
            tokens.any { normalizeClassificationKey(it) == normalizeClassificationKey(AllergyClassificationState.NOT_DETECTED.displayName) } ->
                AllergyClassificationState.NOT_DETECTED
            else -> AllergyClassificationState.NO_INFORMATION
        }
        return ParsedAllergyClassification(allergens, state)
    }

    fun foodCategoryIds(value: String?): List<String> =
        parseFoodCategories(value).map(ProductFoodCategory::id)

    fun allergyIds(value: String?): List<String> =
        parseAllergyClassification(value).allergens.map(FoodAllergy::id)
}

private fun normalizeClassificationKey(value: String): String = Normalizer
    .normalize(value.trim(), Normalizer.Form.NFKC)
    .lowercase()
    .filter { it.isLetterOrDigit() || it == '_' }
