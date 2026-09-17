package org.jjikmuk.backend.global.config

import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.nio.file.Path
import org.junit.jupiter.api.Assumptions.assumeTrue
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ProductNeighborCsvReaderTest {
    @Test
    fun `full ProductNeighbors csv matches the import contract`() {
        assumeTrue(System.getenv("FULL_PRODUCT_NEIGHBOR_CSV_TEST") == "true")
        val path = Path.of("src/main/resources/data/ProductNeighbors.csv")
        assumeTrue(Files.exists(path))
        var rows = 0L
        val sources = HashSet<String>(300_000)

        ProductNeighborCsvReader(Files.newInputStream(path)).use { reader ->
            while (true) {
                val record = reader.readRecord() ?: break
                rows++
                assertEquals(reader.headerCount, record.fieldCount)
                assertEquals(true, sources.add(record.sourceBarcode))
                assertEquals(PRODUCT_NEIGHBOR_TOP_K, record.recommendations.size)
            }
        }

        assertEquals(233_658L, rows)
        assertEquals(233_658, sources.size)
    }

    @Test
    fun `reads and validates one hundred ranked recommendations`() {
        val recommendations = (1..PRODUCT_NEIGHBOR_TOP_K).map { rank ->
            "%013d|%.6f".format(8_800_000_000_000L + rank, 1.0 - rank / 200.0)
        }
        val csv = buildCsv("8801234567890", recommendations)

        ProductNeighborCsvReader(ByteArrayInputStream(csv.toByteArray(Charsets.UTF_8))).use { reader ->
            val record = requireNotNull(reader.readRecord())
            assertEquals("8801234567890", record.sourceBarcode)
            assertEquals("content_neighbors_v1", record.modelVersion)
            assertEquals(PRODUCT_NEIGHBOR_TOP_K, record.recommendationCount)
            assertEquals(recommendations, record.recommendations)
            assertEquals(recommendations.joinToString(","), record.serializedRecommendations())
            assertEquals(null, reader.readRecord())
        }
    }

    @Test
    fun `rejects self recommendation`() {
        val source = "8801234567890"
        val recommendations = (1..PRODUCT_NEIGHBOR_TOP_K).map { rank ->
            if (rank == 1) "$source|1.000000"
            else "%013d|%.6f".format(8_800_000_000_000L + rank, 1.0 - rank / 200.0)
        }
        val csv = buildCsv(source, recommendations)

        assertFailsWith<IllegalArgumentException> {
            ProductNeighborCsvReader(ByteArrayInputStream(csv.toByteArray(Charsets.UTF_8))).use { reader ->
                reader.readRecord()
            }
        }
    }

    private fun buildCsv(sourceBarcode: String, recommendations: List<String>): String {
        val headers = buildList {
            add("source_barcode")
            add("model_version")
            add("recommendation_count")
            addAll((1..PRODUCT_NEIGHBOR_TOP_K).map { "recommendation_%03d".format(it) })
        }
        val values = listOf(sourceBarcode, "content_neighbors_v1", PRODUCT_NEIGHBOR_TOP_K.toString()) + recommendations
        return "\uFEFF${headers.joinToString(",")}\n${values.joinToString(",")}\n"
    }
}
