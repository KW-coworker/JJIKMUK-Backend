package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.boot.context.properties.ConfigurationProperties
import org.springframework.boot.context.properties.EnableConfigurationProperties
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpStatus
import java.net.InetAddress
import java.security.MessageDigest
import java.text.Normalizer
import java.util.ArrayDeque
import java.util.LinkedHashMap
import java.util.concurrent.TimeUnit

@ConfigurationProperties("auth.login-throttle")
data class LoginThrottleProperties(
    val accountLimit: Int = 5,
    val ipLimit: Int = 30,
    val windowSeconds: Long = 300,
    val maxTrackedKeys: Int = 10_000
) {
    init {
        require(accountLimit in 1..1_000) { "login account-limit must be 1..1000" }
        require(ipLimit in 1..10_000) { "login ip-limit must be 1..10000" }
        require(windowSeconds in 1..86_400) { "login window-seconds must be 1..86400" }
        require(maxTrackedKeys in 2..100_000) { "login max-tracked-keys must be 2..100000" }
    }
}

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(LoginThrottleProperties::class)
class LoginThrottleConfiguration {
    @Bean
    fun loginThrottleTicker() = LoginThrottleTicker { TimeUnit.NANOSECONDS.toMillis(System.nanoTime()) }

    @Bean
    fun loginAttemptLimiter(properties: LoginThrottleProperties, ticker: LoginThrottleTicker) =
        LoginAttemptLimiter(properties, ticker::millis)
}

fun interface LoginThrottleTicker {
    fun millis(): Long
}

/**
 * Per-process sliding-window admission control. Counts accepted attempts (not only failures),
 * before password verification/DB access, independently of the authentication transaction.
 * Multi-instance deployments need a shared atomic store instead of this in-memory implementation.
 */
class LoginAttemptLimiter(
    private val properties: LoginThrottleProperties,
    private val tickMillis: () -> Long = { TimeUnit.NANOSECONDS.toMillis(System.nanoTime()) }
) {
    private val windowMillis = properties.windowSeconds * 1_000
    // Reinsert only on admission: iteration order is last-admitted time, hence expiration order.
    private val attempts = LinkedHashMap<String, ArrayDeque<Long>>()

    fun acquire(email: String, remoteAddress: String?) {
        val accountKey = "account:" + digest(Normalizer.normalize(email, Normalizer.Form.NFKC).trim().lowercase())
        val ipKey = "ip:" + digest(normalizeAddress(remoteAddress))
        synchronized(attempts) {
            val now = tickMillis()
            val cutoff = now - windowMillis
            val iterator = attempts.entries.iterator()
            while (iterator.hasNext()) {
                if (iterator.next().value.peekLast() > cutoff) break
                iterator.remove()
            }
            val account = attempts[accountKey]
            val ip = attempts[ipKey]
            val retryAt = maxOf(
                nextAvailable(account, properties.accountLimit, cutoff),
                nextAvailable(ip, properties.ipLimit, cutoff)
            )
            if (retryAt > now) limited(retryAt - now)

            val missingKeys = (if (account == null) 1 else 0) + (if (ip == null) 1 else 0)
            val keysToExpire = attempts.size + missingKeys - properties.maxTrackedKeys
            if (keysToExpire > 0) {
                // Fail closed on capacity: never evict an active quota to admit arbitrary new identities.
                val capacityAvailableAt = attempts.values.elementAt(keysToExpire - 1).peekLast() + windowMillis
                limited(capacityAvailableAt - now)
            }
            record(accountKey, account, now)
            record(ipKey, ip, now)
        }
    }

    private fun nextAvailable(bucket: ArrayDeque<Long>?, limit: Int, cutoff: Long): Long {
        if (bucket == null) return Long.MIN_VALUE
        while (bucket.isNotEmpty() && bucket.peekFirst() <= cutoff) bucket.removeFirst()
        return if (bucket.size >= limit) bucket.peekFirst() + windowMillis else Long.MIN_VALUE
    }

    private fun record(key: String, bucket: ArrayDeque<Long>?, now: Long) {
        val updated = bucket ?: ArrayDeque()
        updated.addLast(now)
        attempts.remove(key)
        attempts[key] = updated
    }

    private fun limited(waitMillis: Long): Nothing = throw CustomException(
        HttpStatus.TOO_MANY_REQUESTS,
        "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.",
        ApiErrorCode.LOGIN_RATE_LIMITED,
        retryAfterSeconds = ((waitMillis + 999) / 1_000).coerceAtLeast(1)
    )

    private fun digest(value: String): String =
        java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)))

    private fun normalizeAddress(value: String?): String {
        val address = value?.trim()?.substringBefore('%').orEmpty()
        // Numeric literals only: never perform hostname/DNS lookup for untrusted request data.
        val ipv4 = address.matches(Regex("(?:[0-9]{1,3}\\.){3}[0-9]{1,3}")) &&
            address.split('.').all { it.toInt() <= 255 }
        val ipv6 = ':' in address && address.matches(Regex("[0-9a-fA-F:.]+"))
        if (!ipv4 && !ipv6) return "unknown"
        return try {
            java.util.HexFormat.of().formatHex(InetAddress.getByName(address).address)
        } catch (_: IllegalArgumentException) {
            "unknown"
        } catch (_: java.net.UnknownHostException) {
            "unknown"
        }
    }
}
