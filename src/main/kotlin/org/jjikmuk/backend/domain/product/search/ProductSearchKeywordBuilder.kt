package org.jjikmuk.backend.domain.product.search

import java.text.Normalizer
import java.util.Locale

/**
 * Builds the internal text indexed by MySQL's ngram FULLTEXT parser.
 *
 * Ingredient and allergy text are deliberately excluded. Including them in a
 * product-name index makes name searches noisy and makes the index much larger.
 */
object ProductSearchKeywordBuilder {
    fun build(
        productName: String?,
        cleanProductName: String?,
        manufacturer: String?
    ): String {
        val originalTerms = listOf(productName, cleanProductName, manufacturer)
            .mapNotNull(::normalizeTerm)
            .distinct()
        val compactTerms = originalTerms
            .map(::compact)
            .filter(String::isNotEmpty)
            .distinct()

        return (originalTerms + compactTerms)
            .distinct()
            .joinToString(" ")
    }

    fun normalizeQuery(query: String): String = compact(query)

    fun normalizeForLog(query: String): String = normalizeTerm(query).orEmpty()

    /**
     * The ngram parser turns this into consecutive bigrams. Requiring the
     * quoted phrase avoids returning rows that contain only one common bigram.
     */
    fun toBooleanPhrase(query: String): String = normalizeQuery(query)
        .takeIf(String::isNotEmpty)
        ?.let { normalized -> "+\"$normalized\"" }
        .orEmpty()

    private fun normalizeTerm(value: String?): String? = value
        ?.let { Normalizer.normalize(it, Normalizer.Form.NFKC) }
        ?.lowercase(Locale.ROOT)
        ?.trim()
        ?.replace(WHITESPACE, " ")
        ?.takeIf(String::isNotEmpty)

    private fun compact(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFKC)
        .lowercase(Locale.ROOT)
        .filter(Char::isLetterOrDigit)

    private val WHITESPACE = Regex("\\s+")
}
