package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class AccountInputPolicyTest {
    @Test
    fun `email and nickname are normalized at the API boundary`() {
        assertEquals("user@example.com", AccountInputPolicy.normalizeEmail(" User@Example.COM "))
        assertEquals("찍먹_user1", AccountInputPolicy.normalizeNickname(" 찍먹_user1 "))
    }

    @Test
    fun `nickname rejects spaces and unsupported characters`() {
        val error = assertFailsWith<CustomException> {
            AccountInputPolicy.normalizeNickname("닉네임 공백")
        }
        assertEquals(ApiErrorCode.NICKNAME_INVALID, error.code)
        assertEquals("nickname", error.field)
    }

    @Test
    fun `password requires eight characters a letter a digit and no whitespace`() {
        AccountInputPolicy.validatePassword("safe-pass1")
        listOf("", "short1", "onlyletters", "12345678", "has space1").forEach { invalid ->
            val error = assertFailsWith<CustomException> {
                AccountInputPolicy.validatePassword(invalid)
            }
            assertEquals(ApiErrorCode.PASSWORD_INVALID, error.code)
        }
    }
}
