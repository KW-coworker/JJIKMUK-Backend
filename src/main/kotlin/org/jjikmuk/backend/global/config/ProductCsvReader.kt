package org.jjikmuk.backend.global.config

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductDataQualityClassifier
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import org.jjikmuk.backend.domain.product.ProductGroupKeyBuilder
import java.io.BufferedReader
import java.io.Closeable
import java.io.InputStream
import java.io.InputStreamReader
import java.io.PushbackReader
import java.io.Reader

internal enum class ProductCsvColumn(val header: String) {
    BARCODE("barcode"),
    PRODUCT_NAME("product_name"),
    MANUFACTURER("manufacturer"),
    REPORT_NO("report_no"),
    ALLERGY("allergy"),
    NUTRIENT_TEXT("nutrient_text"),
    IMAGE_URL("image_url"),
    SOURCE("source"),
    RAW_MATERIALS("raw_materials"),
    ENERGY_KCAL("energy_kcal"),
    CARBS_G("carbs_g"),
    PROTEIN_G("protein_g"),
    FAT_G("fat_g"),
    SUGAR_G("sugar_g"),
    SODIUM_MG("sodium_mg"),
    CHOLESTEROL_MG("cholesterol_mg"),
    ALLERGY_WARNING("allergy_warning"),
    CLEAN_PRODUCT_NAME("clean_product_name"),
    TOTAL_WEIGHT("total_weight"),
    CARBS_PERCENT("carbs_percent(%)"),
    PROTEIN_PERCENT("protein_percent(%)"),
    FAT_PERCENT("fat_percent(%)"),
    SODIUM_G("sodium_g"),
    CHOLESTEROL_G("cholesterol_g"),
    FOOD_MAJOR_CATEGORY("식품대분류명"),
    REPRESENTATIVE_FOOD_NAME("대표식품명"),
    FOOD_MIDDLE_CATEGORY("식품중분류명"),
    FOOD_SUBCATEGORY("식품소분류명"),
    RAW_FOOD_TYPE("rw_PRDLST_DCNM"),
    MERGE_BASIS("병합_기준"),
    NUTRITION_MATCH_METHOD("영양_매칭방식"),
    NUTRITION_MATCH_SCORE("영양_매칭점수"),
    RAW_MATERIAL_MATCH_SCORE("원재료_매칭점수"),
    NUTRITION_PARSED_ITEM_COUNT("영양_파싱항목수"),
    VEGAN("is_vegan"),
    LACTO_VEGETARIAN("is_lacto_vegetarian"),
    OVO_VEGETARIAN("is_ovo_vegetarian"),
    LACTO_OVO_VEGETARIAN("is_lacto_ovo_vegetarian"),
    PESCATARIAN("is_pescatarian"),
    POLLOTARIAN("is_pollotarian"),
    LOW_SUGAR("is_low_sugar"),
    LOW_SODIUM("is_low_sodium"),
    GLUTEN_FREE("is_gluten_free"),
    LOW_CALORIE("is_low_calorie"),
    LOW_FAT("is_low_fat"),
    HIGH_PROTEIN("is_high_protein")
}

