package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductDataOrigin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith

class RecommendationOfflineEvaluatorTest {
    @Test
    fun `calculates ranking safety diversity and latency metrics`() {
        val first = evaluationResponse("REQ-1", listOf("A", "B"))
        val second = evaluationResponse("REQ-2", listOf("C"))

        val report = RecommendationOfflineEvaluator.evaluate(
            listOf(
                RecommendationEvaluationCase("case-1", setOf("B"), first, 100),
                RecommendationEvaluationCase("case-2", setOf("Z"), second, 300)
            ),
            catalogSize = 3
        )

        assertEquals(0.5, report.hitRateAtK)
        assertEquals(0.25, report.meanReciprocalRank)
        assertEquals(0.0, report.hardConstraintViolationRate)
        assertEquals(0.0, report.unknownSafetyRate)
        assertEquals(0.0, report.verificationRequiredRate)
        assertEquals(0.0, report.fallbackCaseRate)
        assertEquals(0.0, report.emptyResponseRate)
        assertEquals(1.0, report.catalogCoverage)
        assertEquals(300, report.p95LatencyMicros)
        assertTrue(report.ndcgAtK > 0.0)
    }

    @Test
    fun `measures explicit verification fallback without treating unknown as danger`() {
        val base = evaluationResponse("REQ-FALLBACK", listOf("FALLBACK-A"))
        val fallbackItem = base.items.single().copy(
            safety = base.items.single().safety.copy(
                status = SafetyStatus.UNKNOWN,
                evidenceLevel = AllergyEvidenceLevel.INGREDIENT_DERIVED,
                message = "공식 알레르기 표기 근거 부족"
            ),
            recommendationTier = RecommendationTier.VERIFICATION_REQUIRED,
            verificationRequired = true,
            warnings = listOf("라벨 확인 필요"),
            requiredActions = listOf("제품 뒷면 확인")
        )
        val response = base.copy(
            eligibleCandidateCount = 0,
            items = emptyList(),
            fallbackItems = listOf(fallbackItem),
            resultMode = RecommendationResultMode.VERIFICATION_REQUIRED,
            fallbackCandidateCount = 1,
            fallbackReason = RecommendationFallbackReason.INSUFFICIENT_VERIFICATION_DATA
        )

        val report = RecommendationOfflineEvaluator.evaluate(
            cases = listOf(
                RecommendationEvaluationCase(
                    caseId = "fallback-case",
                    expectedRelevantBarcodes = setOf("FALLBACK-A"),
                    response = response,
                    latencyMicros = 200,
                    expectedOutcome = ExpectedRecommendationOutcome.VERIFICATION_REQUIRED
                )
            ),
            catalogSize = 10
        )

        assertEquals(0.0, report.hitRateAtK)
        assertEquals(0, report.rankingCaseCount)
        assertEquals(1.0, report.verificationFallbackHitRate)
        assertEquals(1.0, report.outcomeMatchRate)
        assertEquals(0.0, report.hardConstraintViolationRate)
        assertEquals(1.0, report.unknownSafetyRate)
        assertEquals(1.0, report.verificationRequiredRate)
        assertEquals(1.0, report.fallbackCaseRate)
        assertEquals(0.0, report.emptyResponseRate)
        assertEquals(1, report.results.single().verificationRequiredItems)
        assertEquals(RecommendationResultMode.VERIFICATION_REQUIRED, report.results.single().resultMode)
    }

    @Test
    fun `correct abstention passes despite a one hundred percent empty response rate`() {
        val response = evaluationResponse("EMPTY", emptyList()).copy(requiredActions = listOf("라벨 확인"))
        val report = RecommendationOfflineEvaluator.evaluate(listOf(RecommendationEvaluationCase(
            "abstain", emptySet(), response, 100, ExpectedRecommendationOutcome.ABSTAIN, setOf("DANGER")
        )), 10)
        assertEquals(1.0, report.emptyResponseRate)
        assertEquals(0.0, report.unexpectedEmptyResponseRate)
        assertEquals(1.0, report.correctAbstentionRate)
        assertEquals(0, report.rankingCaseCount)
        assertTrue(RecommendationEvaluationThresholds().passes(report))
    }

