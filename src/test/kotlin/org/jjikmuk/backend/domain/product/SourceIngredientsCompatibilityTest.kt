package org.jjikmuk.backend.domain.product

import jakarta.persistence.EntityManager
import org.jjikmuk.backend.domain.allergy.AllergySafetyService
import org.jjikmuk.backend.domain.recommendation.SafetyStatus
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.transaction.annotation.Transactional
import tools.jackson.databind.json.JsonMapper
import tools.jackson.databind.JsonNode
import kotlin.test.*

@SpringBootTest
@ActiveProfiles("test")
@Transactional
class SourceIngredientsCompatibilityTest @Autowired constructor(
    private val repository: ProductRepository,
    private val jdbc: JdbcTemplate,
    private val entityManager: EntityManager,
    private val safety: AllergySafetyService
) {
    @Test
    fun `database label and supplied confidence survive JPA and response serialization`() {
        repository.saveAndFlush(Product(barcode = "SOURCE-JPA", rawMaterials = "쌀"))
        jdbc.update("UPDATE products SET allergy_evidence_level=?, allergy_data_confidence=? WHERE barcode=?",
            "SOURCE_INGREDIENTS", 0.42, "SOURCE-JPA")
        entityManager.clear()
        val product = repository.findById("SOURCE-JPA").orElseThrow()
        assertEquals(AllergyEvidenceLevel.SOURCE_INGREDIENTS, product.allergyEvidenceLevel)
        assertEquals(0.42, product.allergyDataConfidence)
        val decision = safety.evaluate(product, listOf("milk"))
        assertEquals(SafetyStatus.UNKNOWN, decision.status)
        assertEquals(0.42, decision.confidence)
        val json = JsonMapper.builder().findAndAddModules().build().valueToTree<JsonNode>(decision)
        assertEquals("SOURCE_INGREDIENTS", json.get("evidenceLevel").asText())
        assertEquals("UNKNOWN", json.get("status").asText())
    }

    @Test
    fun `unverified source never grants pass but known conflicts are still dangerous`() {
        for (confidence in listOf(null, 0.0, 1.0)) {
            fun product(materials: String?) = Product(barcode = "SOURCE-SAFETY", rawMaterials = materials,
                allergyEvidenceLevel = AllergyEvidenceLevel.SOURCE_INGREDIENTS, allergyDataConfidence = confidence)
            assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(product("쌀"), listOf("milk")).status)
            assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(product(null), listOf("milk")).status)
            assertEquals(SafetyStatus.DANGER, safety.evaluate(product("쌀, 우유"), listOf("milk")).status)
            assertEquals(SafetyStatus.UNKNOWN, safety.evaluate(product("쌀"), listOf("milk"), false).status)
            assertEquals(SafetyStatus.PASS, safety.evaluate(product("쌀"), emptyList()).status)
        }
        assertNull(ProductDataQualityClassifier.allergyConfidence(AllergyEvidenceLevel.SOURCE_INGREDIENTS, 1.0))
    }

    @Test
    fun `existing evidence verdicts and conservative ordering remain unchanged`() {
        val legacy = listOf(AllergyEvidenceLevel.VERIFIED_SOURCE, AllergyEvidenceLevel.DECLARED_LABEL,
            AllergyEvidenceLevel.INGREDIENT_DERIVED, AllergyEvidenceLevel.INFERRED, AllergyEvidenceLevel.UNKNOWN)
        legacy.forEachIndexed { index, level ->
            val product = Product(barcode = "SOURCE-LEGACY-$index", rawMaterials = "쌀", allergyEvidenceLevel = level)
            assertEquals(if (index < 2) SafetyStatus.PASS else SafetyStatus.UNKNOWN,
                safety.evaluate(product, listOf("milk")).status)
            assertEquals(index, level.aggregationPriority)
        }
        assertEquals(AllergyEvidenceLevel.UNKNOWN.aggregationPriority,
            AllergyEvidenceLevel.SOURCE_INGREDIENTS.aggregationPriority)
        assertEquals(AllergyEvidenceLevel.INGREDIENT_DERIVED,
            ProductDataQualityClassifier.classifyAllergyEvidence(null, "쌀", null))
    }
}
