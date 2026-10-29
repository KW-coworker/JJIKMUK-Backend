package org.jjikmuk.backend.domain.user

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.auth.AccountInputPolicy
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.http.HttpStatus
import org.jjikmuk.backend.global.exception.CustomException
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.recommendation.RecommendationFeedbackService
import org.springframework.dao.DataIntegrityViolationException

@Service
class UserService(
    private val userRepository: UserRepository,
    private val passwordEncoder: BCryptPasswordEncoder,
    private val historyRepository: HistoryRepository,
    private val recommendationFeedbackService: RecommendationFeedbackService,
    private val sessions: org.jjikmuk.backend.domain.auth.AuthSessionService,
    private val linkGrants: org.jjikmuk.backend.domain.auth.GoogleLinkGrantRepository,
    private val families: FamilyProfileRepository,
    private val photos: ProfilePhotoRepository
) {
    @Transactional(readOnly = true)
    fun getAllUsers(): List<User> {
        return userRepository.findAll()
    }

    @Transactional(readOnly = true)
    fun getUserProfile(id: Long): User? {
        return userRepository.findById(id).orElse(null)
    }

    @Transactional
    fun updatePassword(id: Long, request: UpdatePasswordRequest) {
        val user = userRepository.lockById(id) ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", ApiErrorCode.USER_NOT_FOUND)

        if (!user.authProvider.supportsPassword) {
            throw CustomException(
                HttpStatus.CONFLICT,
                "Google 전용 계정은 비밀번호를 변경할 수 없습니다.",
                ApiErrorCode.AUTH_METHOD_NOT_SUPPORTED
            )
        }

        if (!passwordEncoder.matches(request.currentPassword, user.password)) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "현재 비밀번호가 일치하지 않습니다.",
                ApiErrorCode.LOGIN_FAILED,
                "currentPassword"
            )
        }

        AccountInputPolicy.validatePassword(request.newPassword)
        user.password = passwordEncoder.encode(request.newPassword)!!
        user.invalidateSessions()
        sessions.revokeAll(id)
        userRepository.save(user)
    }

    @Transactional
    fun updateUserProfile(id: Long, request: UserProfileRequest): User? {
        val user = userRepository.lockById(id) ?: return null
        val nickname = AccountInputPolicy.normalizeNickname(request.nickname)
        if (userRepository.existsByNicknameIgnoreCaseAndIdNot(nickname, id)) {
            throw CustomException(
                HttpStatus.CONFLICT,
                "이미 사용 중인 닉네임입니다.",
                ApiErrorCode.NICKNAME_ALREADY_EXISTS,
                "nickname"
            )
        }
        user.updateProfile(
            nickname = nickname,
            allergies = normalizeAllergies(request.allergies),
            diseases = normalizeDelimited(request.diseases, "기저질환"),
            specialDiet = normalizeSpecialDiet(request.specialDiet),
            dislikedIngredients = normalizeDelimited(request.dislikedIngredients, "기피 식재료")
        )
        return try {
            userRepository.saveAndFlush(user)
        } catch (_: DataIntegrityViolationException) {
            throw CustomException(
                HttpStatus.CONFLICT,
                "이미 사용 중인 닉네임입니다.",
                ApiErrorCode.NICKNAME_ALREADY_EXISTS,
                "nickname"
            )
        }
    }

    @Transactional
    fun patchProfile(id: Long, body: Map<String, Any?>): User {
        ProfileInputs.validateKeys(body)
        val user = userRepository.lockById(id) ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", ApiErrorCode.USER_NOT_FOUND)
        val request = UserProfileRequest(
            nickname = requireNotNull(ProfileInputs.text(body, "nickname", user.nickname)),
            allergies = ProfileInputs.text(body, "allergies", user.allergies),
            diseases = ProfileInputs.text(body, "diseases", user.diseases),
            specialDiet = ProfileInputs.text(body, "specialDiet", user.specialDiet),
            dislikedIngredients = ProfileInputs.text(body, "dislikedIngredients", user.dislikedIngredients))
        return requireNotNull(updateUserProfile(id, request))
    }

    @Transactional
    fun completeProfile(id: Long, request: UserProfileRequest): User {
        val user = updateUserProfile(id, request) ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", ApiErrorCode.USER_NOT_FOUND)
        user.profileCompleted = true
        return userRepository.saveAndFlush(user)
    }

    @Transactional
    fun deleteUser(id: Long) {
        val user = userRepository.lockById(id) ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", ApiErrorCode.USER_NOT_FOUND)
        sessions.deleteAll(id)
        linkGrants.deleteByUserId(id)
        families.deleteByOwnerId(id)
        photos.deleteById(id)
        historyRepository.deleteByUserId(id)
        recommendationFeedbackService.deleteByUserId(id)
        userRepository.delete(user)
    }

    private fun normalizeAllergies(value: String?): String? = try {
        AllergyCatalog.normalizeForStorage(value)
    } catch (error: IllegalArgumentException) {
        throw CustomException(
            HttpStatus.BAD_REQUEST,
            error.message ?: "알레르기 ID가 올바르지 않습니다.",
            ApiErrorCode.VALIDATION_FAILED,
            "allergies"
        )
    }

    private fun normalizeSpecialDiet(value: String?): String? = try {
        DietPreferenceCatalog.normalizeForStorage(value)
    } catch (error: IllegalArgumentException) {
        throw CustomException(
            HttpStatus.BAD_REQUEST,
            error.message ?: "식이조건 ID가 올바르지 않습니다.",
            ApiErrorCode.VALIDATION_FAILED,
            "specialDiet"
        )
    }

    private fun normalizeDelimited(value: String?, fieldName: String): String? = try {
        DelimitedProfileNormalizer.normalizeForStorage(value, fieldName)
    } catch (error: IllegalArgumentException) {
        throw CustomException(
            HttpStatus.BAD_REQUEST,
            error.message ?: "${fieldName} 값이 올바르지 않습니다.",
            ApiErrorCode.VALIDATION_FAILED
        )
    }
}
