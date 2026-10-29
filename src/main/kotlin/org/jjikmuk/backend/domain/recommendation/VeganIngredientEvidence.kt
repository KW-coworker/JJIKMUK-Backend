package org.jjikmuk.backend.domain.recommendation

import java.text.Normalizer

/** Negative evidence only. No match is NOT proof of vegan certification or complete ingredients. */
internal object VeganIngredientEvidence {
    data class Findings(val conflicts: List<String>, val uncertain: List<String>)

    fun inspect(rawMaterials: String?): Findings {
        val conflicts = linkedSetOf<String>()
        val uncertain = linkedSetOf<String>()
        val parts = Normalizer.normalize(rawMaterials.orEmpty(), Normalizer.Form.NFKC).lowercase()
            .split(Regex("[,;|\\n()\\[\\]{}]+"))
        for (part in parts) {
            // Never join different ingredients: '분' and '유' in separate entries are not milk powder.
            val compact = part.filterNot(Char::isWhitespace)
            val text = PLANT_NAMES.fold(compact) { value, name -> value.replace(name, "#") }
            for (term in ANIMAL_TERMS) {
                Regex(Regex.escape(term)).findAll(text).forEach { match ->
                    val before = text.substring(0, match.range.first)
                    val after = text.substring(match.range.last + 1)
                    if (UNCERTAIN_PREFIXES.any(before::endsWith) || UNCERTAIN_SUFFIXES.any(after::startsWith)) {
                        uncertain += term
                    } else {
                        conflicts += term
                    }
                }
            }
            // Short names must not match '둥굴레', '번개' etc.
            for (term in SINGLE_TERMS) {
                if (Regex("^${Regex.escape(term)}[0-9.%]*$").matches(text)) conflicts += term
            }
        }
        return Findings(conflicts.sorted(), uncertain.sorted())
    }

    private val ANIMAL_TERMS = setOf(
        "젓갈", "액젓", "새우", "멸치", "오징어", "고등어", "명태", "황태", "북어", "참치", "다랑어", "연어",
        "어유", "굴소스", "굴추출물", "굴농축액", "굴분말", "홍합", "전복", "바지락", "꽃게", "게살", "게분말",
        "돼지고기", "돈육", "닭고기", "계육", "쇠고기", "소고기", "우육", "동물성유지",
        "계란", "달걀", "난백", "난황", "전란", "우유", "분유", "유청", "유당", "카제인", "유크림", "버터", "치즈",
        "젤라틴", "벌꿀"
    )
    private val SINGLE_TERMS = setOf("굴", "게", "꿀", "돈지", "우지")
    private val PLANT_NAMES = listOf(
        "코코아버터", "카카오버터", "땅콩버터", "아몬드버터", "캐슈넛버터", "코코넛우유"
    )
    // These declarations do not prove animal content OR reliable absence; retain UNKNOWN.
    private val UNCERTAIN_PREFIXES = setOf("식물성", "비건", "무", "합성")
    private val UNCERTAIN_SUFFIXES = setOf("향", "맛", "무첨가", "미함유", "불포함", "프리", "없음")
}