internal data class ProductCsvRecord(
    private val values: Array<String?>,
    val fieldCount: Int
) {
    fun text(column: ProductCsvColumn): String? =
        values[column.ordinal]?.trim()?.takeIf { it.isNotEmpty() }

    fun number(column: ProductCsvColumn): Double? =
        text(column)?.toDoubleOrNull()?.takeIf { it.isFinite() }

    fun flag(column: ProductCsvColumn): Boolean =
        when (text(column)?.lowercase()) {
            "✓", "✔", "true", "t", "yes", "y", "1", "on", "체크" -> true
            else -> false
        }

    fun isRecognizedFlag(column: ProductCsvColumn): Boolean =
        when (text(column)?.lowercase()) {
            "✓", "✔", "true", "t", "yes", "y", "1", "on", "체크",
            "false", "f", "no", "n", "0", "off", "미표시", "-" -> true
            else -> false
        }

    fun isEmpty(): Boolean = values.all { it.isNullOrBlank() }

    fun toProduct(barcode: String): Product {
        val productName = text(ProductCsvColumn.PRODUCT_NAME)
        val cleanProductName = text(ProductCsvColumn.CLEAN_PRODUCT_NAME)
        val manufacturer = text(ProductCsvColumn.MANUFACTURER)
        val rawMaterials = text(ProductCsvColumn.RAW_MATERIALS)
        val imageUrl = text(ProductCsvColumn.IMAGE_URL)
        val allergy = text(ProductCsvColumn.ALLERGY)
        val allergyWarning = text(ProductCsvColumn.ALLERGY_WARNING)
        val nutritionValues = listOf(
            number(ProductCsvColumn.ENERGY_KCAL),
            number(ProductCsvColumn.CARBS_G),
            number(ProductCsvColumn.PROTEIN_G),
            number(ProductCsvColumn.FAT_G),
            number(ProductCsvColumn.SUGAR_G),
            number(ProductCsvColumn.SODIUM_MG),
            number(ProductCsvColumn.CHOLESTEROL_MG)
        )
        val allergyEvidenceLevel = ProductDataQualityClassifier.classifyAllergyEvidence(
            allergyWarning = allergyWarning,
            rawMaterials = rawMaterials,
            normalizedAllergy = allergy
        )
        val parsedItemCount = text(ProductCsvColumn.NUTRITION_PARSED_ITEM_COUNT)?.toIntOrNull()
        val nutritionOrigin = ProductDataQualityClassifier.nutritionOrigin(
            hasNutrition = nutritionValues.any { it != null },
            mergeBasis = text(ProductCsvColumn.MERGE_BASIS),
            matchMethod = text(ProductCsvColumn.NUTRITION_MATCH_METHOD),
            parsedItemCount = parsedItemCount
        )
        val foodType = sequenceOf(
            ProductCsvColumn.RAW_FOOD_TYPE,
            ProductCsvColumn.FOOD_SUBCATEGORY,
            ProductCsvColumn.FOOD_MIDDLE_CATEGORY,
            ProductCsvColumn.REPRESENTATIVE_FOOD_NAME,
            ProductCsvColumn.FOOD_MAJOR_CATEGORY
        ).mapNotNull(::text).firstOrNull()

        return Product(
            barcode = barcode,
            productName = productName,
            manufacturer = manufacturer,
            reportNo = text(ProductCsvColumn.REPORT_NO),
            allergy = allergy,
            nutrientText = text(ProductCsvColumn.NUTRIENT_TEXT),
            imageUrl = imageUrl,
            source = text(ProductCsvColumn.SOURCE),
            rawMaterials = rawMaterials,
            energyKcal = number(ProductCsvColumn.ENERGY_KCAL),
            carbsG = number(ProductCsvColumn.CARBS_G),
            proteinG = number(ProductCsvColumn.PROTEIN_G),
            fatG = number(ProductCsvColumn.FAT_G),
            sugarG = number(ProductCsvColumn.SUGAR_G),
            sodiumMg = number(ProductCsvColumn.SODIUM_MG),
            cholesterolMg = number(ProductCsvColumn.CHOLESTEROL_MG),
            allergyWarning = allergyWarning,
            cleanProductName = cleanProductName,
            totalWeight = text(ProductCsvColumn.TOTAL_WEIGHT),
            foodType = foodType,
            carbsPercent = number(ProductCsvColumn.CARBS_PERCENT),
            proteinPercent = number(ProductCsvColumn.PROTEIN_PERCENT),
            fatPercent = number(ProductCsvColumn.FAT_PERCENT),
            sodiumG = number(ProductCsvColumn.SODIUM_G),
            cholesterolG = number(ProductCsvColumn.CHOLESTEROL_G),
            vegan = flag(ProductCsvColumn.VEGAN),
            lactoVegetarian = flag(ProductCsvColumn.LACTO_VEGETARIAN),
            ovoVegetarian = flag(ProductCsvColumn.OVO_VEGETARIAN),
            lactoOvoVegetarian = flag(ProductCsvColumn.LACTO_OVO_VEGETARIAN),
            pescatarian = flag(ProductCsvColumn.PESCATARIAN),
            pollotarian = flag(ProductCsvColumn.POLLOTARIAN),
            lowSugar = flag(ProductCsvColumn.LOW_SUGAR),
            lowSodium = flag(ProductCsvColumn.LOW_SODIUM),
            glutenFree = flag(ProductCsvColumn.GLUTEN_FREE),
            lowCalorie = flag(ProductCsvColumn.LOW_CALORIE),
            lowFat = flag(ProductCsvColumn.LOW_FAT),
            highProtein = flag(ProductCsvColumn.HIGH_PROTEIN),
            productGroupKey = ProductGroupKeyBuilder.build(
                productName = productName,
                manufacturer = manufacturer,
                rawMaterials = rawMaterials,
                imageUrl = imageUrl
            ),
            allergyEvidenceLevel = allergyEvidenceLevel,
            allergyDataConfidence = ProductDataQualityClassifier.allergyConfidence(
                allergyEvidenceLevel,
                number(ProductCsvColumn.RAW_MATERIAL_MATCH_SCORE)
            ),
            nutritionDataOrigin = nutritionOrigin,
            nutritionDataConfidence = ProductDataQualityClassifier.nutritionConfidence(
                nutritionOrigin,
                number(ProductCsvColumn.NUTRITION_MATCH_SCORE),
                parsedItemCount
            ),
            dietaryDataOrigin = ProductDataOrigin.INFERRED,
            dietaryDataConfidence = ProductDataQualityClassifier.dietaryConfidence(
                hasRawMaterials = !rawMaterials.isNullOrBlank(),
                nutritionValueCount = nutritionValues.count { it != null }
            )
        )
    }
}

/**
 * RFC 4180 CSV reader that retains only columns used by the application.
 * This matters for Product.csv: it has 199 columns and more than 1.3 million records.
 */
