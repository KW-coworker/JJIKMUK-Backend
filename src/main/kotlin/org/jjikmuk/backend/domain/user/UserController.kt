package org.jjikmuk.backend.domain.user

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.*
import org.springframework.security.core.Authentication
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus

data class UpdatePasswordRequest(
    val currentPassword: String,
    val newPassword: String
)
data class UserProfileRequest(
    val nickname: String,
    val allergies: String?,
    val diseases: String?,
    val specialDiet: String?,
    val dislikedIngredients: String?
)

@RestController
@RequestMapping("/api/users")
class UserController(
    private val userService: UserService // 💡 Service 주입
) {
    @GetMapping
    fun getAllUsers(): ResponseEntity<*> {
        val users = userService.getAllUsers()
        return ResponseEntity.ok(mapOf("message" to "전체 유저 목록 조회 성공", "data" to users))
    }

    @GetMapping("/{userId}")
    fun getUserInfo(@PathVariable userId: Long, authentication: Authentication): ResponseEntity<*> {
        val currentUserId = authentication.principal.toString().toLong()
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }
        if (currentUserId != userId && !isAdmin) {
            throw CustomException(HttpStatus.FORBIDDEN, "권한이 없습니다.")
        }

        val user = userService.getUserProfile(userId)
            ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")

        return ResponseEntity.ok(mapOf("message" to "조회 성공", "data" to user))
    }

    @PutMapping("/{id}")
    fun updateUserProfile(
        @PathVariable id: Long,
        @RequestBody request: UserProfileRequest,
        authentication: Authentication
    ): ResponseEntity<*> {
        val currentUserId = authentication.principal.toString().toLong()
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }

        // 남의 프로필 수정 시도 차단!
        if (currentUserId != id && !isAdmin) {
            throw CustomException(HttpStatus.FORBIDDEN, "다른 사용자의 프로필을 수정할 수 없습니다.")
        }

        val updatedUser = userService.updateUserProfile(id, request)
            ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")

        return ResponseEntity.ok(mapOf("message" to "프로필 수정 성공", "data" to updatedUser))
    }
    @PutMapping("/{id}/password")
    fun updatePassword(
        @PathVariable id: Long,
        @RequestBody request: UpdatePasswordRequest,
        authentication: Authentication
    ): ResponseEntity<*> {
        val currentUserId = authentication.principal.toString().toLong()
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }

        // 본인만 비밀번호를 바꿀 수 있도록 방어 (관리자라도 남의 비밀번호를 직접 바꾸는 것은 보통 막아둡니다)
        if (currentUserId != id) {
            throw CustomException(HttpStatus.FORBIDDEN, "본인의 비밀번호만 변경할 수 있습니다.")
        }

        userService.updatePassword(id, request)
        return ResponseEntity.ok(mapOf("message" to "비밀번호가 성공적으로 변경되었습니다.", "data" to null))
    }
    // 💡 3. 회원 탈퇴 로직 추가
    @DeleteMapping("/{id}")
    fun deleteUser(@PathVariable id: Long, authentication: Authentication): ResponseEntity<*> {
        val currentUserId = authentication.principal.toString().toLong()
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }

        // 남의 계정 삭제 시도 차단!
        if (currentUserId != id && !isAdmin) {
            throw CustomException(HttpStatus.FORBIDDEN, "다른 사용자의 계정을 탈퇴시킬 수 없습니다.")
        }

        userService.deleteUser(id)
        return ResponseEntity.ok(mapOf("message" to "회원 탈퇴 성공", "data" to null))
    }
}
