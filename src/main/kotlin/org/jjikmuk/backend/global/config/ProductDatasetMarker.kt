package org.jjikmuk.backend.global.config

import java.nio.charset.StandardCharsets
import java.util.Base64

internal data class ProductDatasetMarker(
    val version: String,
    val sha256: String,
    val rowCount: Long
) {
    init {
        require(version.isNotBlank()) { "Dataset version must not be blank" }
        require(sha256.matches(Regex("[0-9a-f]{64}"))) { "Dataset SHA-256 is invalid" }
        require(rowCount >= 0) { "Dataset row count must not be negative" }
    }

    fun encode(): String = listOf(
        PREFIX,
        Base64.getUrlEncoder().withoutPadding()
            .encodeToString(version.toByteArray(StandardCharsets.UTF_8)),
        sha256,
        rowCount.toString()
    ).joinToString("|")

    companion object {
        private const val PREFIX = "jjikmuk-product-v1"

        fun decode(value: String?): ProductDatasetMarker? {
            val fields = value?.split('|') ?: return null
            if (fields.size != 4 || fields[0] != PREFIX) return null
            return runCatching {
                val version = String(
                    Base64.getUrlDecoder().decode(fields[1]),
                    StandardCharsets.UTF_8
                )
                ProductDatasetMarker(
                    version = version,
                    sha256 = fields[2],
                    rowCount = fields[3].toLong()
                )
            }.getOrNull()
        }
    }
}
