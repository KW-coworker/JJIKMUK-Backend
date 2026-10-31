package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.global.exception.CustomException
import org.junit.jupiter.api.Test
import org.springframework.http.HttpStatus
import java.util.concurrent.Callable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class LoginAttemptLimiterTest {
    private var now = 0L
    private fun limiter(account: Int = 5, ip: Int = 30, keys: Int = 100) =
        LoginAttemptLimiter(LoginThrottleProperties(account, ip, 300, keys)) { now }

    @Test fun `account quota is shared across different source IPs`() {
        val limiter = limiter()
        repeat(5) { limiter.acquire("user@example.com", "192.0.2.${it + 1}") }
        val error = limited { limiter.acquire("user@example.com", "198.51.100.1") }
        assertEquals(300L, error.retryAfterSeconds)
        limiter.acquire("another@example.com", "198.51.100.1")
    }

    @Test fun `IP quota is shared across different emails`() {
        val limiter = limiter(ip = 3)
        repeat(3) { limiter.acquire("user$it@example.com", "192.0.2.1") }
        limited { limiter.acquire("other@example.com", "192.0.2.1") }
        limiter.acquire("other@example.com", "192.0.2.2")
    }

    @Test fun `email NFKC casing and whitespace share the account key`() {
        val limiter = limiter(account = 1)
        limiter.acquire(" User@Example.COM ", "192.0.2.1")
        limited { limiter.acquire("ｕｓｅｒ＠ｅｘａｍｐｌｅ．ｃｏｍ", "192.0.2.2") }
    }

    @Test fun `IPv6 equivalent representations share IP quota`() {
        val limiter = limiter(ip = 1)
        limiter.acquire("one@example.com", "2001:db8::1")
        limited { limiter.acquire("two@example.com", "2001:0DB8:0000:0000:0000:0000:0000:0001") }
    }

    @Test fun `IPv4 mapped IPv6 shares IPv4 quota`() {
        val limiter = limiter(ip = 1)
        limiter.acquire("one@example.com", "192.0.2.1")
        limited { limiter.acquire("two@example.com", "::ffff:192.0.2.1") }
    }

    @Test fun `missing and invalid peer addresses do not create unlimited fresh quotas`() {
        val limiter = limiter(ip = 1)
        limiter.acquire("one@example.com", null)
        listOf("deadbeef", "example.com", "999.1.1.1", "").forEach {
            limited { limiter.acquire("two@example.com", it) }
        }
    }

    @Test fun `sliding window only frees expired attempts not the entire bucket`() {
        val limiter = limiter(account = 2)
        limiter.acquire("user@example.com", "192.0.2.1")
        now = 100_000
        limiter.acquire("user@example.com", "192.0.2.1")
        now = 299_001
        assertEquals(1L, limited { limiter.acquire("user@example.com", "192.0.2.1") }.retryAfterSeconds)
        now = 300_000
        limiter.acquire("user@example.com", "192.0.2.1")
        assertEquals(100L, limited { limiter.acquire("user@example.com", "192.0.2.1") }.retryAfterSeconds)
    }

    @Test fun `combined block returns the longer of account and IP waits`() {
        val limiter = limiter(account = 1, ip = 1)
        limiter.acquire("user@example.com", "192.0.2.1")
        now = 60_000
        limiter.acquire("other@example.com", "192.0.2.2")
        assertEquals(300L, limited { limiter.acquire("user@example.com", "192.0.2.2") }.retryAfterSeconds)
    }

    @Test fun `blocked retries neither slide lockout nor consume unrelated quotas`() {
        val limiter = limiter(account = 1, ip = 1)
        limiter.acquire("user@example.com", "192.0.2.1")
        now = 299_000
        repeat(20) { limited { limiter.acquire("user@example.com", "192.0.2.2") } }
        limiter.acquire("other@example.com", "192.0.2.2")
        now = 300_000
        limiter.acquire("user@example.com", "192.0.2.1")
    }

    @Test fun `capacity rejects fresh identities without evicting active account counters`() {
        val limiter = limiter(account = 2, keys = 2)
        limiter.acquire("one@example.com", "192.0.2.1")
        repeat(50) { limited { limiter.acquire("random$it@example.com", "198.51.100.1") } }
        limiter.acquire("one@example.com", "192.0.2.1")
        limited { limiter.acquire("one@example.com", "192.0.2.1") }
        now = 300_000
        limiter.acquire("new@example.com", "198.51.100.1")
    }

    @Test fun `capacity wait accounts for every slot needed by a new attempt`() {
        val limiter = limiter(keys = 3)
        limiter.acquire("one@example.com", "192.0.2.1")
        now = 100_000
        limiter.acquire("two@example.com", "192.0.2.1")
        assertEquals(300L, limited { limiter.acquire("new@example.com", "192.0.2.2") }.retryAfterSeconds)
        now = 400_000
        limiter.acquire("new@example.com", "192.0.2.2")
    }

    @Test fun `expired entries cleanup follows last admission order`() {
        val limiter = limiter(account = 5, keys = 3)
        limiter.acquire("one@example.com", "192.0.2.1")
        now = 100_000
        limiter.acquire("two@example.com", "192.0.2.1")
        now = 200_000
        limiter.acquire("one@example.com", "192.0.2.1")
        now = 400_000
        limiter.acquire("three@example.com", "192.0.2.1")
        limited { limiter.acquire("four@example.com", "192.0.2.1") }
    }

    @Test fun `simultaneous account attempts cannot overshoot admission limit`() {
        val limiter = limiter()
        val statuses = concurrently { limiter.acquire("same@example.com", "192.0.2.${it + 1}") }
        assertEquals(5, statuses.count { it })
    }

    @Test fun `simultaneous IP attempts cannot overshoot admission limit`() {
        val limiter = limiter(ip = 7)
        val statuses = concurrently { limiter.acquire("user$it@example.com", "192.0.2.1") }
        assertEquals(7, statuses.count { it })
    }

    @Test fun `invalid throttle settings fail fast instead of disabling protection`() {
        assertFailsWith<IllegalArgumentException> { LoginThrottleProperties(accountLimit = 0) }
        assertFailsWith<IllegalArgumentException> { LoginThrottleProperties(ipLimit = -1) }
        assertFailsWith<IllegalArgumentException> { LoginThrottleProperties(windowSeconds = 0) }
        assertFailsWith<IllegalArgumentException> { LoginThrottleProperties(maxTrackedKeys = 1) }
    }

    private fun limited(block: () -> Unit): CustomException = assertFailsWith<CustomException>(block = block).also {
        assertEquals(HttpStatus.TOO_MANY_REQUESTS, it.status)
        assertEquals("LOGIN_RATE_LIMITED", it.code)
    }

    private fun concurrently(block: (Int) -> Unit): List<Boolean> {
        val executor = Executors.newFixedThreadPool(20)
        val start = CountDownLatch(1)
        try {
            val tasks = (0 until 20).map { index -> executor.submit(Callable {
                check(start.await(5, TimeUnit.SECONDS))
                try { block(index); true } catch (e: CustomException) {
                    assertEquals("LOGIN_RATE_LIMITED", e.code)
                    false
                }
            }) }
            start.countDown()
            return tasks.map { it.get(10, TimeUnit.SECONDS) }
        } finally {
            executor.shutdownNow()
        }
    }
}
