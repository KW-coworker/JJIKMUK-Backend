package org.jjikmuk.backend.domain.product

import java.text.Normalizer

enum class ProductUse { FROZEN_DESSERT, FISH_CAKE, DUMPLING, MEAT_DISH, SAUCE, PICKLED_SIDE, MEAL_SHAKE, DRINK, SNACK, PREPARATION_MIX, UNKNOWN }
enum class CategoryCompatibility { MATCH, MISMATCH, UNKNOWN }
data class ProductCategoryAssessment(
    val policyVersion: String,
    val categoryIds: List<String>,
    val usage: ProductUse,
    val evidence: String,
    val needsReview: Boolean,
    val unknownStoredValues: List<String>
)
data class CategoryCompatibilityDecision(
    val status: CategoryCompatibility,
    val referenceUsage: ProductUse,
    val candidateUsage: ProductUse,
    val reason: String,
    val policyVersion: String = ProductCategoryPolicy.VERSION
)

/** Browse categories are multi-label; substitution uses consumer purpose, not ingredient overlap.
 * This is a deliberately small, versioned ruleset, not official food classification or safety evidence.
 */
object ProductCategoryPolicy {
    const val VERSION = "consumer-purpose-v1"
    private fun compact(value: String?) = Normalizer.normalize(value.orEmpty(), Normalizer.Form.NFKC)
        .lowercase().filter(Char::isLetterOrDigit)

    fun assess(product: Product): ProductCategoryAssessment {
        val name = compact(product.cleanProductName ?: product.productName)
        val type = compact(product.foodType)
        val unknown = ProductClassificationCatalog.splitStored(product.foodCategories).filter { ProductFoodCategory.resolve(it) == null }
        val fromType = when (type) {
            "어묵", "어묵류" -> ProductUse.FISH_CAKE
            "빙과", "아이스크림", "아이스밀크", "샤베트", "저지방아이스크림" -> ProductUse.FROZEN_DESSERT
            "만두", "만두류" -> ProductUse.DUMPLING
            "양념육", "분쇄가공육제품" -> ProductUse.MEAT_DISH
            "소스", "소스류", "혼합장", "고추장", "간장", "양조간장", "혼합간장" -> ProductUse.SAUCE
            "절임식품", "김치" -> ProductUse.PICKLED_SIDE
            "체중조절용조제식품" -> ProductUse.MEAL_SHAKE
            "두유", "두유액", "가공두유", "우유", "가공유", "탄산음료", "혼합음료", "과채음료", "과채주스" -> ProductUse.DRINK
            "과자", "비스킷" -> ProductUse.SNACK
            else -> ProductUse.UNKNOWN
        }
        val fromName = when {
            listOf("파우더", "아이스크림믹스", "베이킹믹스", "팬케이크믹스").any(name::contains) -> ProductUse.PREPARATION_MIX
            "물만두" in name || name.endsWith("만두") -> ProductUse.DUMPLING
            "장아찌" in name || "단무지" in name -> ProductUse.PICKLED_SIDE
            name.endsWith("소스") || name.endsWith("초고추장") -> ProductUse.SAUCE
            "쉐이크" in name -> ProductUse.MEAL_SHAKE
            "아이스크림" in name && "맛" !in name && "향" !in name -> ProductUse.FROZEN_DESSERT
            else -> ProductUse.UNKNOWN
        }
        // Explicit mix/powder form matters even when a broad category says dessert.
        val conflict = fromType != ProductUse.UNKNOWN && fromName != ProductUse.UNKNOWN && fromType != fromName && fromName != ProductUse.PREPARATION_MIX
        val usage = when {
            conflict -> ProductUse.UNKNOWN
            fromName == ProductUse.PREPARATION_MIX -> fromName
            fromType != ProductUse.UNKNOWN -> fromType
            else -> fromName
        }
        return ProductCategoryAssessment(VERSION, ProductClassificationCatalog.foodCategoryIds(product.foodCategories), usage,
            when { conflict -> "SOURCE_NAME_TYPE_CONFLICT"; fromName == ProductUse.PREPARATION_MIX -> "NAME_PREPARATION_FORM"
                fromType != ProductUse.UNKNOWN -> "FOOD_TYPE_RULE"; fromName != ProductUse.UNKNOWN -> "PRODUCT_NAME_RULE"; else -> "INSUFFICIENT_EVIDENCE" },
            usage == ProductUse.UNKNOWN || unknown.isNotEmpty(), unknown)
    }

    fun compare(reference: Product, candidate: Product): CategoryCompatibilityDecision {
        val from = assess(reference).usage
        val to = assess(candidate).usage
        val status = when {
            from == ProductUse.UNKNOWN || to == ProductUse.UNKNOWN -> CategoryCompatibility.UNKNOWN
            from == to -> CategoryCompatibility.MATCH
            else -> CategoryCompatibility.MISMATCH
        }
        return CategoryCompatibilityDecision(status, from, to, when (status) {
            CategoryCompatibility.MATCH -> "같은 소비 용도 규칙에 해당합니다. 상품 동일성이나 안전성을 뜻하지 않습니다."
            CategoryCompatibility.MISMATCH -> "완제품/원료 형태 또는 소비 용도가 다릅니다."
            CategoryCompatibility.UNKNOWN -> "소비 용도를 확정할 근거가 부족합니다. 카테고리 일치만으로 대체 가능성을 확정하지 않습니다."
        })
    }
}
