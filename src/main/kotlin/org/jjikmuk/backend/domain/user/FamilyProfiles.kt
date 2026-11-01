package org.jjikmuk.backend.domain.user

import jakarta.persistence.*
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.http.HttpStatus
import org.springframework.security.core.Authentication
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.*

@Entity @Table(name = "family_profiles")
class FamilyProfile(
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) val id: Long? = null,
    @Column(nullable = false) val ownerId: Long,
    @Column(nullable = false, length = 20) var nickname: String,
    @Column(length = 1000) var allergies: String? = null,
    @Column(length = 1000) var specialDiet: String? = null,
    @Column(length = 1000) var diseases: String? = null,
    @Column(length = 1000) var dislikedIngredients: String? = null,
    @Version var version: Long = 0,
    @Column(name = "relationship", length = 32) var relation: String? = null,
    @Column(length = 32) var emoji: String? = null
) {
    fun response() = FamilyProfileResponse(requireNotNull(id), nickname, allergies, specialDiet, diseases, dislikedIngredients, version, relation, emoji)
    fun asConditions() = User(email = "", password = "", nickname = nickname,
        allergies = allergies, specialDiet = specialDiet, diseases = diseases, dislikedIngredients = dislikedIngredients)
}
data class FamilyProfileResponse(val id: Long, val nickname: String, val allergies: String?,
    val specialDiet: String?, val diseases: String?, val dislikedIngredients: String?, val version: Long,
    val relation: String? = null, val emoji: String? = null)
interface FamilyProfileRepository : JpaRepository<FamilyProfile, Long> {
    fun findAllByOwnerIdOrderById(ownerId: Long): List<FamilyProfile>
    fun findByIdAndOwnerId(id: Long, ownerId: Long): FamilyProfile?
    fun countByOwnerId(ownerId: Long): Long
    fun deleteByOwnerId(ownerId: Long)
}

@Service @Transactional(readOnly = true)
class FamilyProfileService(private val repository: FamilyProfileRepository, private val users: UserRepository) {
    fun list(owner: Long) = repository.findAllByOwnerIdOrderById(owner).map(FamilyProfile::response)
    fun owned(owner: Long, id: Long): FamilyProfile = repository.findByIdAndOwnerId(id, owner)
        ?: throw CustomException(HttpStatus.NOT_FOUND, "가족 프로필을 찾을 수 없습니다.", "FAMILY_NOT_FOUND")

    @Transactional
    fun create(owner: Long, body: Map<String, Any?>): FamilyProfileResponse {
        ProfileInputs.validateKeys(body, setOf("relation", "emoji"))
        users.lockById(owner) ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", "USER_NOT_FOUND")
        if (repository.countByOwnerId(owner) >= 20) throw CustomException(HttpStatus.CONFLICT, "가족 프로필은 최대 20개입니다.", "FAMILY_LIMIT_EXCEEDED")
        val nickname = ProfileInputs.text(body + ("nickname" to body["nickname"]), "nickname", null)!!
        val member = FamilyProfile(ownerId = owner, nickname = nickname)
        apply(member, body)
        return repository.saveAndFlush(member).response()
    }

    @Transactional
    fun patch(owner: Long, id: Long, body: Map<String, Any?>): FamilyProfileResponse {
        ProfileInputs.validateKeys(body, setOf("version", "relation", "emoji"))
        val member = owned(owner, id)
        val version = (body["version"] as? Number)?.toString()?.toLongOrNull()
            ?: throw ProfileInputs.invalid("version", "조회한 정수 version을 전달해주세요.")
        checkVersion(member, version)
        apply(member, body)
        return repository.saveAndFlush(member).response()
    }

    @Transactional
    fun delete(owner: Long, id: Long, version: Long) {
        val member = owned(owner, id)
        checkVersion(member, version)
        repository.delete(member)
        repository.flush()
    }
    private fun checkVersion(member: FamilyProfile, version: Long) {
        if (version != member.version) throw CustomException(HttpStatus.CONFLICT,
            "다른 기기에서 변경되었습니다. 다시 조회해주세요.", "PROFILE_VERSION_CONFLICT")
    }
    private fun apply(member: FamilyProfile, body: Map<String, Any?>) {
        member.nickname = ProfileInputs.text(body, "nickname", member.nickname)!!
        member.allergies = ProfileInputs.text(body, "allergies", member.allergies)
        member.specialDiet = ProfileInputs.text(body, "specialDiet", member.specialDiet)
        member.diseases = ProfileInputs.text(body, "diseases", member.diseases)
        member.dislikedIngredients = ProfileInputs.text(body, "dislikedIngredients", member.dislikedIngredients)
        member.relation = displayText(body, "relation", member.relation)
        member.emoji = displayText(body, "emoji", member.emoji)
    }

    // Display metadata, never used as a dietary condition. Null/blank clears; omission preserves.
    private fun displayText(body: Map<String, Any?>, key: String, previous: String?): String? {
        if (!body.containsKey(key)) return previous
        val raw = body[key] ?: return null
        if (raw !is String) throw ProfileInputs.invalid(key, "문자열 또는 null만 사용할 수 있습니다.")
        if (raw.codePoints().anyMatch { Character.isISOControl(it) } ||
            raw.codePointCount(0, raw.length) > 32) {
            throw ProfileInputs.invalid(key, "제어 문자 없이 32자 이하로 입력해주세요.")
        }
        return raw.trim().takeIf { it.isNotEmpty() }
    }
}

@RestController @RequestMapping("/api/users/me/family-profiles")
class FamilyProfileController(private val service: FamilyProfileService) {
    @GetMapping fun list(auth: Authentication) = mapOf("message" to "가족 프로필 목록 조회 성공", "data" to service.list(auth.owner()))
    @GetMapping("/{id}") fun get(@PathVariable id: Long, auth: Authentication) =
        mapOf("message" to "가족 프로필 조회 성공", "data" to service.owned(auth.owner(), id).response())
    @PostMapping @ResponseStatus(HttpStatus.CREATED)
    fun create(@RequestBody body: Map<String, Any?>, auth: Authentication) =
        mapOf("message" to "가족 프로필 생성 성공", "data" to service.create(auth.owner(), body))
    @PatchMapping("/{id}") fun patch(@PathVariable id: Long, @RequestBody body: Map<String, Any?>, auth: Authentication) =
        mapOf("message" to "가족 프로필 수정 성공", "data" to service.patch(auth.owner(), id, body))
    @DeleteMapping("/{id}") fun delete(@PathVariable id: Long, @RequestParam version: Long, auth: Authentication): Map<String, String> {
        service.delete(auth.owner(), id, version)
        return mapOf("message" to "가족 프로필 삭제 성공")
    }
    private fun Authentication.owner() = principal.toString().toLong()
}