    @Test
    fun `unexpected empty response fails but correct abstention is excluded from hit denominator`() {
        val positive = evaluationResponse("OK", listOf("A"))
        val empty = evaluationResponse("EMPTY", emptyList()).copy(requiredActions = listOf("라벨 확인"))
        val report = RecommendationOfflineEvaluator.evaluate(listOf(
            RecommendationEvaluationCase("positive", setOf("A"), positive, 100),
            RecommendationEvaluationCase("abstain", emptySet(), empty, 100, ExpectedRecommendationOutcome.ABSTAIN)
        ), 10)
        assertEquals(1.0, report.hitRateAtK)
        assertEquals(0.5, report.emptyResponseRate)
        assertTrue(RecommendationEvaluationThresholds().passes(report))
        val incorrect = RecommendationOfflineEvaluator.evaluate(listOf(
            RecommendationEvaluationCase("missing", setOf("A"), empty, 100)
        ), 10)
        assertEquals(1.0, incorrect.unexpectedEmptyResponseRate)
        assertFalse(RecommendationEvaluationThresholds().passes(incorrect))
    }

    @Test
    fun `reviewer forbidden labels catch a product the algorithm incorrectly marked PASS`() {
        val report = RecommendationOfflineEvaluator.evaluate(listOf(RecommendationEvaluationCase(
            "gold-danger", setOf("A"), evaluationResponse("BAD", listOf("A", "DANGER")), 100,
            forbiddenBarcodes = setOf("DANGER")
        )), 10)
        assertEquals(0.5, report.hardConstraintViolationRate)
        assertFalse(RecommendationEvaluationThresholds().passes(report))
    }

    @Test
    fun `unknown in the verified channel and danger in the secondary channel both fail`() {
        val base = evaluationResponse("BROKEN", listOf("A"))
        val unknown = base.items.single().copy(dietConstraints = base.items.single().dietConstraints.copy(status = DietConstraintStatus.UNKNOWN))
        val danger = base.items.single().copy(product = Product(barcode = "DANGER"),
            safety = base.items.single().safety.copy(status = SafetyStatus.DANGER))
        val report = RecommendationOfflineEvaluator.evaluate(listOf(RecommendationEvaluationCase(
            "bad-channel", setOf("A"), base.copy(items = listOf(unknown), fallbackItems = listOf(danger)), 100
        )), 10)
        assertEquals(0.0, report.hitRateAtK)
        assertEquals(0.5, report.hardConstraintViolationRate)
        assertEquals(2, report.presentationViolationCount)
        assertFalse(RecommendationEvaluationThresholds().passes(report))
    }

    @Test
    fun `fixed K denominator penalizes omitted relevant products and duplicate hits`() {
        val response = evaluationResponse("SHORT", listOf("A"))
        val report = RecommendationOfflineEvaluator.evaluate(listOf(
            RecommendationEvaluationCase("short", setOf("A", "B"), response, 100)
        ), 10, k = 2)
        assertTrue(report.ndcgAtK < 1.0)
        val duplicate = RecommendationOfflineEvaluator.evaluate(listOf(
            RecommendationEvaluationCase("duplicate", setOf("A", "B"), evaluationResponse("DUP", listOf("A", "A")), 100)
        ), 10, k = 2)
        assertEquals(report.ndcgAtK, duplicate.ndcgAtK)
        assertEquals(1, duplicate.presentationViolationCount)
    }

    @Test
    fun `invalid ground truth labels fail explicitly`() {
        val empty = evaluationResponse("EMPTY", emptyList())
        assertFailsWith<IllegalArgumentException> {
            RecommendationOfflineEvaluator.evaluate(listOf(RecommendationEvaluationCase("empty-positive", emptySet(), empty, 0)), 10)
        }
        assertFailsWith<IllegalArgumentException> {
            RecommendationOfflineEvaluator.evaluate(listOf(RecommendationEvaluationCase("contradiction", setOf("A"), empty, 0,
                forbiddenBarcodes = setOf("A"))), 10)
        }
    }

