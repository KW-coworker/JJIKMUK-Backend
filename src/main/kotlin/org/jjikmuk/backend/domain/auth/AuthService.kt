package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.config.JwtProvider
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.client.RestClient
import java.util.UUID
import java.time.LocalDateTime

@Service
class AuthService(
    private val userRepository: UserRepository,
    private val passwordEncoder: BCryptPasswordEncoder,
    private val jwtProvider: JwtProvider,
    private val restClient: RestClient,
    private val emailVerificationRepository: EmailVerificationRepository,
    private val emailService: EmailService
) {
    @Transactional
    fun signup(request: SignupRequest): User {
        if (userRepository.findByEmail(request.email) != null) {
            throw CustomException(HttpStatus.BAD_REQUEST, "이미 가입된 이메일입니다.")
        }
        val encodedPassword = passwordEncoder.encode(request.password)
        val user = User(
            email = request.email,
            password = encodedPassword!!,
            nickname = request.nickname,
            allergies = request.allergies,
            diseases = request.diseases
        )
        return userRepository.save(user)
    }

    @Transactional(readOnly = true)
    fun login(request: LoginRequest): String {
        val user = userRepository.findByEmail(request.email)
            ?: throw CustomException(HttpStatus.UNAUTHORIZED, "이메일 또는 비밀번호가 일치하지 않습니다.")

        if (!passwordEncoder.matches(request.password, user.password)) {
            throw CustomException(HttpStatus.UNAUTHORIZED, "이메일 또는 비밀번호가 일치하지 않습니다.")
        }
        return jwtProvider.createToken(user.id!!, user.email, user.role.name)
    }

    @Transactional
    fun googleLogin(request: GoogleLoginRequest): String {
        // 🚀 2. 구글 공식 검증 서버로 토큰을 보내서 진짜인지 확인합니다.
        val googleResponse = try {
            restClient.get()
                .uri("https://oauth2.googleapis.com/tokeninfo?id_token=${request.idToken}")
                .retrieve()
                .body(Map::class.java)
        } catch (e: Exception) {
            throw CustomException(HttpStatus.UNAUTHORIZED, "유효하지 않은 구글 토큰입니다.")
        }

        // 🚀 3. 검증된 데이터에서 이메일을 뽑아냅니다.
        val email = googleResponse?.get("email") as? String
            ?: throw CustomException(HttpStatus.BAD_REQUEST, "구글 계정에서 이메일 정보를 가져올 수 없습니다.")

        // 🚀 4. 우리 DB에 있는 유저인지 확인합니다.
        var user = userRepository.findByEmail(email)

        // 🚀 5. 처음 보는 이메일이라면? -> 묻지도 따지지도 않고 자동 회원가입!
        if (user == null) {
            // 소셜 로그인은 비밀번호가 필요 없지만, DB 제약조건(Not Null)을 통과하기 위해 절대 못 맞추는 쓰레기값을 암호화해서 넣습니다.
            val dummyPassword = passwordEncoder.encode(UUID.randomUUID().toString())

            user = User(
                email = email,
                password = dummyPassword!!,
                nickname = "구글유저_${email.substringBefore("@")}", // 이메일 앞자리를 임시 닉네임으로
                allergies = null,
                diseases = null,
                specialDiet = null,
                dislikedIngredients = null
            )
            user = userRepository.save(user)
        }

        // 🚀 6. 최종적으로 우리 서비스의 JWT 토큰을 발급해서 돌려줍니다.
        return jwtProvider.createToken(user.id!!, user.email, user.role.name)
    }
    @Transactional
    fun resetPassword(request: PasswordResetRequest) {
        // 1. 해당 이메일로 가입된 유저가 있는지 확인
        val user = userRepository.findByEmail(request.email)
            ?: throw CustomException(HttpStatus.NOT_FOUND, "가입되지 않은 이메일입니다.")

        // 2. 인증 테이블에서 번호 확인
        val verification = emailVerificationRepository.findByEmail(request.email)
            ?: throw CustomException(HttpStatus.BAD_REQUEST, "인증 요청 내역이 없습니다.")

        if (verification.expiredAt.isBefore(LocalDateTime.now())) {
            throw CustomException(HttpStatus.BAD_REQUEST, "인증 시간이 만료되었습니다.")
        }

        if (verification.code != request.code) {
            throw CustomException(HttpStatus.BAD_REQUEST, "인증번호가 일치하지 않습니다.")
        }

        // 3. 인증이 완벽하게 성공했으니 새 비밀번호로 암호화하여 덮어쓰기
        user.password = passwordEncoder.encode(request.newPassword)!!
        userRepository.save(user)

        // 4. 사용한 인증번호는 파기
        emailVerificationRepository.delete(verification)
    }

    fun verifyEmailCode(request: EmailVerifyRequest) {
        val verification = emailVerificationRepository.findByEmail(request.email)
            ?: throw CustomException(HttpStatus.BAD_REQUEST, "인증 요청 내역이 없습니다.")

        if (verification.expiredAt.isBefore(LocalDateTime.now())) {
            throw CustomException(HttpStatus.BAD_REQUEST, "인증 시간이 만료되었습니다.")
        }

        if (verification.code != request.code) {
            throw CustomException(HttpStatus.BAD_REQUEST, "인증번호가 일치하지 않습니다.")
        }
        emailVerificationRepository.delete(verification)
    }
}
