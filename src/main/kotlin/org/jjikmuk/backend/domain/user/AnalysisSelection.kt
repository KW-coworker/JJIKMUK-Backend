package org.jjikmuk.backend.domain.user

import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel
import org.jjikmuk.backend.domain.recommendation.*
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

data class AnalysisSelectionResponse(val mode: String, val analysisApplied: Boolean,
    val includeSelf: Boolean, val familyProfileIds: List<Long>)

data class EffectiveAnalysis(val profile: User, val selection: AnalysisSelectionResponse) {
    val applied get() = selection.analysisApplied
    val personalHistoryAllowed get() = selection.mode == "self"
}

@Service @Transactional(readOnly = true)
class AnalysisSelectionService(private val users: UserRepository, private val families: FamilyProfileService) {
    fun resolve(ownerId: Long?, mode: String?, includeSelf: Boolean?, familyIds: List<Long>?): EffectiveAnalysis {
        val selectedMode = mode?.lowercase() ?: if (ownerId == null) "none" else "self"
        if (selectedMode !in setOf("self", "selected", "none")) throw invalid("analysisMode는 self, selected, none 중 하나입니다.")
        val ids = familyIds.orEmpty().distinct().sorted()
        if (ids.size > 20 || ids.any { it <= 0 }) throw invalid("가족 ID는 양의 정수이며 최대 20개입니다.")
        if (selectedMode != "selected" && (ids.isNotEmpty() || includeSelf != null)) throw invalid("includeSelf와 familyProfileIds는 selected 모드에서만 사용합니다.")
        if (selectedMode == "none") return EffectiveAnalysis(emptyProfile(), AnalysisSelectionResponse("none", false, false, emptyList()))
        if (ownerId == null) throw CustomException(HttpStatus.UNAUTHORIZED, "분석 대상 선택에는 로그인이 필요합니다.", "AUTHENTICATION_REQUIRED")
        val owner = users.findById(ownerId).orElseThrow { CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", "USER_NOT_FOUND") }
        if (selectedMode == "self") return EffectiveAnalysis(owner, AnalysisSelectionResponse("self", true, true, emptyList()))
        val self = includeSelf ?: false
        if (!self && ids.isEmpty()) throw invalid("분석 대상을 선택하거나 analysisMode=none을 사용해주세요.")
        val members = ids.map { families.owned(ownerId, it).asConditions() }
        val profiles = if (self) listOf(owner) + members else members
        fun combine(value: (User) -> String?) = profiles.flatMap { DelimitedProfileNormalizer.terms(value(it)) }
            .distinct().joinToString(",").ifEmpty { null }
        // Union of restrictions; ALL dietary constraints must pass. Never overwrite the account.
        val effective = emptyProfile().apply {
            allergies = combine { it.allergies }; specialDiet = combine { it.specialDiet }
            diseases = combine { it.diseases }; dislikedIngredients = combine { it.dislikedIngredients }
        }
        return EffectiveAnalysis(effective, AnalysisSelectionResponse("selected", true, self, ids))
    }
    private fun emptyProfile() = User(email = "", password = "", nickname = "분석 대상")
    private fun invalid(message: String) = CustomException(HttpStatus.BAD_REQUEST, message, "ANALYSIS_SELECTION_INVALID")
}

fun notEvaluatedSafety() = SafetyDecision(SafetyStatus.NOT_EVALUATED, emptyList(), emptyList(),
    AllergyEvidenceLevel.UNKNOWN, null, "분석 대상을 선택하지 않아 개인 조건을 검사하지 않았습니다.")
fun DietConstraintDecision.withoutAnalysis() = copy(status = DietConstraintStatus.NOT_EVALUATED,
    requiredFilters = emptyList(), satisfiedFilters = emptyList(), failedFilters = emptyList(),
    uncertainFilters = emptyList(), attributes = emptyList(), confidence = null,
    message = "분석 대상 없음: 식단 적합성을 검사하지 않았습니다.")
