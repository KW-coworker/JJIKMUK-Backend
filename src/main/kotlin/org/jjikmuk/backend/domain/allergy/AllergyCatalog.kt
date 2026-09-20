package org.jjikmuk.backend.domain.allergy

import java.text.Normalizer

/** Stable IDs shared by the API, Android client, and recommendation policy. */
enum class FoodAllergy(
    val id: String,
    val displayName: String,
    val profileAliases: Set<String>,
    val evidenceKeywords: Set<String>
) {
    EGG("egg", "계란", setOf("계란", "달걀", "난류", "알류"), setOf("계란", "달걀", "난류", "난백", "난황", "전란", "알부민", "egg")),
    MILK("milk", "우유", setOf("우유", "유제품", "유단백"), setOf("우유", "유제품", "유청", "유단백", "카제인", "분유", "버터", "치즈", "밀크", "milk")),
    SOY("soy", "대두", setOf("대두", "콩", "소이"), setOf("대두", "콩", "콩가루", "콩단백", "콩기름", "소이", "두유", "두부", "soy")),
    WHEAT("wheat", "밀", setOf("밀", "밀가루", "소맥"), setOf("밀", "밀가루", "밀함유", "밀단백", "밀분말", "소맥", "밀전분", "밀글루텐", "글루텐", "wheat")),
    PORK("pork", "돼지고기", setOf("돼지고기", "돈육"), setOf("돼지고기", "돈육", "돈지", "라드", "pork")),
    CHICKEN("chicken", "닭고기", setOf("닭고기", "계육"), setOf("닭고기", "계육", "치킨", "chicken")),
    SHRIMP("shrimp", "새우", setOf("새우", "쉬림프"), setOf("새우", "쉬림프", "크릴", "shrimp")),
    CRAB("crab", "게", setOf("게", "크랩"), setOf("게", "꽃게", "대게", "홍게", "게살", "게분말", "게장", "게맛살", "크랩", "crab")),
    SQUID("squid", "오징어", setOf("오징어"), setOf("오징어", "squid")),
    MACKEREL("mackerel", "고등어", setOf("고등어"), setOf("고등어", "mackerel")),
    SHELLFISH("shellfish", "조개류", setOf("조개류", "조개"), setOf("조개류", "조개", "조개육수", "조개살", "조개추출물", "굴", "굴소스", "홍합", "전복", "바지락", "가리비", "꼬막", "shellfish", "oyster", "mussel", "abalone")),
    OYSTER("oyster", "굴", setOf("굴"), setOf("굴", "굴소스", "굴추출물", "굴분말", "oyster")),
    MUSSEL("mussel", "홍합", setOf("홍합"), setOf("홍합", "mussel")),
    ABALONE("abalone", "전복", setOf("전복"), setOf("전복", "abalone")),
    PEACH("peach", "복숭아", setOf("복숭아", "피치"), setOf("복숭아", "피치", "peach")),
    TOMATO("tomato", "토마토", setOf("토마토"), setOf("토마토", "tomato")),
    PEANUT("peanut", "땅콩", setOf("땅콩", "피넛"), setOf("땅콩", "피넛", "peanut")),
    WALNUT("walnut", "호두", setOf("호두"), setOf("호두", "walnut")),
    BUCKWHEAT("buckwheat", "메밀", setOf("메밀"), setOf("메밀", "buckwheat")),
    PINE_NUT("pine_nut", "잣", setOf("잣", "잣류"), setOf("잣", "잣가루", "잣소스", "pine nut", "pinenut")),
    SULFITES("sulfites", "아황산류", setOf("아황산류", "아황산", "설파이트"), setOf("아황산류", "아황산", "메타중아황산", "이산화황", "설파이트", "sulfite")),
    SESAME("sesame", "참깨", setOf("참깨", "세서미"), setOf("참깨", "참기름", "깨소금", "볶음깨", "통깨", "깨분말", "세서미", "sesame")),
    ALMOND("almond", "아몬드", setOf("아몬드"), setOf("아몬드", "almond")),
    MUSTARD("mustard", "머스타드", setOf("머스타드", "머스터드", "겨자"), setOf("머스타드", "머스터드", "겨자", "mustard")),
    CELERY("celery", "셀러리", setOf("셀러리", "샐러리"), setOf("셀러리", "샐러리", "celery")),
    BEEF("beef", "소고기", setOf("소고기", "쇠고기", "우육"), setOf("소고기", "쇠고기", "우육", "비프", "beef"));

    val requiresVerifiedSource: Boolean
        get() = this in setOf(SESAME, ALMOND, MUSTARD, CELERY)
}

data class AllergyProfile(
    val ids: List<FoodAllergy>,
    val unknownTerms: List<String>
)

object AllergyCatalog {
    private val byAlias: Map<String, FoodAllergy> = FoodAllergy.entries
        .flatMap { allergy -> (allergy.profileAliases + allergy.id + allergy.name).map { normalized(it) to allergy } }
        .toMap()
    private val broadLegacyAliases: Map<String, List<FoodAllergy>> = mapOf(
        "견과류" to listOf(FoodAllergy.WALNUT, FoodAllergy.PINE_NUT, FoodAllergy.ALMOND),
        "갑각류" to listOf(FoodAllergy.SHRIMP, FoodAllergy.CRAB)
    )

    fun resolve(value: String): FoodAllergy? = byAlias[normalized(value)]

    fun parse(value: String?): AllergyProfile {
        val ids = linkedSetOf<FoodAllergy>()
        val unknown = linkedSetOf<String>()
        value.orEmpty().split(Regex("[,;/|\\n]+"))
            .map(String::trim)
            .filter(String::isNotBlank)
            .forEach { term ->
                val key = normalized(term)
                val resolved = byAlias[key]
                when {
                    resolved != null -> ids += resolved
                    broadLegacyAliases.containsKey(key) -> ids += broadLegacyAliases.getValue(key)
                    else -> unknown += term
                }
            }
        return AllergyProfile(ids.toList(), unknown.toList())
    }

    /** Normalizes new writes; unrecognized allergies must never be silently discarded. */
    fun normalizeForStorage(value: String?): String? {
        val parsed = parse(value)
        require(parsed.unknownTerms.isEmpty()) {
            "지원하지 않는 알레르기 ID: ${parsed.unknownTerms.joinToString()}"
        }
        return parsed.ids.map(FoodAllergy::id).takeIf(List<String>::isNotEmpty)?.joinToString(",")
    }

    private fun normalized(value: String): String = Normalizer
        .normalize(value.trim(), Normalizer.Form.NFKC)
        .lowercase()
        .filter { it.isLetterOrDigit() || it == '_' }
}
