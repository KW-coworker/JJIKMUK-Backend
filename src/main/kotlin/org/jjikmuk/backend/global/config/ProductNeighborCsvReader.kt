package org.jjikmuk.backend.global.config

import java.io.Closeable
import java.io.InputStream
import java.io.InputStreamReader

internal const val PRODUCT_NEIGHBOR_TOP_K = 100
private val PRODUCT_NEIGHBOR_BARCODE_REGEX = Regex("\\d{8,14}")

internal data class ProductNeighborCsvRecord(
    val sourceBarcode: String,
    val modelVersion: String,
    val recommendationCount: Int,
    val recommendations: List<String>,
    val fieldCount: Int
) {
    init {
        require(sourceBarcode.matches(PRODUCT_NEIGHBOR_BARCODE_REGEX)) {
            "Invalid source barcode: $sourceBarcode"
        }
        require(modelVersion.isNotBlank()) { "Recommendation model version is blank" }
        require(recommendationCount == PRODUCT_NEIGHBOR_TOP_K) {
            "Expected $PRODUCT_NEIGHBOR_TOP_K recommendations, actual $recommendationCount"
        }
        require(recommendations.size == recommendationCount) {
            "Recommendation cell count mismatch: expected $recommendationCount, actual ${recommendations.size}"
        }

        val parsedBarcodes = recommendations.map(::parseRecommendationBarcode)
        require(parsedBarcodes.distinct().size == parsedBarcodes.size) {
            "Duplicate recommendation barcode for source $sourceBarcode"
        }
        require(sourceBarcode !in parsedBarcodes) {
            "Self recommendation found for source $sourceBarcode"
        }
    }

    fun serializedRecommendations(): String = recommendations.joinToString(",")

    private fun parseRecommendationBarcode(value: String): String {
        val separator = value.lastIndexOf('|')
        require(separator > 0 && separator < value.lastIndex) {
            "Invalid recommendation value: $value"
        }
        val barcode = value.substring(0, separator)
        val score = value.substring(separator + 1).toDoubleOrNull()
        require(barcode.matches(PRODUCT_NEIGHBOR_BARCODE_REGEX)) {
            "Invalid recommendation barcode: $barcode"
        }
        require(score != null && score.isFinite() && score in 0.0..1.0) {
            "Invalid recommendation score: ${value.substring(separator + 1)}"
        }
        return barcode
    }
}

internal class ProductNeighborCsvReader(inputStream: InputStream) : Closeable {
    private val csvReader = SelectiveRfc4180Reader(
        InputStreamReader(inputStream, Charsets.UTF_8)
    )

    val headerCount: Int

    init {
        val headers = csvReader.readHeader()
            ?: throw IllegalArgumentException("Recommendation CSV header is missing")
        val normalizedHeaders = headers.mapIndexed { index, header ->
            header.trim().removePrefix(if (index == 0) "\uFEFF" else "")
        }
        headerCount = normalizedHeaders.size

        val requiredHeaders = buildList {
            add("source_barcode")
            add("model_version")
            add("recommendation_count")
            addAll((1..PRODUCT_NEIGHBOR_TOP_K).map { rank -> "recommendation_%03d".format(rank) })
        }
        val missingHeaders = requiredHeaders.filterNot(normalizedHeaders::contains)
        require(missingHeaders.isEmpty()) {
            "Required recommendation CSV headers are missing: ${missingHeaders.joinToString()}"
        }
        csvReader.selectColumns(requiredHeaders.map(normalizedHeaders::indexOf))
    }

    fun readRecord(): ProductNeighborCsvRecord? {
        val selected = csvReader.readSelectedRecord() ?: return null
        val sourceBarcode = selected.values[0]?.trim().orEmpty()
        val modelVersion = selected.values[1]?.trim().orEmpty()
        val count = selected.values[2]?.trim()?.toIntOrNull()
            ?: throw IllegalArgumentException("Invalid recommendation_count for source $sourceBarcode")
        val recommendations = selected.values
            .drop(3)
            .mapNotNull { it?.trim()?.takeIf(String::isNotEmpty) }

        return ProductNeighborCsvRecord(
            sourceBarcode = sourceBarcode,
            modelVersion = modelVersion,
            recommendationCount = count,
            recommendations = recommendations,
            fieldCount = selected.fieldCount
        )
    }

    override fun close() = csvReader.close()
}
