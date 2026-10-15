package org.jjikmuk.backend.domain.product

import java.math.BigDecimal
import java.text.Normalizer
import java.util.Locale

/** Only explicit total_weight values are interpreted. Never infer capacity from names/nutrients. */
internal data class ProductCapacity(val amount: BigDecimal?, val unit: String?) {
    val key: String get() = if (amount == null) "unknown" else "$unit:${amount.toPlainString()}"
    val label: String get() = if (amount == null) "용량 정보 없음" else "${amount.toPlainString()}$unit"

    companion object {
        private val UNKNOWN = ProductCapacity(null, null)
        private const val NUMBER = "((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\\.[0-9]+)?)"
        private const val UNIT = "(kg|mg|ml|g|l|킬로그램|밀리그램|밀리리터|그램|그람|리터)"
        private const val COUNT = "([0-9]+)(?:개|입|봉|팩|병|포|매)?"
        private val SINGLE = Regex("^$NUMBER$UNIT$")
        private val PACK = Regex("^$NUMBER$UNIT[x×*]$COUNT$")
        private val PREFIX = Regex("^(?:총내용량|총중량|내용량)[:：]?")

        fun parse(raw: String?): ProductCapacity {
            if (raw.isNullOrBlank() || raw.length > 128) return UNKNOWN
            val text = Normalizer.normalize(raw, Normalizer.Form.NFKC)
                .lowercase(Locale.ROOT).filterNot(Char::isWhitespace).replace(PREFIX, "")
            val match = SINGLE.matchEntire(text) ?: PACK.matchEntire(text) ?: return UNKNOWN
            val amount = match.groupValues[1].replace(",", "").toBigDecimalOrNull() ?: return UNKNOWN
            val count = if (match.groupValues.size > 3) match.groupValues[3].toBigDecimal() else BigDecimal.ONE
            if (amount.signum() <= 0 || count.signum() <= 0) return UNKNOWN
            val (unit, multiplier) = when (match.groupValues[2]) {
                "kg", "킬로그램" -> "g" to BigDecimal("1000")
                "mg", "밀리그램" -> "g" to BigDecimal("0.001")
                "g", "그램", "그람" -> "g" to BigDecimal.ONE
                "l", "리터" -> "ml" to BigDecimal("1000")
                else -> "ml" to BigDecimal.ONE
            }
            val normalized = amount.multiply(count).multiply(multiplier).stripTrailingZeros()
            // Avoid exponent notation in keys and JSON, including 1kg -> 1000g.
            return ProductCapacity(normalized.setScale(normalized.scale().coerceAtLeast(0)), unit)
        }
    }
}
