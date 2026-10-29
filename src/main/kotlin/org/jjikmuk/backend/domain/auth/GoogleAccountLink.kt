package org.jjikmuk.backend.domain.auth

import jakarta.persistence.*
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.beans.factory.annotation.Value
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock
import org.springframework.data.jpa.repository.Query
import org.springframework.http.HttpStatus
import org.springframework.stereotype.Component
import org.springframework.web.client.RestClient
import org.springframework.web.client.RestClientResponseException
import java.time.Instant

data class GoogleIdentity(val subject: String, val email: String)

@Component
class GoogleIdentityVerifier(private val restClient: RestClient,
    @Value("\${google.client-id:}") private val clientId: String) {
    fun verify(idToken: String): GoogleIdentity {
        if (clientId.isBlank()) throw CustomException(HttpStatus.SERVICE_UNAVAILABLE,
            "Google 로그인이 아직 구성되지 않았습니다.", "GOOGLE_LOGIN_UNAVAILABLE")
        if (idToken.length !in 20..10000) throw invalid()
        val result = try {
            restClient.get().uri { it.scheme("https").host("oauth2.googleapis.com").path("/tokeninfo")
                .queryParam("id_token", idToken).build() }.retrieve().body(Map::class.java)
        } catch (e: RestClientResponseException) {
            if (e.statusCode.is4xxClientError) throw invalid()
            throw unavailable()
        } catch (_: Exception) { throw unavailable() }
        val subject = result?.get("sub")?.toString()?.takeIf { it.isNotBlank() && it.length <= 255 } ?: throw invalid()
        if (result["aud"] != clientId || result["email_verified"].toString() != "true" ||
            result["iss"] !in setOf("accounts.google.com", "https://accounts.google.com") ||
            (result["exp"].toString().toLongOrNull() ?: 0) <= Instant.now().epochSecond) throw invalid()
        val email = try { AccountInputPolicy.normalizeEmail(result["email"] as? String ?: "") }
            catch (_: CustomException) { throw invalid() }
        return GoogleIdentity(subject, email)
    }
    private fun invalid() = CustomException(HttpStatus.UNAUTHORIZED, "유효하지 않은 Google ID 토큰입니다.", "GOOGLE_TOKEN_INVALID")
    private fun unavailable() = CustomException(HttpStatus.SERVICE_UNAVAILABLE, "Google 인증 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", "GOOGLE_LOGIN_UNAVAILABLE")
}

@Entity @Table(name = "google_link_grants")
class GoogleLinkGrant(
    @Id @Column(length = 64) val tokenHash: String,
    @Column(nullable = false) val userId: Long,
    @Column(nullable = false, length = 255) val googleSubject: String,
    @Column(nullable = false) val tokenVersion: Int,
    @Column(nullable = false) val expiresAt: Instant,
    @Column(nullable = false) var attempts: Int = 0,
    var consumedAt: Instant? = null
)
interface GoogleLinkGrantRepository : JpaRepository<GoogleLinkGrant, String> {
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select g from GoogleLinkGrant g where g.tokenHash = :hash")
    fun lockByHash(hash: String): GoogleLinkGrant?
    @Query("select g.userId from GoogleLinkGrant g where g.tokenHash = :hash")
    fun ownerForHash(hash: String): Long?
    fun deleteByUserId(userId: Long)
}
