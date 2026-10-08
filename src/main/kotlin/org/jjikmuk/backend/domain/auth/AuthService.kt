package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.user.AuthProvider
import org.jjikmuk.backend.domain.user.DelimitedProfileNormalizer
import org.jjikmuk.backend.domain.user.DietPreferenceCatalog
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.config.JwtProvider
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.beans.factory.annotation.Value
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.http.HttpStatus
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.client.RestClient
import java.util.UUID

@Service
class AuthService(
    private val userRepository: UserRepository,
    private val passwordEncoder: BCryptPasswordEncoder,
    private val jwtProvider: JwtProvider,
    private val restClient: RestClient,
    private val emailService: EmailService,
    @Value("\${google.client-id:}") private val googleClientId: String
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

    @Transactional(readOnly = true)
    fun login(request: LoginRequest): AuthResponse {
        val email = try {
            AccountInputPolicy.normalizeEmail(request.email)
        } catch (_: CustomException) {
            throw loginFailed()
        }
        val user = userRepository.findByEmail(email) ?: throw loginFailed()
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

    @Transactional
    fun googleLogin(request: GoogleLoginRequest): AuthResponse {
        if (googleClientId.isBlank()) {
            throw CustomException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Google 로그인이 아직 구성되지 않았습니다.",
                ApiErrorCode.GOOGLE_LOGIN_UNAVAILABLE
            )
        }
        val googleResponse = try {
            restClient.get()
                .uri { builder ->
                    builder
                        .scheme("https")
                        .host("oauth2.googleapis.com")
                        .path("/tokeninfo")
                        .queryParam("id_token", request.idToken)
                        .build()
                }
                .retrieve()
                .body(Map::class.java)
        } catch (_: Exception) {
            throw invalidGoogleToken()
        }

        val audience = googleResponse?.get("aud") as? String
        val verified = googleResponse?.get("email_verified")?.toString()?.toBooleanStrictOrNull() == true
        if (audience != googleClientId || !verified) throw invalidGoogleToken()
        val email = (googleResponse["email"] as? String)
            ?.let(AccountInputPolicy::normalizeEmail)
            ?: throw invalidGoogleToken()

        var isNewUser = false
        var user = userRepository.findByEmail(email)
        if (user == null) {
            isNewUser = true
            user = User(
                email = email,
                password = passwordEncoder.encode(UUID.randomUUID().toString())!!,
                nickname = generateUniqueGoogleNickname(),
                allergies = null,
                diseases = null,
                specialDiet = null,
                dislikedIngredients = null,
                authProvider = AuthProvider.GOOGLE,
                profileCompleted = false
            )
        } else {
            user.authProvider = user.authProvider.linkGoogle()
        }
        user = userRepository.saveAndFlush(user)
        return issueAuthResponse(user, isNewUser, "구글 로그인 성공")
    }

    @Transactional
    fun resetPassword(request: PasswordResetRequest) {
        val email = AccountInputPolicy.normalizeEmail(request.email)
        AccountInputPolicy.validatePassword(request.newPassword)
        val user = userRepository.findByEmail(email)
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
        userRepository.save(user)
    }

    @Transactional(readOnly = true)
    fun nicknameAvailability(value: String): NicknameAvailabilityResponse {
        val nickname = AccountInputPolicy.normalizeNickname(value)
        return NicknameAvailabilityResponse(
            nickname = nickname,
            available = !userRepository.existsByNicknameIgnoreCase(nickname)
        )
    }

    private fun issueAuthResponse(user: User, isNewUser: Boolean, message: String): AuthResponse {
        val issued = jwtProvider.createToken(
            userId = requireNotNull(user.id),
            email = user.email,
            role = user.role.name,
            tokenVersion = user.tokenVersion
        )
        return AuthResponse(
            message = message,
            token = issued.token,
            userId = requireNotNull(user.id),
            email = user.email,
            expiresAt = issued.expiresAt,
            expiresInSeconds = issued.expiresInSeconds,
            isNewUser = isNewUser,
            profileCompleted = user.profileCompleted
        )
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

    private fun generateUniqueGoogleNickname(): String {
        repeat(10) {
            val candidate = "user_${UUID.randomUUID().toString().replace("-", "").take(8)}"
            if (!userRepository.existsByNicknameIgnoreCase(candidate)) return candidate
        }
        throw CustomException(
            HttpStatus.SERVICE_UNAVAILABLE,
            "닉네임 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
            ApiErrorCode.INTERNAL_SERVER_ERROR
        )
    }

    private fun loginFailed() = CustomException(
        HttpStatus.UNAUTHORIZED,
        "이메일 또는 비밀번호가 일치하지 않습니다.",
        ApiErrorCode.LOGIN_FAILED
    )

    private fun invalidGoogleToken() = CustomException(
        HttpStatus.UNAUTHORIZED,
        "유효하지 않은 Google ID 토큰입니다.",
        ApiErrorCode.GOOGLE_TOKEN_INVALID
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
