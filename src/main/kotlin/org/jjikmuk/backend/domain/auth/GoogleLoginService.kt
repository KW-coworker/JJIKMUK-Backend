package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.domain.user.AuthProvider
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.dao.DuplicateKeyException
import org.springframework.http.HttpStatus
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Propagation
import org.springframework.transaction.annotation.Transactional
import java.sql.SQLException
import java.time.Instant
import java.util.UUID

@Service
class GoogleLoginService(
    private val verifier: GoogleIdentityVerifier,
    private val transactions: GoogleLoginTransactions
) {
    // Reject an enclosing transaction rather than suspending it: suspension can retain its
    // connection/locks during Google's network request. Call from the non-transactional API facade.
    @Transactional(propagation = Propagation.NEVER)
    fun login(request: GoogleLoginRequest): Any {
        val identity = verifier.verify(request.idToken)
        return try {
            transactions.loginOrCreate(identity)
        } catch (conflict: GoogleAccountCreationConflict) {
            // The transactional proxy has completed rollback before control reaches this catch.
            // Re-read at most once, in a new transaction; never reuse a rollback-only persistence context.
            transactions.recoverExisting(identity) ?: throw conflict.original
        }
    }
}

/** Separate bean is deliberate: self-invocation would bypass Spring's transaction proxy. */
@Service
class GoogleLoginTransactions(
    private val users: UserRepository,
    private val encoder: BCryptPasswordEncoder,
    private val sessions: AuthSessionService,
    private val grants: GoogleLinkGrantRepository
) {
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    fun loginOrCreate(identity: GoogleIdentity): Any {
        existing(identity)?.let { return it }
        val user = User(
            email = identity.email,
            password = encoder.encode(UUID.randomUUID().toString())!!,
            nickname = generateUniqueNickname(),
            authProvider = AuthProvider.GOOGLE,
            profileCompleted = false,
            googleSubject = identity.subject
        )
        val saved = try {
            users.saveAndFlush(user)
        } catch (error: DataIntegrityViolationException) {
            // Only new-user unique-key failures qualify, never FK/null failures or session writes.
            if (!isUniqueKeyViolation(error)) throw error
            throw GoogleAccountCreationConflict(error)
        }
        // Account and issued session commit together, or both roll back.
        return sessions.issue(saved, true, "구글 로그인 성공")
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    fun recoverExisting(identity: GoogleIdentity): Any? = existing(identity)

    private fun existing(identity: GoogleIdentity): Any? {
        users.idForGoogleSubject(identity.subject)?.let { id ->
            val user = users.lockById(id) ?: throw invalidGoogleToken()
            // Recheck after acquiring the lock rather than trusting an earlier unlocked lookup.
            if (user.googleSubject != identity.subject) throw invalidGoogleToken()
            return sessions.issue(user, false, "구글 로그인 성공")
        }
        val id = users.idForEmail(identity.email) ?: return null
        val user = users.lockById(id) ?: throw invalidGoogleToken()
        if (user.googleSubject != null) {
            if (user.googleSubject != identity.subject) throw invalidGoogleToken()
            return sessions.issue(user, false, "구글 로그인 성공")
        }
        if (user.authProvider.supportsPassword) {
            // A LOCAL signup may have won the race. Email equality never grants login or auto-linking.
            val token = EmailVerificationSecurity.newToken()
            grants.deleteByUserId(id)
            val expiresAt = Instant.now().plusSeconds(300)
            grants.save(GoogleLinkGrant(EmailVerificationSecurity.hashToken(token), id,
                identity.subject, user.tokenVersion, expiresAt))
            return GoogleLinkRequiredResponse(linkToken = token, expiresAt = expiresAt)
        }
        // Preserve the existing one-time migration of an unbound legacy Google-only account.
        user.googleSubject = identity.subject
        users.saveAndFlush(user)
        return sessions.issue(user, false, "구글 로그인 성공")
    }

    private fun generateUniqueNickname(): String {
        repeat(10) {
            val candidate = "user_${UUID.randomUUID().toString().replace("-", "").take(8)}"
            if (!users.existsByNicknameIgnoreCase(candidate)) return candidate
        }
        throw CustomException(HttpStatus.SERVICE_UNAVAILABLE,
            "닉네임 생성에 실패했습니다. 잠시 후 다시 시도해주세요.", ApiErrorCode.INTERNAL_SERVER_ERROR)
    }

    private fun invalidGoogleToken() = CustomException(HttpStatus.UNAUTHORIZED,
        "유효하지 않은 Google ID 토큰입니다.", ApiErrorCode.GOOGLE_TOKEN_INVALID)
}

internal class GoogleAccountCreationConflict(val original: DataIntegrityViolationException) :
    RuntimeException("Google account creation hit a unique constraint", original)

/** Driver codes, not localized messages/constraint names. SQLState 23000 alone includes non-unique failures. */
internal fun isUniqueKeyViolation(error: DataIntegrityViolationException): Boolean =
    generateSequence<Throwable>(error) { it.cause }.any {
        it is DuplicateKeyException || it is SQLException &&
            (it.sqlState == "23505" || it.sqlState == "23000" && it.errorCode == 1062)
    }
