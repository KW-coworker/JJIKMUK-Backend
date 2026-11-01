package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.chat.dto.*
import org.jjikmuk.backend.domain.user.*
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service

data class ChatSelectedProfile(val dto: ProfileDto, val analysis: EffectiveAnalysis)
data class ChatResolvedProfiles(val effective: EffectiveAnalysis,
    val selected: List<ChatSelectedProfile>, val source: String)

@Service
class ChatProfileResolver(private val selections: AnalysisSelectionService) {
    fun resolve(request: ChatRequestDto, ownerId: Long, mode: String?, includeSelf: Boolean?,
        familyIds: List<Long>?): ChatResolvedProfiles {
        if (request.profile == null && request.profiles == null) {
            val effective = selections.resolve(ownerId, mode, includeSelf, familyIds)
            val selected = effective.subjects.map { subject ->
                val own = subject.kind == "self"
                val selection = AnalysisSelectionResponse(if (own) "self" else "selected", true,
                    own, if (own) emptyList() else listOf(subject.id))
                ChatSelectedProfile(dto(subject.conditions, "${subject.kind}:${subject.id}", "SERVER",
                    subject.id, subject.kind, if (own) ownerId else null),
                    EffectiveAnalysis(subject.conditions, selection))
            }
            return ChatResolvedProfiles(effective, selected, if (effective.applied) "SERVER" else "NONE")
        }
        if (mode != null || includeSelf != null || familyIds != null) {
            throw CustomException(HttpStatus.BAD_REQUEST,
                "서버 프로필 Query 선택과 Body profile/profiles는 함께 사용할 수 없습니다.", "ANALYSIS_SELECTION_INVALID")
        }
        val supplied = listOfNotNull(request.profile) + request.profiles.orEmpty()
        if (supplied.size > 21) throw invalid("profiles", "프로필은 본인 포함 최대 21개입니다.")
        // Validate inactive entries too; never silently drop malformed health conditions.
        val validated = supplied.mapIndexed { index, entry ->
            val field = "profiles[$index]"
            val input = entry ?: throw invalid(field, "프로필 항목은 null일 수 없습니다.")
            if (input.isActive == null) throw invalid("$field.isActive", "활성 여부는 true 또는 false입니다.")
            if (input.id != null && input.id < 0) throw invalid("$field.id", "로컬 ID는 0 이상의 정수 또는 null입니다.")
            val name = input.nickname.trim()
            if (name.isBlank() || input.nickname.length > 40 || name.any(Char::isISOControl)) {
                throw invalid("$field.nickname", "이름은 제어문자 없이 1~40자로 입력해주세요.")
            }
            fun value(key: String, raw: String?): String? = try {
                ProfileInputs.text(mapOf(key to raw), key, null)
            } catch (error: CustomException) {
                throw invalid("$field.$key", error.message)
            }
            input to User(email = "", password = "", nickname = name,
                allergies = value("allergies", input.allergies), diseases = value("diseases", input.diseases),
                specialDiet = value("specialDiet", input.specialDiet),
                dislikedIngredients = value("dislikedIngredients", input.dislikedIngredients))
        }
        // Do not identify people by nickname/id: two locally stored people may share either.
        val selected = validated.filter { it.first.isActive == true }.mapIndexed { index, (_, conditions) ->
            val selection = AnalysisSelectionResponse("provided", true, false, emptyList())
            ChatSelectedProfile(dto(conditions, "request:$index", "CLIENT_REQUEST", (index + 1).toLong(), "provided", null),
                EffectiveAnalysis(conditions, selection))
        }
        val selection = AnalysisSelectionResponse(if (selected.isEmpty()) "none" else "provided",
            selected.isNotEmpty(), false, emptyList())
        return ChatResolvedProfiles(EffectiveAnalysis(combineAnalysisConditions(selected.map { it.analysis.profile }), selection),
            selected, "CLIENT_REQUEST")
    }

    private fun dto(user: User, key: String, source: String, profileId: Long, kind: String, accountId: Long?): ProfileDto {
        val parsed = AllergyCatalog.parse(user.allergies)
        val allergyNames = (parsed.ids.map { it.displayName } + parsed.unknownTerms)
            .takeIf { it.isNotEmpty() }?.joinToString(", ")
        return ProfileDto(accountId, user.nickname, allergyNames, user.diseases, user.specialDiet,
            user.dislikedIngredients, key, source, profileId, kind)
    }
    private fun invalid(field: String, message: String) =
        CustomException(HttpStatus.BAD_REQUEST, message, "VALIDATION_FAILED", field)
}