internal class ProductCsvReader(inputStream: InputStream) : Closeable {
    private val csvReader = SelectiveRfc4180Reader(
        InputStreamReader(inputStream, Charsets.UTF_8)
    )

    val headerCount: Int

    init {
        val headers = csvReader.readHeader()
            ?: throw IllegalArgumentException("CSV header is missing")
        val normalizedHeaders = headers.mapIndexed { index, header ->
            header.trim().removePrefix(if (index == 0) "\uFEFF" else "")
        }
        headerCount = normalizedHeaders.size

        val missingHeaders = ProductCsvColumn.entries
            .map { it.header }
            .filterNot(normalizedHeaders::contains)
        require(missingHeaders.isEmpty()) {
            "Required CSV headers are missing: ${missingHeaders.joinToString()}"
        }

        val inputIndices = ProductCsvColumn.entries.map { column ->
            normalizedHeaders.indexOf(column.header)
        }
        csvReader.selectColumns(inputIndices)
    }

    fun readRecord(): ProductCsvRecord? {
        val selectedRecord = csvReader.readSelectedRecord() ?: return null
        return ProductCsvRecord(selectedRecord.values, selectedRecord.fieldCount)
    }

    override fun close() = csvReader.close()
}

internal data class SelectedRecord(
    val values: Array<String?>,
    val fieldCount: Int
)

internal class SelectiveRfc4180Reader(reader: Reader) : Closeable {
    private val reader = PushbackReader(BufferedReader(reader, BUFFER_SIZE), 1)
    private var selectedOutputPositionByInput = IntArray(0)
    private var selectedColumnCount = 0

    fun readHeader(): List<String>? {
        val values = mutableListOf<String>()
        val fieldCount = readRawRecord(
            shouldCapture = { true },
            onValue = { _, value -> values.add(value) }
        ) ?: return null

        require(fieldCount == values.size) { "CSV header could not be parsed" }
        return values
    }

    fun selectColumns(inputIndices: List<Int>) {
        val maxInputIndex = inputIndices.maxOrNull() ?: -1
        selectedOutputPositionByInput = IntArray(maxInputIndex + 1) { NOT_SELECTED }
        inputIndices.forEachIndexed { outputPosition, inputIndex ->
            selectedOutputPositionByInput[inputIndex] = outputPosition
        }
        selectedColumnCount = inputIndices.size
    }

    fun readSelectedRecord(): SelectedRecord? {
        check(selectedColumnCount > 0) { "Selected columns have not been configured" }
        val values = arrayOfNulls<String>(selectedColumnCount)
        val fieldCount = readRawRecord(
            shouldCapture = { inputIndex -> outputPosition(inputIndex) != NOT_SELECTED },
            onValue = { inputIndex, value ->
                val outputPosition = outputPosition(inputIndex)
                if (outputPosition != NOT_SELECTED) values[outputPosition] = value
            }
        ) ?: return null
        return SelectedRecord(values, fieldCount)
    }

    private fun outputPosition(inputIndex: Int): Int =
        selectedOutputPositionByInput.getOrElse(inputIndex) { NOT_SELECTED }

    private fun readRawRecord(
        shouldCapture: (Int) -> Boolean,
        onValue: (Int, String) -> Unit
    ): Int? {
        var fieldIndex = 0
        var fieldCharacterCount = 0
        var field = if (shouldCapture(fieldIndex)) StringBuilder() else null
        var inQuotes = false
        var sawAnyCharacter = false

        fun finishField() {
            field?.let { onValue(fieldIndex, it.toString()) }
            fieldIndex++
            fieldCharacterCount = 0
            field = if (shouldCapture(fieldIndex)) StringBuilder() else null
        }

        while (true) {
            val codePoint = reader.read()
            if (codePoint == -1) {
                if (!sawAnyCharacter && fieldIndex == 0 && fieldCharacterCount == 0) return null
                if (inQuotes) throw IllegalArgumentException("CSV ended inside a quoted field")
                finishField()
                return fieldIndex
            }

            sawAnyCharacter = true
            val character = codePoint.toChar()

            if (inQuotes) {
                if (character == '"') {
                    val next = reader.read()
                    if (next == '"'.code) {
                        field?.append('"')
                        fieldCharacterCount++
                    } else {
                        inQuotes = false
                        if (next != -1) reader.unread(next)
                    }
                } else {
                    field?.append(character)
                    fieldCharacterCount++
                }
                continue
            }

            when (character) {
                '"' -> {
                    if (fieldCharacterCount == 0) {
                        inQuotes = true
                    } else {
                        field?.append(character)
                        fieldCharacterCount++
                    }
                }

                ',' -> finishField()
                '\n' -> {
                    finishField()
                    return fieldIndex
                }

                '\r' -> {
                    val next = reader.read()
                    if (next != '\n'.code && next != -1) reader.unread(next)
                    finishField()
                    return fieldIndex
                }

                else -> {
                    field?.append(character)
                    fieldCharacterCount++
                }
            }
        }
    }

    override fun close() = reader.close()

    private companion object {
        const val NOT_SELECTED = -1
        const val BUFFER_SIZE = 256 * 1024
    }
}
