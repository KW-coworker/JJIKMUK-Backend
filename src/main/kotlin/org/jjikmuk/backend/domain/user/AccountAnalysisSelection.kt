package org.jjikmuk.backend.domain.user

import jakarta.persistence.*
import jakarta.servlet.http.HttpServletResponse
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.http.HttpStatus
import org.springframework.security.core.Authentication
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.*

/** Account-owned toggle settings, not family data or device import state. */
@Entity @Table(name = "account_analysis_selections")
class AccountAnalysisSelection(
    @Id @Column(name = "owner_id") val ownerId: Long,
    @Column(nullable = false) var includeSelf: Boolean = true,
    // Serialized by the owner row lock, also for the first save where no settings row exists.
    @Column(nullable = false) var version: Long = 0,
    @ElementCollection
    @CollectionTable(name = "account_analysis_selection_families", joinColumns = [JoinColumn(name = "owner_id")])
    @Column(name = "family_profile_id", nullable = false)
    var familyProfileIds: MutableSet<Long> = linkedSetOf()
) {
    fun response() = AccountAnalysisSelectionResponse(includeSelf, familyProfileIds.sorted(), version, true)
}

data class AccountAnalysisSelectionResponse(
    val includeSelf: Boolean,
    val familyProfileIds: List<Long>,
    val version: Long,
    val configured: Boolean
) {
    val mode: String get() = when {
        familyProfileIds.isNotEmpty() -> "selected"
        includeSelf -> "self"
        else -> "none"
    }
}

interface AccountAnalysisSelectionRepository : JpaRepository<AccountAnalysisSelection, Long>

@Service @Transactional(readOnly = true)
class AccountAnalysisSelectionService(
    private val repository: AccountAnalysisSelectionRepository,
    private val users: UserRepository,
    private val families: FamilyProfileRepository
) {
    fun get(owner: Long): AccountAnalysisSelectionResponse {
        if (!users.existsById(owner)) throw missingUser()
        // Reading/signing in never imports device profiles or creates settings.
        return repository.findById(owner).orElse(null)?.response()
            ?: AccountAnalysisSelectionResponse(true, emptyList(), 0, false)
    }

    /** Full selection replacement, never a last-write-wins PATCH from an old device. */
    @Transactional
    fun replace(owner: Long, body: Map<String, Any?>): AccountAnalysisSelectionResponse {
        val unknown = body.keys - setOf("version", "includeSelf", "familyProfileIds")
        if (unknown.isNotEmpty()) throw ProfileInputs.invalid(unknown.first(), "지원하지 않는 선택 필드입니다.")
        val expected = ProfileInputs.expectedVersion(body["version"])
        val self = body["includeSelf"] as? Boolean
            ?: throw ProfileInputs.invalid("includeSelf", "true 또는 false를 전달해주세요.")
        val rawIds = body["familyProfileIds"] as? List<*>
            ?: throw ProfileInputs.invalid("familyProfileIds", "서버 가족 ID의 정수 배열을 전달해주세요. 전원 OFF는 []입니다.")
        if (rawIds.size > 20) throw ProfileInputs.invalid("familyProfileIds", "가족은 최대 20명입니다.")
        val ids = rawIds.map { raw ->
            val id = when (raw) {
                is Byte, is Short, is Int, is Long, is java.math.BigInteger -> raw.toString().toLongOrNull()
                else -> null
            }
            id?.takeIf { it > 0 } ?: throw ProfileInputs.invalid("familyProfileIds", "서버 가족 ID는 양의 정수입니다.")
        }.toSortedSet()
        users.lockById(owner) ?: throw missingUser()
        val selection = repository.findById(owner).orElse(null) ?: AccountAnalysisSelection(owner)
        if (selection.version != expected) throw CustomException(HttpStatus.CONFLICT,
            "다른 기기에서 분석 대상이 변경되었습니다. 다시 조회한 뒤 선택해주세요.",
            "ANALYSIS_SELECTION_VERSION_CONFLICT", "version")
        // Only owned server IDs are valid. Clients must map local IDs using family create/list responses.
        ids.forEach { id ->
            if (families.findByIdAndOwnerId(id, owner) == null) throw CustomException(HttpStatus.NOT_FOUND,
                "가족 프로필을 찾을 수 없습니다.", "FAMILY_NOT_FOUND")
        }
        selection.includeSelf = self
        selection.familyProfileIds.clear()
        selection.familyProfileIds.addAll(ids)
        selection.version = Math.addExact(selection.version, 1)
        return repository.saveAndFlush(selection).response()
    }

    /** Called within family deletion's transaction. Do not turn self ON when the last family is removed. */
    @Transactional
    fun removeFamily(owner: Long, familyId: Long) {
        users.lockById(owner) ?: throw missingUser()
        val selection = repository.findById(owner).orElse(null) ?: return
        if (selection.familyProfileIds.remove(familyId)) {
            selection.version = Math.addExact(selection.version, 1)
            repository.saveAndFlush(selection)
        }
    }

    @Transactional
    fun deleteAccount(owner: Long) {
        users.lockById(owner) ?: throw missingUser()
        repository.findById(owner).orElse(null)?.let { repository.delete(it); repository.flush() }
    }

    private fun missingUser() = CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", "USER_NOT_FOUND")
}

@RestController @RequestMapping("/api/users/me/analysis-selection")
class AccountAnalysisSelectionController(private val service: AccountAnalysisSelectionService) {
    @ModelAttribute fun noCache(response: HttpServletResponse) { response.setHeader("Cache-Control", "no-store") }
    @GetMapping fun get(auth: Authentication) = mapOf("message" to "분석 대상 조회 성공",
        "data" to service.get(auth.principal.toString().toLong()))
    @PutMapping fun replace(auth: Authentication, @RequestBody body: Map<String, Any?>) =
        mapOf("message" to "분석 대상 저장 성공", "data" to service.replace(auth.principal.toString().toLong(), body))
}
