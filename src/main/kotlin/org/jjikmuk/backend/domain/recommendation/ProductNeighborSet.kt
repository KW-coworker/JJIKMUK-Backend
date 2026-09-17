package org.jjikmuk.backend.domain.recommendation

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.Id
import jakarta.persistence.Table

@Entity
@Table(name = "product_neighbor_sets")
class ProductNeighborSet(
    @Id
    @Column(name = "source_barcode", nullable = false, length = 32)
    val sourceBarcode: String,

    @Column(name = "model_version", nullable = false, length = 100)
    val modelVersion: String,

    @Column(name = "recommendation_count", nullable = false)
    val recommendationCount: Int,

    @Column(name = "recommendations", nullable = false, columnDefinition = "TEXT")
    val recommendations: String
)

data class StoredNeighbor(
    val barcode: String,
    val similarityScore: Double,
    val originalRank: Int
)

fun ProductNeighborSet.parseNeighbors(): List<StoredNeighbor> =
    recommendations.split(',')
        .asSequence()
        .map(String::trim)
        .filter(String::isNotEmpty)
        .mapIndexedNotNull { index, value ->
            val separator = value.lastIndexOf('|')
            if (separator <= 0 || separator == value.lastIndex) return@mapIndexedNotNull null
            val barcode = value.substring(0, separator)
            val score = value.substring(separator + 1).toDoubleOrNull()
                ?.takeIf { it.isFinite() && it in 0.0..1.0 }
                ?: return@mapIndexedNotNull null
            StoredNeighbor(barcode, score, index + 1)
        }
        .take(recommendationCount)
        .toList()
