package org.jjikmuk.backend.domain.product

import org.junit.jupiter.api.Test
import tools.jackson.databind.json.JsonMapper
import java.security.MessageDigest
import kotlin.test.*

class CatalogAttributePayloadTest {
    @Test fun `encoding preserves legacy observation bytes and compares typed fields`() {
        val row = CatalogEvolutionService.FIELDS.associateWith { null as Any? }.toMutableMap().apply {
            put("product_name", "쌀 \"과자\""); put("energy_kcal", 100.0)
            put("is_vegan", byteArrayOf(1)); put("is_low_sugar", 0)
            put("allergy_evidence_level", "SOURCE_INGREDIENTS"); put("allergy_data_confidence", 0.42)
        }
        val expected = CatalogEvolutionService.FIELDS.associateWith { key ->
            when(key) { "is_vegan" -> true; "is_low_sugar" -> false; else -> row[key] }
        }
        val raw = JsonMapper.builder().findAndAddModules().build().writeValueAsString(expected)
        assertEquals(raw, CatalogAttributePayload.encode(row))
        assertEquals(MessageDigest.getInstance("SHA-256").digest(raw.toByteArray()).joinToString("") { "%02x".format(it) }, CatalogAttributePayload.hash(raw))
        assertEquals(emptyList(), CatalogAttributePayload.changedFields(raw, raw))
        val next = CatalogAttributePayload.encode(row + ("nutrition_basis_raw" to "100g"))
        assertEquals(listOf("nutrition_basis_raw"), CatalogAttributePayload.changedFields(raw, next))
        assertEquals(CatalogEvolutionService.FIELDS, CatalogAttributePayload.changedFields(null, raw))
    }
}
