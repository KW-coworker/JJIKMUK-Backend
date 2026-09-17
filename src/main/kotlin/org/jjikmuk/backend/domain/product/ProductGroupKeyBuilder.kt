package org.jjikmuk.backend.domain.product

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.text.Normalizer
import java.util.Locale

/** Creates a deterministic identity for cards with the same displayed information. */
object ProductGroupKeyBuilder {
    fun build(
        productName: String?,
        manufacturer: String?,
        rawMaterials: String?,
        imageUrl: String?
    ): String {
        val identity = listOf(
            normalizeText(productName),
            normalizeText(manufacturer),
            normalizeRawMaterials(rawMaterials),
            normalizeUrl(imageUrl)
        ).joinToString(FIELD_SEPARATOR)

        return MessageDigest.getInstance("SHA-256")
            .digest(identity.toByteArray(StandardCharsets.UTF_8))
            .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
    }

    private fun normalizeText(value: String?): String = normalize(value)
        .trim()
        .replace(WHITESPACE, " ")

    private fun normalizeRawMaterials(value: String?): String = normalize(value)
        .filterNot(Char::isWhitespace)

    private fun normalizeUrl(value: String?): String = Normalizer
        .normalize(value.orEmpty(), Normalizer.Form.NFKC)
        .trim()

    private fun normalize(value: String?): String = Normalizer
        .normalize(value.orEmpty(), Normalizer.Form.NFKC)
        .lowercase(Locale.ROOT)

    private const val FIELD_SEPARATOR = "\u001f"
    private val WHITESPACE = Regex("\\s+")
}
