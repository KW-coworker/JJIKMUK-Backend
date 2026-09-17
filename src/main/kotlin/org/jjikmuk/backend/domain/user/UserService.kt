package org.jjikmuk.backend.domain.user

import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.http.HttpStatus
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.recommendation.RecommendationFeedbackService

@Service
class UserService(
    private val userRepository: UserRepository,
    private val passwordEncoder: BCryptPasswordEncoder,
    private val historyRepository: HistoryRepository,
    private val recommendationFeedbackService: RecommendationFeedbackService
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
        val user = userRepository.findById(id).orElseThrow {
            CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")
        }

        if (!passwordEncoder.matches(request.currentPassword, user.password)) {
            throw CustomException(HttpStatus.BAD_REQUEST, "현재 비밀번호가 일치하지 않습니다.")
        }

        // 🚀 수정된 부분: encode 결과 뒤에 !! 를 붙여 String 타입으로 확정 짓습니다.
        user.password = passwordEncoder.encode(request.newPassword)!!
        userRepository.save(user)
    }

    @Transactional
    fun updateUserProfile(id: Long, request: UserProfileRequest): User? {
        val user = userRepository.findById(id).orElse(null) ?: return null
        user.updateProfile(
            nickname = request.nickname,
            allergies = request.allergies,
            diseases = request.diseases,
            specialDiet = request.specialDiet,
            dislikedIngredients = request.dislikedIngredients
        )
        return userRepository.save(user)
    }

    @Transactional
    fun deleteUser(id: Long) {
        val user = userRepository.findById(id).orElseThrow {
            CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.")
        }
        historyRepository.deleteByUserId(id)
        recommendationFeedbackService.deleteByUserId(id)
        userRepository.delete(user)
    }
}