    @Test
    fun `safe similarity-only fallback counts as eligible recommendation but not unknown fallback`() {
        val base = evaluationResponse("SAFE-FALLBACK", listOf("A"))
        val response = base.copy(items = emptyList(), resultMode = RecommendationResultMode.RELAXED_SAFE,
            fallbackItems = listOf(base.items.single().copy(recommendationTier = RecommendationTier.RELAXED_SAFE)))
        val report = RecommendationOfflineEvaluator.evaluate(listOf(
            RecommendationEvaluationCase("relaxed-safe", setOf("A"), response, 100)
        ), 10)
        assertEquals(1.0, report.hitRateAtK)
        assertEquals(1.0, report.outcomeMatchRate)
        assertTrue(RecommendationEvaluationThresholds().passes(report))
    }

    @Test
    fun `verification fallback must contain real warnings and follow-up actions`() {
        val base = evaluationResponse("NO-WARNING", listOf("A"))
        val item = base.items.single().copy(
            safety = base.items.single().safety.copy(status = SafetyStatus.UNKNOWN),
            recommendationTier = RecommendationTier.VERIFICATION_REQUIRED, verificationRequired = true,
            warnings = listOf(" "), requiredActions = listOf("라벨 확인")
        )
        val response = base.copy(items = emptyList(), fallbackItems = listOf(item), resultMode = RecommendationResultMode.VERIFICATION_REQUIRED)
        val report = RecommendationOfflineEvaluator.evaluate(listOf(
            RecommendationEvaluationCase("unlabelled", setOf("A"), response, 100, ExpectedRecommendationOutcome.VERIFICATION_REQUIRED)
        ), 10)
        assertEquals(0.0, report.hitRateAtK)
        assertEquals(0.0, report.verificationFallbackHitRate)
        assertEquals(1, report.presentationViolationCount)
        assertFalse(RecommendationEvaluationThresholds().passes(report))
    }

    private fun evaluationResponse(requestId: String, barcodes: List<String>): ProductRecommendationResponse {
        val safety = SafetyDecision(
            status = SafetyStatus.PASS,
            conflictingAllergens = emptyList(),
            evidenceSources = listOf("allergy_warning"),
            evidenceLevel = AllergyEvidenceLevel.DECLARED_LABEL,
            confidence = 0.95,
            message = "통과"
        )
        val diet = DietConstraintDecision(
            status = DietConstraintStatus.PASS,
            requiredFilters = emptyList(),
            satisfiedFilters = emptyList(),
            failedFilters = emptyList(),
            uncertainFilters = emptyList(),
            evidenceOrigin = ProductDataOrigin.INFERRED,
            confidence = 0.8,
            message = "통과"
        )
        val items = barcodes.mapIndexed { index, barcode ->
            RecommendedProduct(
                product = Product(barcode = barcode, productName = barcode),
                originalRank = index + 1,
                baseSimilarityScore = 0.8,
                preferenceScore = 0.7,
                dataQualityScore = 0.8,
                finalScore = 0.78,
                mmrScore = 0.6,
                safety = safety,
                dietConstraints = diet,
                dataEvidence = ProductDataEvidence(
                    AllergyEvidenceLevel.DECLARED_LABEL,
                    0.95,
                    ProductDataOrigin.SOURCE,
                    0.9,
                    ProductDataOrigin.INFERRED,
                    0.8
                ),
                scoreBreakdown = RecommendationScoreBreakdown(
                    0.7, 0.25, 0.05, 0.56, 0.175, 0.04
                ),
                reasons = emptyList()
            )
        }
        return ProductRecommendationResponse(
            requestId = requestId,
            referenceProduct = Product(barcode = "REFERENCE-$requestId"),
            referenceSafety = safety,
            userContext = UserRecommendationContext(1, emptyList(), emptyList(), emptyList(), 0, 0, 0.0, 0.0),
            policyVersion = RecommendationService.POLICY_VERSION,
            modelVersion = "test-model",
            precomputedCandidateCount = items.size,
            eligibleCandidateCount = items.size,
            requestedLimit = 10,
            minSimilarityScore = 0.0,
            items = items,
            excluded = RecommendationExclusionSummary(0, 0, 0, 0, 0, 0, 0),
            timing = RecommendationTiming(0, 0, 0, 0, 0)
        )
    }
}
