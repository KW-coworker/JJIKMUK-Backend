package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.global.exception.CustomException
import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.springframework.http.HttpStatus

enum class EmailVerificationPurpose(val id: String) {
    SIGNUP("signup"),
    PASSWORD_RESET("password_reset");

    companion object {
        fun parse(value: String): EmailVerificationPurpose {
            val normalized = value.trim().lowercase().replace('-', '_')
            return entries.firstOrNull { it.id == normalized }
                ?: throw CustomException(
                    HttpStatus.BAD_REQUEST,
                    "purpose는 signup 또는 password_reset이어야 합니다.",
                    ApiErrorCode.VALIDATION_FAILED,
                    "purpose"
                )
        }
    }
}
