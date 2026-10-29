package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductFoodCategory
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.domain.user.EffectiveAnalysis
import org.jjikmuk.backend.domain.user.notEvaluatedSafety
import org.jjikmuk.backend.domain.user.withoutAnalysis
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.data.domain.PageRequest
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.nio.charset.StandardCharsets
import java.security.SecureRandom
import java.util.Base64
import java.util.Locale
import java.util.UUID
import kotlin.math.absoluteValue
import kotlin.random.Random

@Service
@Transactional(readOnly = true)
class SafeProductRecommendationService(
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository,
    private val policy: RecommendationPolicy
) {
    fun recommend(
        userId: Long,
        limit: Int,
        cursor: String?,
        seed: Long?,
        excludedBarcodes: Set<String>,
        requestedCategories: Set<ProductFoodCategory>,
        analysis: EffectiveAnalysis? = null
    ): SafeProductRecommendationResponse {
        require(limit in 1..MAX_LIMIT) { "limit는 1~$MAX_LIMIT 범위여야 합니다." }
        require(excludedBarcodes.size <= MAX_EXCLUDED_BARCODES) {
            "excludeBarcodes는 최대 ${MAX_EXCLUDED_BARCODES}개까지 전달할 수 있습니다."
        }

        val owner = userRepository.findById(userId).orElseThrow {
            CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")
        }
        val user = analysis?.profile ?: owner

        val allergies = policy.allergyProfileTerms(user.allergies)
        val dislikedIngredients = policy.profileTerms(user.dislikedIngredients)
        val preferences = policy.selectedDietFilters(user)
        val hardHealthFilters = policy.healthConstraintFilters(user)
        val requiredFilters = policy.requiredFilters(user)
        val requestedCategoryIds = requestedCategories.map(ProductFoodCategory::id).toSet()
        val context = listOf(userId, analysis?.selection, user.allergies, user.specialDiet, user.diseases,
            user.dislikedIngredients, requestedCategoryIds.sorted()).joinToString("|")
        val contextHash = java.security.MessageDigest.getInstance("SHA-256")
            .digest(context.toByteArray(StandardCharsets.UTF_8)).joinToString("") { "%02x".format(it) }
        val state = cursor?.let(CursorCodec::decode) ?: CursorState.initial(seed ?: nextSeed(), contextHash)
        if (state.contextHash != contextHash) throw IllegalArgumentException("분석 대상/조건이 바뀌었습니다. cursor 없이 다시 조회해주세요.")
        if (seed != null && seed != state.seed) throw IllegalArgumentException("cursor와 seed가 일치하지 않습니다.")
        val excludedGroupKeys = productRepository.findAllById(excludedBarcodes)
            .map(::displayIdentity)
            .toMutableSet()

        val strict = linkedMapOf<String, Candidate>()
        var currentState = state
        var exhausted = false
        var scanned = 0
        var danger = 0
        var unknownSafety = 0
        var dislikedIngredient = 0
        var healthMismatch = 0
        var healthUnknown = 0
        var dietMismatch = 0
        var dietUnknown = 0
        var categoryMismatch = 0
        var alreadyDeliveredOrDuplicate = 0
        var pageFilled = false

        while (!exhausted && scanned < MAX_SCANNED_CANDIDATES && !pageFilled) {
            val batchSize = minOf(CANDIDATE_BATCH_SIZE, MAX_SCANNED_CANDIDATES - scanned)
            val products = if (!currentState.wrapped) {
                productRepository.findByBarcodeGreaterThanOrderByBarcodeAsc(
                    currentState.afterBarcode,
                    PageRequest.of(0, batchSize)
                )
            } else {
                productRepository.findByBarcodeGreaterThanAndBarcodeLessThanEqualOrderByBarcodeAsc(
                    currentState.afterBarcode,
                    currentState.startBarcode,
                    PageRequest.of(0, batchSize)
                )
            }

            if (products.isEmpty()) {
                if (!currentState.wrapped) {
                    currentState = currentState.copy(afterBarcode = "", wrapped = true)
                    continue
                }
                exhausted = true
                break
            }

            for (product in products) {
                scanned++
                currentState = currentState.copy(afterBarcode = product.barcode)
                val identity = displayIdentity(product)
                if (product.barcode in excludedBarcodes || identity in excludedGroupKeys ||
                    identity in strict
                ) {
                    alreadyDeliveredOrDuplicate++
                    continue
                }

                val categoryIds = product.foodCategoryIds.ifEmpty {
                    listOf(ProductFoodCategory.UNCLASSIFIED.id)
                }
                if (requestedCategoryIds.isNotEmpty() && categoryIds.none(requestedCategoryIds::contains)) {
                    categoryMismatch++
                    continue
                }

                val safety = policy.evaluateSafety(product, allergies)
                when (safety.status) {
                    SafetyStatus.DANGER -> {
                        danger++
                        continue
                    }
                    SafetyStatus.UNKNOWN -> {
                        unknownSafety++
                        continue
                    }
                    SafetyStatus.PASS, SafetyStatus.NOT_EVALUATED -> Unit
                }

                if (policy.containsDislikedIngredient(product, dislikedIngredients)) {
                    dislikedIngredient++
                    continue
                }

                val health = policy.evaluateDietConstraints(product, hardHealthFilters)
                val diet = policy.evaluateDietConstraints(product, requiredFilters)
                when (diet.status) {
                    DietConstraintStatus.MISMATCH -> {
                        dietMismatch++
                        if (health.status == DietConstraintStatus.MISMATCH) healthMismatch++
                        continue
                    }
                    DietConstraintStatus.UNKNOWN -> {
                        dietUnknown++
                        if (health.status == DietConstraintStatus.UNKNOWN) healthUnknown++
                        continue
                    }
                    DietConstraintStatus.PASS, DietConstraintStatus.NOT_EVALUATED -> Unit
                }

                val preference = policy.evaluateDietConstraints(product, preferences)
                strict[identity] = Candidate(product, safety, health, preference, diet, categoryIds)

                if (strict.size >= limit) {
                    pageFilled = true
                    break
                }
            }

            if (!pageFilled && currentState.wrapped &&
                (products.size < batchSize || currentState.afterBarcode >= currentState.startBarcode)
            ) {
                exhausted = true
            } else if (!pageFilled && !currentState.wrapped && products.size < batchSize) {
                currentState = currentState.copy(afterBarcode = "", wrapped = true)
            }
        }

        val random = Random((state.seed xor state.afterBarcode.hashCode().toLong()).foldToInt())
        val selected = strict.values.shuffled(random).take(limit)
        val items = selected.map { candidate ->
            SafeProductRecommendationItem(
                product = candidate.product,
                safety = if (analysis?.applied == false) notEvaluatedSafety() else candidate.safety,
                healthConstraints = if (analysis?.applied == false) candidate.health.withoutAnalysis() else candidate.health,
                preferences = if (analysis?.applied == false) candidate.preference.withoutAnalysis() else candidate.preference,
                preferenceRelaxed = false,
                categoryIds = candidate.categoryIds,
                dietConstraints = if (analysis?.applied == false) candidate.diet.withoutAnalysis() else candidate.diet
            )
        }
        val groups = ProductFoodCategory.entries.mapNotNull { category ->
            val groupedItems = items.filter { category.id in it.categoryIds }
            if (groupedItems.isEmpty()) null
            else SafeRecommendationCategoryGroup(category.id, category.displayName, groupedItems)
        }
        val mode = when {
            analysis?.applied == false -> SafeRecommendationMode.GENERAL
            items.isEmpty() -> SafeRecommendationMode.EMPTY
            else -> SafeRecommendationMode.PREFERENCE_MATCHED
        }
        val nextCursor = if (exhausted) null else CursorCodec.encode(currentState)

        return SafeProductRecommendationResponse(
            requestId = UUID.randomUUID().toString(),
            userId = userId,
            seed = state.seed,
            requestedLimit = limit,
            returnedItemCount = items.size,
            returnedBarcodes = items.map { it.product.barcode },
            requestedCategoryIds = requestedCategoryIds.sorted(),
            preferenceFilterIds = preferences.map { it.key }.sorted(),
            hardHealthFilterIds = hardHealthFilters.map { it.key }.sorted(),
            requiredDietFilterIds = requiredFilters.map { it.key }.sorted(),
            recommendationMode = mode,
            categories = groups,
            nextCursor = nextCursor,
            hasNext = nextCursor != null,
            scannedCandidateCount = scanned,
            analysisSelection = analysis?.selection,
            notice = if (analysis?.applied == false) "분석 대상이 없어 개인 조건을 적용하지 않은 일반 상품 목록입니다."
                else "선택한 대상의 필수 조건을 모두 적용한 표기 데이터 기반 추천입니다. 실제 포장 표시를 확인해주세요.",
            exclusions = SafeRecommendationExclusionSummary(
                danger = danger,
                unknownSafety = unknownSafety,
                dislikedIngredient = dislikedIngredient,
                healthMismatch = healthMismatch,
                healthUnknown = healthUnknown,
                dietMismatch = dietMismatch,
                dietUnknown = dietUnknown,
                categoryMismatch = categoryMismatch,
                alreadyDeliveredOrDuplicate = alreadyDeliveredOrDuplicate
            )
        )
    }

    private fun displayIdentity(product: Product): String = product.productGroupKey
        ?.takeIf(String::isNotBlank)
        ?: listOf(
            product.productName,
            product.manufacturer,
            product.rawMaterials,
            product.imageUrl
        ).joinToString("|") { it.orEmpty().trim().lowercase() }

    private fun nextSeed(): Long = secureRandom.nextLong().let { value ->
        if (value == Long.MIN_VALUE) 0L else value.absoluteValue
    }

    private data class Candidate(
        val product: Product,
        val safety: SafetyDecision,
        val health: DietConstraintDecision,
        val preference: DietConstraintDecision,
        val diet: DietConstraintDecision,
        val categoryIds: List<String>
    )

    private data class CursorState(
        val seed: Long,
        val startBarcode: String,
        val afterBarcode: String,
        val wrapped: Boolean,
        val contextHash: String
    ) {
        companion object {
            fun initial(seed: Long, contextHash: String): CursorState {
                val random = Random((seed xor (seed ushr 32)).toInt())
                val startBarcode = if (random.nextInt(100) < SYNTHETIC_BARCODE_PERCENT) {
                    "NO_BARCODE_ROW_${random.nextInt(1, SYNTHETIC_BARCODE_MAX_ROW)}"
                } else {
                    String.format(
                        Locale.ROOT,
                        "%013d",
                        random.nextLong(0, MAX_NUMERIC_BARCODE_EXCLUSIVE)
                    )
                }
                return CursorState(seed, startBarcode, startBarcode, false, contextHash)
            }
        }
    }

    private object CursorCodec {
        private val encoder = Base64.getUrlEncoder().withoutPadding()
        private val decoder = Base64.getUrlDecoder()

        fun encode(state: CursorState): String {
            val value = listOf(
                CURSOR_VERSION,
                state.seed.toString(),
                encodePart(state.startBarcode),
                encodePart(state.afterBarcode),
                if (state.wrapped) "1" else "0",
                state.contextHash
            ).joinToString(".")
            return encoder.encodeToString(value.toByteArray(StandardCharsets.UTF_8))
        }

        fun decode(cursor: String): CursorState = try {
            require(cursor.length <= MAX_CURSOR_LENGTH)
            val decoded = String(decoder.decode(cursor), StandardCharsets.UTF_8).split('.')
            require(decoded.size == 6 && decoded[0] == CURSOR_VERSION)
            val seed = decoded[1].toLong()
            val start = decodePart(decoded[2])
            val after = decodePart(decoded[3])
            require(start.length <= MAX_BARCODE_LENGTH && after.length <= MAX_BARCODE_LENGTH)
            val wrapped = when (decoded[4]) {
                "0" -> false
                "1" -> true
                else -> error("invalid wrapped flag")
            }
            require(decoded[5].matches(Regex("[a-f0-9]{64}")))
            CursorState(seed, start, after, wrapped, decoded[5])
        } catch (_: Exception) {
            throw IllegalArgumentException("유효하지 않은 추천 cursor입니다.")
        }

        private fun encodePart(value: String): String =
            encoder.encodeToString(value.toByteArray(StandardCharsets.UTF_8))

        private fun decodePart(value: String): String =
            String(decoder.decode(value), StandardCharsets.UTF_8)
    }

    private fun Long.foldToInt(): Int = (this xor (this ushr 32)).toInt()

    private companion object {
        val secureRandom = SecureRandom()
        const val MAX_LIMIT = 50
        const val MAX_EXCLUDED_BARCODES = 200
        const val MAX_CURSOR_LENGTH = 1000
        const val MAX_BARCODE_LENGTH = 255
        const val CANDIDATE_BATCH_SIZE = 250
        const val MAX_SCANNED_CANDIDATES = 5_000
        const val SYNTHETIC_BARCODE_PERCENT = 80
        const val SYNTHETIC_BARCODE_MAX_ROW = 2_000_000
        const val MAX_NUMERIC_BARCODE_EXCLUSIVE = 10_000_000_000_000L
        const val CURSOR_VERSION = "v2"
    }
}
