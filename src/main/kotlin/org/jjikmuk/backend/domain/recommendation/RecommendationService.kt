package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductClassificationCatalog
import org.jjikmuk.backend.domain.product.ProductFilter
import org.jjikmuk.backend.domain.product.ProductFoodCategory
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.beans.factory.annotation.Value
import org.springframework.context.ApplicationEventPublisher
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.text.Normalizer
import java.time.Duration
import java.time.LocalDateTime
import java.util.UUID
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.round

@Service
@Transactional(readOnly = true)
class RecommendationService(
    private val neighborRepository: ProductNeighborSetRepository,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository,
    private val historyRepository: HistoryRepository,
    private val policy: RecommendationPolicy,
    private val eventPublisher: ApplicationEventPublisher,
    @Value("\${recommendation.ranking.similarity-weight:0.70}")
    private val similarityWeight: Double,
    @Value("\${recommendation.ranking.preference-weight:0.25}")
    private val preferenceWeight: Double,
    @Value("\${recommendation.ranking.data-quality-weight:0.05}")
    private val dataQualityWeight: Double,
    @Value("\${recommendation.ranking.mmr-relevance:0.85}")
    private val mmrRelevance: Double
) {
    fun recommendAlternatives(
        referenceBarcode: String,
        userId: Long,
        limit: Int,
        minSimilarityScore: Double
    ): ProductRecommendationResponse {
        validateRequest(limit, minSimilarityScore)
        val requestId = UUID.randomUUID().toString()
        val totalStartedAt = System.nanoTime()

        val user = userRepository.findById(userId).orElseThrow {
            CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")
        }
        val reference = productRepository.findById(referenceBarcode).orElseThrow {
            CustomException(HttpStatus.NOT_FOUND, "해당 바코드($referenceBarcode)의 제품을 찾을 수 없습니다.")
        }

        val neighborStartedAt = System.nanoTime()
        val neighborSet = neighborRepository.findById(referenceBarcode).orElseThrow {
            CustomException(
                HttpStatus.NOT_FOUND,
                "해당 상품의 사전 계산 추천 후보가 없습니다. ProductNeighbors.csv 적재 상태를 확인해주세요."
            )
        }
        val storedNeighbors = neighborSet.parseNeighbors()
        val neighborLookupMicros = elapsedMicros(neighborStartedAt)

        val productFetchStartedAt = System.nanoTime()
        val candidateProducts = productRepository.findAllById(storedNeighbors.map(StoredNeighbor::barcode))
            .associateBy(Product::barcode)
        val productFetchMicros = elapsedMicros(productFetchStartedAt)

        val allergies = policy.allergyProfileTerms(user.allergies)
        val dislikedIngredients = policy.profileTerms(user.dislikedIngredients)
        val requiredFilters = policy.requiredFilters(user)
        val historyStartedAt = System.nanoTime()
        val historyProfile = buildHistoryProfile(user, allergies, requiredFilters)
        val historyFetchMicros = elapsedMicros(historyStartedAt)

        var missingProduct = 0
        var lowSimilarity = 0
        var danger = 0
        var unknownSafety = 0
        var dietMismatch = 0
        var dietUnknown = 0
        var dislikedIngredient = 0

        val rankingStartedAt = System.nanoTime()
        val strictCandidates = mutableListOf<ScoredCandidate>()
        val relaxedSafeCandidates = mutableListOf<ScoredCandidate>()
        val verificationCandidates = mutableListOf<ScoredCandidate>()

        // DANGER, explicit diet mismatches and disliked ingredients never enter a fallback pool.
        storedNeighbors.forEach { neighbor ->
            val product = candidateProducts[neighbor.barcode]
            if (product == null) {
                missingProduct++
                return@forEach
            }

            val safety = policy.evaluateSafety(product, allergies)
            if (safety.status == SafetyStatus.DANGER) {
                danger++
                return@forEach
            }

            val diet = policy.evaluateDietConstraints(product, requiredFilters)
            if (diet.status == DietConstraintStatus.MISMATCH) {
                dietMismatch++
                return@forEach
            }
            if (policy.containsDislikedIngredient(product, dislikedIngredients)) {
                dislikedIngredient++
                return@forEach
            }

            val preferenceScore = preferenceScore(product, historyProfile.signals)
            val qualityScore = policy.dataQualityScore(product)
            val score = combinedScore(neighbor.similarityScore, preferenceScore, qualityScore)
            val candidate = ScoredCandidate(
                product = product,
                originalRank = neighbor.originalRank,
                baseSimilarity = neighbor.similarityScore,
                preferenceScore = preferenceScore,
                dataQualityScore = qualityScore,
                finalScore = score.value,
                safety = safety,
                diet = diet,
                scoreBreakdown = score.breakdown,
                reasons = buildReasons(
                    reference = reference,
                    product = product,
                    baseSimilarity = neighbor.similarityScore,
                    preference = preferenceScore,
                    diet = diet,
                    quality = qualityScore,
                    safety = safety
                )
            )

            when {
                safety.status == SafetyStatus.UNKNOWN -> {
                    unknownSafety++
                    verificationCandidates += candidate
                }
                diet.status == DietConstraintStatus.UNKNOWN -> {
                    dietUnknown++
                    verificationCandidates += candidate
                }
                neighbor.similarityScore < minSimilarityScore -> {
                    lowSimilarity++
                    relaxedSafeCandidates += candidate
                }
                else -> strictCandidates += candidate
            }
        }

        val selected = diversify(strictCandidates, limit)
        // A fallback is exposed separately so clients cannot mistake UNKNOWN for a verified recommendation.
        val fallbackSelection = when {
            selected.isNotEmpty() -> null
            relaxedSafeCandidates.isNotEmpty() -> selectFallback(relaxedSafeCandidates)
            verificationCandidates.isNotEmpty() -> selectFallback(verificationCandidates)
            else -> null
        }
        val resultMode = when {
            selected.isNotEmpty() -> RecommendationResultMode.VERIFIED
            fallbackSelection == null -> RecommendationResultMode.ACTION_REQUIRED
            fallbackSelection.candidate.safety.status == SafetyStatus.PASS &&
                fallbackSelection.candidate.diet.status == DietConstraintStatus.PASS -> {
                RecommendationResultMode.RELAXED_SAFE
            }
            else -> RecommendationResultMode.VERIFICATION_REQUIRED
        }
        val fallbackReason = when (resultMode) {
            RecommendationResultMode.VERIFIED -> null
            RecommendationResultMode.RELAXED_SAFE -> RecommendationFallbackReason.MINIMUM_SIMILARITY_RELAXED
            RecommendationResultMode.VERIFICATION_REQUIRED -> {
                RecommendationFallbackReason.INSUFFICIENT_VERIFICATION_DATA
            }
            RecommendationResultMode.ACTION_REQUIRED -> RecommendationFallbackReason.NO_RETURNABLE_CANDIDATE
        }
        val activeFallbackCandidateCount = when (resultMode) {
            RecommendationResultMode.VERIFIED,
            RecommendationResultMode.ACTION_REQUIRED -> 0
            RecommendationResultMode.RELAXED_SAFE -> relaxedSafeCandidates.size
            RecommendationResultMode.VERIFICATION_REQUIRED -> verificationCandidates.size
        }
        val responseRequiredActions = when (resultMode) {
            RecommendationResultMode.VERIFIED,
            RecommendationResultMode.RELAXED_SAFE -> emptyList()
            RecommendationResultMode.VERIFICATION_REQUIRED -> listOf(
                "제품 뒷면의 원재료와 알레르기 표시를 직접 확인하거나 촬영해 주세요."
            )
            RecommendationResultMode.ACTION_REQUIRED -> listOf(
                "다른 상품을 선택하거나 제품 뒷면의 원재료와 알레르기 표시를 촬영해 주세요."
            )
        }
        val rankingMicros = elapsedMicros(rankingStartedAt)
        val exclusions = RecommendationExclusionSummary(
            missingProduct = missingProduct,
            lowSimilarity = lowSimilarity,
            danger = danger,
            unknownSafety = unknownSafety,
            dietMismatch = dietMismatch,
            dietUnknown = dietUnknown,
            dislikedIngredient = dislikedIngredient
        )
        val timing = RecommendationTiming(
            neighborLookupMicros = neighborLookupMicros,
            productFetchMicros = productFetchMicros,
            historyFetchMicros = historyFetchMicros,
            rankingMicros = rankingMicros,
            totalMicros = elapsedMicros(totalStartedAt)
        )
        val response = ProductRecommendationResponse(
            requestId = requestId,
            referenceProduct = reference,
            referenceSafety = policy.evaluateSafety(reference, allergies),
            userContext = UserRecommendationContext(
                userId = userId,
                allergies = allergies,
                requiredDietFilters = requiredFilters.map(ProductFilter::key).sorted(),
                dislikedIngredients = dislikedIngredients,
                usableHistorySignals = historyProfile.eventCount,
                usableHistoryProducts = historyProfile.signals.size,
                positiveHistoryWeight = rounded(historyProfile.signals.sumOf { it.weight.coerceAtLeast(0.0) }),
                negativeHistoryWeight = rounded(historyProfile.signals.sumOf { it.weight.coerceAtMost(0.0) })
            ),
            policyVersion = POLICY_VERSION,
            modelVersion = neighborSet.modelVersion,
            precomputedCandidateCount = storedNeighbors.size,
            eligibleCandidateCount = strictCandidates.size,
            requestedLimit = limit,
            minSimilarityScore = minSimilarityScore,
            items = selected.map {
                toRecommendedProduct(it, RecommendationTier.VERIFIED, minSimilarityScore)
            },
            excluded = exclusions,
            timing = timing,
            fallbackItems = fallbackSelection?.let { selectedFallback ->
                val tier = if (resultMode == RecommendationResultMode.RELAXED_SAFE) {
                    RecommendationTier.RELAXED_SAFE
                } else {
                    RecommendationTier.VERIFICATION_REQUIRED
                }
                listOf(toRecommendedProduct(selectedFallback, tier, minSimilarityScore))
            }.orEmpty(),
            resultMode = resultMode,
            fallbackCandidateCount = activeFallbackCandidateCount,
            fallbackReason = fallbackReason,
            requiredActions = responseRequiredActions,
            notice = noticeFor(resultMode)
        )
        eventPublisher.publishEvent(RecommendationCompletedEvent.from(response, userId))
        return response
    }

    private fun validateRequest(limit: Int, minSimilarityScore: Double) {
        require(limit in 1..MAX_LIMIT) { "limit는 1~$MAX_LIMIT 범위여야 합니다." }
        require(minSimilarityScore in 0.0..1.0) { "minScore는 0~1 범위여야 합니다." }
        require(similarityWeight >= 0 && preferenceWeight >= 0 && dataQualityWeight >= 0) {
            "추천 랭킹 가중치는 0 이상이어야 합니다."
        }
        require(similarityWeight + dataQualityWeight > 0) {
            "유사도와 데이터 품질 가중치 중 하나는 0보다 커야 합니다."
        }
        require(mmrRelevance in 0.0..1.0) { "MMR relevance는 0~1 범위여야 합니다." }
    }

    private fun buildHistoryProfile(
        user: User,
        allergies: List<String>,
        requiredFilters: Set<ProductFilter>
    ): HistoryProfile {
        val histories = historyRepository.findTop200ByUserIdOrderByCreatedAtDesc(requireNotNull(user.id))
        if (histories.isEmpty()) return HistoryProfile(emptyList(), 0)
        val historyProducts = productRepository.findAllById(histories.map { it.barcode }.distinct())
            .associateBy(Product::barcode)
        val now = LocalDateTime.now()

        val eventSignals = histories.mapNotNull { history ->
            val product = historyProducts[history.barcode] ?: return@mapNotNull null
            if (history.actionType.preferenceWeight == 0.0) return@mapNotNull null
            if (policy.evaluateSafety(product, allergies).status != SafetyStatus.PASS) return@mapNotNull null
            if (policy.evaluateDietConstraints(product, requiredFilters).status != DietConstraintStatus.PASS) {
                return@mapNotNull null
            }
            val ageDays = Duration.between(history.createdAt, now).toMinutes().coerceAtLeast(0) / 1_440.0
            HistorySignal(
                product = product,
                weight = history.actionType.preferenceWeight * exp(-ageDays / HISTORY_DECAY_DAYS),
                explicit = history.actionType.explicitPreference
            )
        }
        val aggregated = eventSignals.groupBy { it.product.barcode }.values.map { sameProduct ->
            val explicitWeight = sameProduct.filter(HistorySignal::explicit)
                .sumOf(HistorySignal::weight)
                .coerceIn(-MAX_PRODUCT_HISTORY_WEIGHT, MAX_PRODUCT_HISTORY_WEIGHT)
            val passiveWeight = sameProduct.filterNot(HistorySignal::explicit)
                .sumOf(HistorySignal::weight)
                .coerceIn(0.0, MAX_PASSIVE_PRODUCT_WEIGHT)
            HistorySignal(
                product = sameProduct.first().product,
                weight = (explicitWeight + passiveWeight)
                    .coerceIn(-MAX_PRODUCT_HISTORY_WEIGHT, MAX_PRODUCT_HISTORY_WEIGHT),
                explicit = sameProduct.any(HistorySignal::explicit)
            )
        }.filter { abs(it.weight) >= MIN_HISTORY_WEIGHT }
        return HistoryProfile(aggregated, eventSignals.size)
    }

    private fun preferenceScore(candidate: Product, signals: List<HistorySignal>): Double? {
        if (signals.isEmpty()) return null
        val denominator = signals.sumOf { abs(it.weight) }
        if (denominator == 0.0) return null
        val raw = signals.sumOf { signal ->
            val similarity = if (signal.product.barcode == candidate.barcode) {
                1.0
            } else {
                productTextSimilarity(candidate, signal.product)
            }
            signal.weight * similarity
        } / denominator
        return (raw.coerceIn(-1.0, 1.0) + 1.0) / 2.0
    }

    private fun combinedScore(
        baseSimilarity: Double,
        preference: Double?,
        quality: Double
    ): WeightedScore {
        val activePreferenceWeight = preferenceWeight.takeIf { preference != null } ?: 0.0
        val denominator = similarityWeight + activePreferenceWeight + dataQualityWeight
        val normalizedSimilarityWeight = similarityWeight / denominator
        val normalizedPreferenceWeight = activePreferenceWeight / denominator
        val normalizedQualityWeight = dataQualityWeight / denominator
        val similarityContribution = normalizedSimilarityWeight * baseSimilarity
        val preferenceContribution = preference?.let { normalizedPreferenceWeight * it }
        val qualityContribution = normalizedQualityWeight * quality
        val value = (similarityContribution + (preferenceContribution ?: 0.0) + qualityContribution)
            .coerceIn(0.0, 1.0)
        return WeightedScore(
            value = value,
            breakdown = RecommendationScoreBreakdown(
                similarityWeight = rounded(normalizedSimilarityWeight),
                preferenceWeight = rounded(normalizedPreferenceWeight),
                dataQualityWeight = rounded(normalizedQualityWeight),
                similarityContribution = rounded(similarityContribution),
                preferenceContribution = preferenceContribution?.let(::rounded),
                dataQualityContribution = rounded(qualityContribution)
            )
        )
    }

    private fun buildReasons(
        reference: Product,
        product: Product,
        baseSimilarity: Double,
        preference: Double?,
        diet: DietConstraintDecision,
        quality: Double,
        safety: SafetyDecision
    ): List<String> = buildList {
        add("기준 상품과 콘텐츠 유사도 ${round(baseSimilarity * 100).toInt()}%")
        val sharedCategories = ProductClassificationCatalog.foodCategoryIds(reference.foodCategories)
            .intersect(ProductClassificationCatalog.foodCategoryIds(product.foodCategories).toSet())
        if (sharedCategories.isNotEmpty()) {
            val labels = sharedCategories.mapNotNull { id -> ProductFoodCategory.resolve(id)?.displayName }
            add("같은 식품 카테고리: ${labels.joinToString()}")
        } else if (!reference.foodType.isNullOrBlank() && reference.foodType == product.foodType) {
            add("같은 식품 유형: ${product.foodType}")
        }
        add("알레르기 판정 ${safety.status}: ${safety.evidenceSources.joinToString().ifBlank { "근거 없음" }}")
        if (diet.requiredFilters.isNotEmpty()) {
            when (diet.status) {
                DietConstraintStatus.PASS ->
                    add("필수 식단 조건 충족: ${diet.satisfiedFilters.joinToString()}")
                DietConstraintStatus.UNKNOWN ->
                    add("식단 조건 확인 필요: ${diet.uncertainFilters.joinToString()}")
                DietConstraintStatus.MISMATCH -> Unit
            }
        }
        if (preference != null && preference >= 0.55) add("최근 섭취·관심 이력과 유사")
        if (preference != null && preference < 0.45) add("비선호 이력과의 유사성이 있어 순위를 낮춤")
        if (quality >= 0.67) add("원재료·영양 등 비교 정보가 비교적 충분")
    }

    private fun diversify(candidates: List<ScoredCandidate>, limit: Int): List<SelectedCandidate> {
        val remaining = candidates.sortedByDescending(ScoredCandidate::finalScore).toMutableList()
        val selected = mutableListOf<SelectedCandidate>()
        while (selected.size < limit && remaining.isNotEmpty()) {
            val ranked = remaining.map { candidate ->
                val redundancy = selected.maxOfOrNull { selectedCandidate ->
                    displaySimilarity(candidate.product, selectedCandidate.candidate.product)
                } ?: 0.0
                candidate to (mmrRelevance * candidate.finalScore - (1.0 - mmrRelevance) * redundancy)
            }.sortedWith(
                compareByDescending<Pair<ScoredCandidate, Double>> { it.second }
                    .thenByDescending { it.first.finalScore }
                    .thenBy { it.first.originalRank }
                    .thenBy { it.first.product.barcode }
            )
            val (best, mmrScore) = ranked.first()
            selected += SelectedCandidate(best, mmrScore)
            remaining.remove(best)
        }
        return selected
    }

    private fun selectFallback(candidates: List<ScoredCandidate>): SelectedCandidate {
        val candidate = candidates.sortedWith(
            compareBy<ScoredCandidate> { fallbackRisk(it) }
                .thenBy { it.originalRank }
                .thenByDescending { it.finalScore }
                .thenByDescending { it.dataQualityScore }
                .thenBy { it.product.barcode }
        ).first()
        return SelectedCandidate(candidate, mmrRelevance * candidate.finalScore)
    }

    private fun fallbackRisk(candidate: ScoredCandidate): Int = when {
        candidate.safety.status == SafetyStatus.PASS &&
            candidate.diet.status == DietConstraintStatus.PASS -> 0
        candidate.safety.status == SafetyStatus.PASS -> 1
        candidate.diet.status == DietConstraintStatus.PASS -> 2
        else -> 3
    }

    private fun toRecommendedProduct(
        selected: SelectedCandidate,
        tier: RecommendationTier,
        minSimilarityScore: Double
    ): RecommendedProduct {
        val candidate = selected.candidate
        val warnings = when (tier) {
            RecommendationTier.VERIFIED -> emptyList()
            RecommendationTier.RELAXED_SAFE -> listOf(
                "안전·식단 조건은 통과했지만 기준 유사도 ${rounded(minSimilarityScore)} 미만인 대안입니다."
            )
            RecommendationTier.VERIFICATION_REQUIRED -> buildList {
                if (candidate.safety.status == SafetyStatus.UNKNOWN) add(candidate.safety.message)
                if (candidate.diet.status == DietConstraintStatus.UNKNOWN) add(candidate.diet.message)
                add("이 상품은 안전 추천이 아니며 실제 포장 라벨 확인 전에는 섭취 판단에 사용하면 안 됩니다.")
            }.distinct()
        }
        val requiredActions = if (tier == RecommendationTier.VERIFICATION_REQUIRED) {
            listOf("제품 뒷면의 원재료와 알레르기 표시를 직접 확인하거나 촬영해 주세요.")
        } else {
            emptyList()
        }
        return RecommendedProduct(
            product = candidate.product,
            originalRank = candidate.originalRank,
            baseSimilarityScore = rounded(candidate.baseSimilarity),
            preferenceScore = candidate.preferenceScore?.let(::rounded),
            dataQualityScore = rounded(candidate.dataQualityScore),
            finalScore = rounded(candidate.finalScore),
            mmrScore = rounded(selected.mmrScore),
            safety = candidate.safety,
            dietConstraints = candidate.diet,
            dataEvidence = ProductDataEvidence(
                allergyEvidenceLevel = candidate.product.allergyEvidenceLevel,
                allergyConfidence = candidate.product.allergyDataConfidence,
                nutritionOrigin = candidate.product.nutritionDataOrigin,
                nutritionConfidence = candidate.product.nutritionDataConfidence,
                dietaryOrigin = candidate.product.dietaryDataOrigin,
                dietaryConfidence = candidate.diet.confidence
            ),
            scoreBreakdown = candidate.scoreBreakdown,
            reasons = candidate.reasons,
            recommendationTier = tier,
            verificationRequired = tier == RecommendationTier.VERIFICATION_REQUIRED,
            warnings = warnings,
            requiredActions = requiredActions
        )
    }

    private fun noticeFor(resultMode: RecommendationResultMode): String = when (resultMode) {
        RecommendationResultMode.VERIFIED ->
            "추천 결과는 표기 데이터 기반이며 실제 포장 라벨과 의료 전문가의 지침을 우선해야 합니다."
        RecommendationResultMode.RELAXED_SAFE ->
            "엄격한 안전·식단 조건은 유지하고 유사도 기준만 완화한 대안입니다."
        RecommendationResultMode.VERIFICATION_REQUIRED ->
            "안전성을 확정할 근거가 부족한 확인 필요 대안입니다. 실제 포장 라벨 확인 전에는 섭취 판단에 사용하지 마세요."
        RecommendationResultMode.ACTION_REQUIRED ->
            "위험 또는 명시적 조건 불일치 상품은 결과 수를 채우기 위해 반환하지 않습니다."
    }

    private fun displaySimilarity(left: Product, right: Product): Double {
        val leftName = normalize(left.cleanProductName ?: left.productName)
        val rightName = normalize(right.cleanProductName ?: right.productName)
        val leftManufacturer = normalize(left.manufacturer)
        val rightManufacturer = normalize(right.manufacturer)
        if (leftName.isNotEmpty() && leftName == rightName && leftManufacturer == rightManufacturer) return 1.0
        val nameSimilarity = dice(charBigrams(leftName), charBigrams(rightName))
        val manufacturerBonus = if (leftManufacturer.isNotEmpty() && leftManufacturer == rightManufacturer) 0.25 else 0.0
        return (nameSimilarity * 0.75 + manufacturerBonus).coerceAtMost(1.0)
    }

    private fun productTextSimilarity(left: Product, right: Product): Double {
        val nameSimilarity = dice(
            charBigrams(normalize(left.cleanProductName ?: left.productName)),
            charBigrams(normalize(right.cleanProductName ?: right.productName))
        )
        val ingredientSimilarity = dice(wordTokens(left.rawMaterials), wordTokens(right.rawMaterials))
        val leftCategories = ProductClassificationCatalog.foodCategoryIds(left.foodCategories).toSet()
        val rightCategories = ProductClassificationCatalog.foodCategoryIds(right.foodCategories).toSet()
        val categorySimilarity = if (leftCategories.isNotEmpty() && rightCategories.isNotEmpty()) {
            jaccard(leftCategories, rightCategories)
        } else {
            null
        }
        val typeSimilarity = categorySimilarity ?: if (
            !left.foodType.isNullOrBlank() && normalize(left.foodType) == normalize(right.foodType)
        ) 1.0 else 0.0
        val available = mutableListOf(0.70 to nameSimilarity)
        if (ingredientSimilarity > 0.0) available += 0.20 to ingredientSimilarity
        if (categorySimilarity != null || typeSimilarity > 0.0) available += 0.10 to typeSimilarity
        val denominator = available.sumOf { it.first }
        return available.sumOf { (weight, score) -> weight * score } / denominator
    }

    private fun charBigrams(value: String): Set<String> = when {
        value.isEmpty() -> emptySet()
        value.length == 1 -> setOf(value)
        else -> (0 until value.length - 1).mapTo(linkedSetOf()) { index -> value.substring(index, index + 2) }
    }

    private fun wordTokens(value: String?): Set<String> = Normalizer
        .normalize(value.orEmpty(), Normalizer.Form.NFKC)
        .lowercase()
        .split(Regex("[^가-힣a-z0-9]+"))
        .filterTo(linkedSetOf()) { it.length >= 2 }

    private fun dice(left: Set<String>, right: Set<String>): Double {
        if (left.isEmpty() || right.isEmpty()) return 0.0
        return 2.0 * left.count(right::contains) / (left.size + right.size)
    }

    private fun jaccard(left: Set<String>, right: Set<String>): Double {
        if (left.isEmpty() || right.isEmpty()) return 0.0
        return left.intersect(right).size.toDouble() / left.union(right).size.toDouble()
    }

    private fun normalize(value: String?): String = Normalizer
        .normalize(value.orEmpty(), Normalizer.Form.NFKC)
        .lowercase()
        .filter { it.isLetterOrDigit() }

    private fun elapsedMicros(startedAt: Long): Long = ((System.nanoTime() - startedAt) / 1_000)
        .coerceAtLeast(0)

    private fun rounded(value: Double): Double = round(value * 1_000_000) / 1_000_000

    private data class HistoryProfile(val signals: List<HistorySignal>, val eventCount: Int)
    private data class HistorySignal(
        val product: Product,
        val weight: Double,
        val explicit: Boolean
    )
    private data class WeightedScore(val value: Double, val breakdown: RecommendationScoreBreakdown)

    private data class ScoredCandidate(
        val product: Product,
        val originalRank: Int,
        val baseSimilarity: Double,
        val preferenceScore: Double?,
        val dataQualityScore: Double,
        val finalScore: Double,
        val safety: SafetyDecision,
        val diet: DietConstraintDecision,
        val scoreBreakdown: RecommendationScoreBreakdown,
        val reasons: List<String>
    )

    private data class SelectedCandidate(val candidate: ScoredCandidate, val mmrScore: Double)

    companion object {
        const val POLICY_VERSION = "hard-constraints-personalized-category-v4"
        private const val MAX_LIMIT = 20
        private const val HISTORY_DECAY_DAYS = 30.0
        private const val MAX_PRODUCT_HISTORY_WEIGHT = 6.0
        private const val MAX_PASSIVE_PRODUCT_WEIGHT = 1.0
        private const val MIN_HISTORY_WEIGHT = 0.01
    }
}
