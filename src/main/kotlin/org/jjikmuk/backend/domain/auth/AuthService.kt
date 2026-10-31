package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.user.AuthProvider
import org.jjikmuk.backend.domain.user.DelimitedProfileNormalizer
import org.jjikmuk.backend.domain.user.DietPreferenceCatalog
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.http.HttpStatus
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class AuthService(
    private val userRepository: UserRepository,
    private val passwordEncoder: BCryptPasswordEncoder,
    private val sessions: AuthSessionService,
    private val googleLoginService: GoogleLoginService,
    private val linkGrants: GoogleLinkGrantRepository,
    private val emailService: EmailService
) {
    @Transactional
    fun signup(request: SignupRequest): User {
        val email = AccountInputPolicy.normalizeEmail(request.email)
        val nickname = AccountInputPolicy.normalizeNickname(request.nickname)
        AccountInputPolicy.validatePassword(request.password)
        ensureEmailAvailable(email)
        ensureNicknameAvailable(nickname)

        emailService.consumeVerificationGrant(
            emailValue = email,
            purpose = EmailVerificationPurpose.SIGNUP,
            rawToken = request.verificationToken
        )
        val user = User(
            email = email,
            password = passwordEncoder.encode(request.password)!!,
            nickname = nickname,
            allergies = normalizeAllergies(request.allergies),
            diseases = normalizeDelimited(request.diseases, "기저질환"),
            specialDiet = normalizeSpecialDiet(request.specialDiet),
            dislikedIngredients = normalizeDelimited(request.dislikedIngredients, "기피 식재료"),
            authProvider = AuthProvider.LOCAL,
            profileCompleted = true
        )
        return try {
            userRepository.saveAndFlush(user)
        } catch (error: DataIntegrityViolationException) {
            val duplicateEmail = error.mostSpecificCause.message
                ?.contains("email", ignoreCase = true) == true
            if (duplicateEmail) {
                throw CustomException(
                    HttpStatus.CONFLICT,
                    "이미 가입된 이메일입니다.",
                    ApiErrorCode.EMAIL_ALREADY_REGISTERED,
                    "email"
                )
            }
            throw CustomException(
                HttpStatus.CONFLICT,
                "이미 사용 중인 닉네임입니다.",
                ApiErrorCode.NICKNAME_ALREADY_EXISTS,
                "nickname"
            )
        }
    }

    @Transactional
    fun login(request: LoginRequest): AuthResponse {
        val email = try {
            AccountInputPolicy.normalizeEmail(request.email)
        } catch (_: CustomException) {
            throw loginFailed()
        }
        val userId = userRepository.idForEmail(email) ?: throw loginFailed()
        val user = userRepository.lockById(userId) ?: throw loginFailed()
        if (!user.authProvider.supportsPassword) {
            throw CustomException(
                HttpStatus.CONFLICT,
                "Google로 가입한 계정입니다. Google 로그인을 이용해주세요.",
                ApiErrorCode.AUTH_METHOD_NOT_SUPPORTED,
                "email"
            )
        }
        if (!passwordEncoder.matches(request.password, user.password)) throw loginFailed()
        return issueAuthResponse(user, isNewUser = false, message = "로그인 성공")
    }

    // Deliberately non-transactional: Google verification must finish before account/session writes.
    // GoogleLoginService rejects callers that already hold a transaction; do not add @Transactional here.
    fun googleLogin(request: GoogleLoginRequest): Any = googleLoginService.login(request)

    @Transactional(noRollbackFor = [CustomException::class])
    fun linkGoogle(request: GoogleLinkRequest): AuthResponse {
        val hash = linkHash(request.linkToken)
        val owner = linkGrants.ownerForHash(hash) ?: throw invalidLink()
        val user = userRepository.lockById(owner) ?: throw invalidLink()
        val grant = linkGrants.lockByHash(hash) ?: throw invalidLink()
        if (grant.consumedAt != null || !grant.expiresAt.isAfter(java.time.Instant.now()) ||
            grant.tokenVersion != user.tokenVersion || grant.attempts >= 5) throw invalidLink()
        if (!user.authProvider.supportsPassword || !passwordEncoder.matches(request.currentPassword, user.password)) {
            grant.attempts++
            throw CustomException(HttpStatus.BAD_REQUEST, "기존 계정 비밀번호를 확인해주세요.", "GOOGLE_LINK_PASSWORD_INVALID", "currentPassword")
        }
        if ((user.googleSubject != null && user.googleSubject != grant.googleSubject) ||
            userRepository.findByGoogleSubject(grant.googleSubject)?.id?.let { it != user.id } == true) {
            throw CustomException(HttpStatus.CONFLICT, "이미 다른 계정과 연결된 Google 계정입니다.", "GOOGLE_ACCOUNT_ALREADY_LINKED")
        }
        grant.consumedAt = java.time.Instant.now()
        user.googleSubject = grant.googleSubject
        user.authProvider = user.authProvider.linkGoogle()
        userRepository.saveAndFlush(user)
        return issueAuthResponse(user, false, "기존 계정에 Google 연결 및 로그인 성공")
    }

    @Transactional
    fun cancelGoogleLink(token: String) {
        val hash = linkHash(token)
        val owner = linkGrants.ownerForHash(hash) ?: return
        userRepository.lockById(owner) ?: return
        linkGrants.lockByHash(hash)?.consumedAt = java.time.Instant.now()
    }

    private fun linkHash(token: String): String {
        if (!token.matches(Regex("[A-Za-z0-9_-]{43}"))) throw invalidLink()
        return EmailVerificationSecurity.hashToken(token)
    }
    private fun invalidLink() = CustomException(HttpStatus.GONE, "계정 연결 요청이 만료되었거나 사용되었습니다. Google 로그인을 다시 진행해주세요.", "GOOGLE_LINK_EXPIRED")

    @Transactional
    fun resetPassword(request: PasswordResetRequest) {
        val email = AccountInputPolicy.normalizeEmail(request.email)
        AccountInputPolicy.validatePassword(request.newPassword)
        val user = userRepository.idForEmail(email)?.let(userRepository::lockById)
            ?: throw CustomException(
                HttpStatus.NOT_FOUND,
                "가입되지 않은 이메일입니다.",
                ApiErrorCode.USER_NOT_FOUND,
                "email"
            )
        if (!user.authProvider.supportsPassword) {
            throw CustomException(
                HttpStatus.CONFLICT,
                "Google 전용 계정은 비밀번호를 재설정할 수 없습니다.",
                ApiErrorCode.AUTH_METHOD_NOT_SUPPORTED,
                "email"
            )
        }

        emailService.consumeVerificationGrant(
            emailValue = email,
            purpose = EmailVerificationPurpose.PASSWORD_RESET,
            rawToken = request.verificationToken
        )
        user.password = passwordEncoder.encode(request.newPassword)!!
        user.invalidateSessions()
        sessions.revokeAll(requireNotNull(user.id))
        userRepository.save(user)
    }

    @Transactional(readOnly = true)
    fun nicknameAvailability(value: String, currentUserId: Long? = null): NicknameAvailabilityResponse {
        val nickname = AccountInputPolicy.normalizeNickname(value)
        return NicknameAvailabilityResponse(
            nickname = nickname,
            available = if (currentUserId == null) !userRepository.existsByNicknameIgnoreCase(nickname)
                else !userRepository.existsByNicknameIgnoreCaseAndIdNot(nickname, currentUserId)
        )
    }

    private fun issueAuthResponse(user: User, isNewUser: Boolean, message: String): AuthResponse {
        return sessions.issue(user, isNewUser, message)
    }

    private fun ensureEmailAvailable(email: String) {
        if (userRepository.findByEmail(email) != null) {
            throw CustomException(
                HttpStatus.CONFLICT,
                "이미 가입된 이메일입니다. 가입 요청의 응답을 받지 못했다면 로그인을 시도해주세요.",
                ApiErrorCode.EMAIL_ALREADY_REGISTERED,
                "email"
            )
        }
    }

    private fun ensureNicknameAvailable(nickname: String) {
        if (userRepository.existsByNicknameIgnoreCase(nickname)) {
            throw CustomException(
                HttpStatus.CONFLICT,
                "이미 사용 중인 닉네임입니다.",
                ApiErrorCode.NICKNAME_ALREADY_EXISTS,
                "nickname"
            )
        }
    }

    private fun loginFailed() = CustomException(
        HttpStatus.UNAUTHORIZED,
        "이메일 또는 비밀번호가 일치하지 않습니다.",
        ApiErrorCode.LOGIN_FAILED
    )

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
