package org.jjikmuk.backend.domain.auth

import jakarta.persistence.*
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.config.JwtProvider
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.beans.factory.annotation.Value
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock
import org.springframework.data.jpa.repository.Query
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.util.UUID

@Entity @Table(name = "auth_sessions")
class AuthSession(
    @Id @Column(length = 36) val id: String = UUID.randomUUID().toString(),
    @Column(nullable = false) val userId: Long,
    @Column(nullable = false) val tokenVersion: Int,
    @Column(nullable = false) val expiresAt: Instant,
    var revokedAt: Instant? = null
)

@Entity @Table(name = "refresh_credentials")
class RefreshCredential(
    @Id @Column(length = 64) val tokenHash: String,
    @Column(nullable = false, length = 36) val sessionId: String,
    var consumedAt: Instant? = null
)

interface AuthSessionRepository : JpaRepository<AuthSession, String> {
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select s from AuthSession s where s.id = :id")
    fun lockById(id: String): AuthSession?
    fun findAllByUserId(userId: Long): List<AuthSession>
    @Query("select s.userId from AuthSession s where s.id = :id")
    fun ownerForId(id: String): Long?
    fun deleteByUserId(userId: Long)
}
interface RefreshCredentialRepository : JpaRepository<RefreshCredential, String> {
    @Query("select r.sessionId from RefreshCredential r where r.tokenHash = :hash")
    fun sessionIdForHash(hash: String): String?
    fun deleteBySessionId(sessionId: String)
}

@Service
class AuthSessionService(
    private val sessions: AuthSessionRepository,
    private val credentials: RefreshCredentialRepository,
    private val users: UserRepository,
    private val jwt: JwtProvider,
    @Value("\${auth.refresh.lifetime-days:30}") private val lifetimeDays: Long
) {
    @Transactional
    fun issue(user: User, isNewUser: Boolean, message: String): AuthResponse {
        require(lifetimeDays in 1..90)
        val session = sessions.save(AuthSession(userId = requireNotNull(user.id), tokenVersion = user.tokenVersion,
            expiresAt = Instant.now().plusSeconds(lifetimeDays * 86400)))
        return tokens(user, session, isNewUser, message)
    }

    // Keep consumed hashes until session expiry: replay detection also invalidates the new credential.
    // Client must serialize refresh calls; response loss requires reauthentication, not blind replay.
    @Transactional(noRollbackFor = [CustomException::class])
    fun refresh(raw: String): AuthResponse {
        if (!raw.matches(Regex("[A-Za-z0-9_-]{43}"))) throw invalid()
        val hash = EmailVerificationSecurity.hashToken(raw)
        val id = credentials.sessionIdForHash(hash) ?: throw invalid()
        // Always lock user before session, also used by password changes and logout.
        val sessionUser = sessions.ownerForId(id) ?: throw invalid()
        val user = users.lockById(sessionUser) ?: throw invalid()
        val session = sessions.lockById(id) ?: throw invalid()
        val credential = credentials.findById(hash).orElse(null) ?: throw invalid()
        if (session.revokedAt != null || !session.expiresAt.isAfter(Instant.now()) || session.tokenVersion != user.tokenVersion) {
            session.revokedAt = Instant.now()
            throw invalid()
        }
        if (credential.consumedAt != null) {
            session.revokedAt = Instant.now()
            throw CustomException(HttpStatus.UNAUTHORIZED, "이미 사용한 갱신 토큰입니다. 다시 로그인해주세요.", "REFRESH_TOKEN_REUSED")
        }
        credential.consumedAt = Instant.now()
        return tokens(user, session, false, "로그인 갱신 성공")
    }

    @Transactional
    fun logout(userId: Long, sessionId: String?) {
        val user = users.lockById(userId) ?: throw invalid()
        if (sessionId == null) {
            // Old tokens have no device session; use the conservative all-device revocation.
            user.invalidateSessions()
            revokeAll(userId)
        } else {
            val session = sessions.lockById(sessionId) ?: throw invalid()
            if (session.userId != userId) throw invalid()
            session.revokedAt = Instant.now()
        }
    }

    @Transactional
    fun revokeAll(userId: Long) {
        sessions.findAllByUserId(userId).forEach { it.revokedAt = Instant.now() }
    }

    @Transactional
    fun deleteAll(userId: Long) {
        sessions.findAllByUserId(userId).forEach { credentials.deleteBySessionId(it.id) }
        sessions.deleteByUserId(userId)
    }

    private fun tokens(user: User, session: AuthSession, isNew: Boolean, message: String): AuthResponse {
        val refresh = EmailVerificationSecurity.newToken()
        credentials.save(RefreshCredential(EmailVerificationSecurity.hashToken(refresh), session.id))
        val access = jwt.createToken(requireNotNull(user.id), user.email, user.role.name, user.tokenVersion, session.id)
        return AuthResponse(message, access.token, userId = requireNotNull(user.id), email = user.email,
            expiresAt = access.expiresAt, expiresInSeconds = access.expiresInSeconds,
            isNewUser = isNew, profileCompleted = user.profileCompleted,
            refreshToken = refresh, refreshExpiresAt = session.expiresAt,
            authProvider = user.authProvider.name, hasPassword = user.authProvider.supportsPassword)
    }
    private fun invalid() = CustomException(HttpStatus.UNAUTHORIZED, "로그인 유지 기간이 끝났거나 세션이 무효합니다. 다시 로그인해주세요.", "REFRESH_TOKEN_INVALID")
}
