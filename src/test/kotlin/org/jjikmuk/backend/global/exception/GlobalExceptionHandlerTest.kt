package org.jjikmuk.backend.global.exception

import org.springframework.http.HttpStatus
import kotlin.test.Test
import kotlin.test.assertEquals

class GlobalExceptionHandlerTest {
    @Test
    fun `error response exposes stable code and optional field`() {
        val response = GlobalExceptionHandler().handleCustomException(
            CustomException(
                HttpStatus.CONFLICT,
                "이미 사용 중인 닉네임입니다.",
                ApiErrorCode.NICKNAME_ALREADY_EXISTS,
                "nickname"
            )
        )

        assertEquals(409, response.statusCode.value())
        assertEquals(ApiErrorCode.NICKNAME_ALREADY_EXISTS, response.body?.code)
        assertEquals("nickname", response.body?.field)
    }
}
