package org.jjikmuk.backend.domain.product

import tools.jackson.databind.json.JsonMapper
import java.security.MessageDigest

/** The same observation encoding is used by regular imports and bounded maintenance. */
object CatalogAttributePayload {
    private val mapper = JsonMapper.builder().findAndAddModules().build()

    fun encode(row: Map<String, Any?>): String = mapper.writeValueAsString(
        CatalogEvolutionService.FIELDS.associateWith { key ->
            val value = row[key]
            if (key.startsWith("is_")) when (value) {
                is Boolean -> value
                is Number -> value.toInt() != 0
                is ByteArray -> value.any { it.toInt() != 0 }
                else -> value
            } else value
        }
    )

    fun hash(encoded: String): String = MessageDigest.getInstance("SHA-256")
        .digest(encoded.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

    fun changedFields(previous: String?, encoded: String): List<String> {
        val old = previous?.let(mapper::readTree)
        val now = mapper.readTree(encoded)
        return CatalogEvolutionService.FIELDS.filter { old?.get(it) != now.get(it) }
    }
}
