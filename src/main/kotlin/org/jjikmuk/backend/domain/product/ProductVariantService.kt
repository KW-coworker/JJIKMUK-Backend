package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.allergy.AllergySafetyService
import org.jjikmuk.backend.domain.recommendation.SafetyDecision
import org.jjikmuk.backend.domain.recommendation.SafetyStatus
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
@Transactional(readOnly = true)
class ProductVariantService(
    private val productRepository: ProductRepository,
    private val searchRepository: DistinctProductSearchRepository,
    private val userRepository: UserRepository,
    private val safetyService: AllergySafetyService,
    private val productService: ProductService
) {
    fun getVariants(barcode: String, userId: Long?): ProductVariantResponse {
        val reference = productRepository.findFirstByBarcode(barcode)
            ?: throw CustomException(HttpStatus.NOT_FOUND, "해당 바코드(${barcode})의 제품을 찾을 수 없습니다.")
        val members = searchRepository.findDisplayGroupMembers(reference, MAX_GROUP_ROWS + 1)
        if (members.size > MAX_GROUP_ROWS) {
            // Never silently truncate: a discarded row may carry the only allergy warning.
            throw CustomException(
                HttpStatus.UNPROCESSABLE_ENTITY,
                "같은 상품으로 묶인 자료가 너무 많아 용량 옵션을 확인할 수 없습니다. 상품 데이터 점검이 필요합니다.",
                ApiErrorCode.PRODUCT_VARIANT_GROUP_TOO_LARGE
            )
        }
        val user = userId?.let {
            userRepository.findById(it).orElseThrow {
                CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")
            }
        }
        val profile = AllergyCatalog.parse(user?.allergies)
        val allergies = profile.ids.map { it.id } + profile.unknownTerms
        val options = members.ifEmpty { listOf(reference) }
            .groupBy { ProductCapacity.parse(it.totalWeight) }
            .entries.sortedWith(
                compareBy<Map.Entry<ProductCapacity, List<Product>>> {
                    when (it.key.unit) { "g" -> 0; "ml" -> 1; else -> 2 }
                }.thenBy { it.key.amount }
            ).map { (capacity, rows) ->
                val decisions = rows.map { safetyService.evaluate(it, allergies, user != null) }
                val safety = aggregateSafety(decisions)
                val representative = rows.sortedWith(
                    compareByDescending<Product> { completeness(it) }.thenBy { it.barcode }
                ).first()
                ProductCapacityOption(
                    key = capacity.key,
                    label = capacity.label,
                    amount = capacity.amount,
                    unit = capacity.unit,
                    barcode = representative.barcode,
                    sourceRowCount = rows.size,
                    hasSafetyDifferences = decisions.map { it.status to it.conflictingAllergens.toSet() }
                        .distinct().size > 1,
                    data = productService.analyzeProductAllergy(representative, user, safety)
                )
            }
        return ProductVariantResponse(
            referenceBarcode = reference.barcode,
            selectedOptionKey = ProductCapacity.parse(reference.totalWeight).key,
            optionCount = options.size,
            hasSelectableOptions = options.size > 1,
            options = options
        )
    }

    private fun aggregateSafety(decisions: List<SafetyDecision>): SafetyDecision {
        if (decisions.size == 1) return decisions.single()
        val status = when {
            decisions.any { it.status == SafetyStatus.DANGER } -> SafetyStatus.DANGER
            decisions.any { it.status == SafetyStatus.UNKNOWN } -> SafetyStatus.UNKNOWN
            else -> SafetyStatus.PASS
        }
        val relevant = decisions.filter { it.status == status }
        val conflicts = decisions.flatMap { it.conflictingAllergens }.distinct().sorted()
        return SafetyDecision(
            status = status,
            conflictingAllergens = conflicts,
            evidenceSources = decisions.flatMap { it.evidenceSources }.distinct().sorted(),
            evidenceLevel = relevant.maxBy { it.evidenceLevel.ordinal }.evidenceLevel,
            confidence = if (relevant.any { it.confidence == null }) null else relevant.minOf { it.confidence!! },
            message = when (status) {
                SafetyStatus.DANGER -> "같은 용량의 자료 중 등록된 알레르기와 충돌하는 표기가 확인되었습니다: " +
                    conflicts.mapNotNull { AllergyCatalog.resolve(it)?.displayName }.joinToString() +
                    ". 실제 포장 라벨을 확인해 주세요."
                SafetyStatus.UNKNOWN -> "같은 용량의 자료 중 개인 알레르기 판정이 불가능한 자료가 있습니다. 실제 포장 라벨을 확인해 주세요."
                SafetyStatus.PASS -> "같은 용량의 자료에서 등록된 알레르기 조건과의 충돌은 발견되지 않았습니다. 실제 포장 라벨을 확인해 주세요."
            }
        )
    }

    /** Pick one intact source row, never mix nutrients from different rows. No safety ranking here. */
    private fun completeness(product: Product): Int = listOf(
        product.energyKcal, product.carbsG, product.proteinG, product.fatG,
        product.sugarG, product.sodiumMg, product.cholesterolMg
    ).count { it != null } + listOf(
        product.rawMaterials, product.allergyWarning, product.imageUrl, product.reportNo
    ).count { !it.isNullOrBlank() }

    private companion object {
        const val MAX_GROUP_ROWS = 1000
    }
}
