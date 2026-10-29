package org.jjikmuk.backend.domain.auth

import org.jjikmuk.backend.global.exception.ApiErrorCode
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus
import java.nio.charset.StandardCharsets
import java.text.Normalizer

object AccountInputPolicy {
    private val emailPattern = Regex("^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+$")
    private val nicknamePattern = Regex("^[가-힣A-Za-z0-9_]{2,20}$")

    fun normalizeEmail(value: String): String {
        val normalized = Normalizer.normalize(value, Normalizer.Form.NFKC).trim().lowercase()
        if (normalized.length !in 3..254 || !emailPattern.matches(normalized)) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "올바른 이메일 형식을 입력해주세요.",
                ApiErrorCode.EMAIL_INVALID,
                "email"
            )
        }
        return normalized
    }

    fun normalizeNickname(value: String): String {
        val normalized = Normalizer.normalize(value, Normalizer.Form.NFKC).trim()
        if (!nicknamePattern.matches(normalized)) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "닉네임은 2~20자의 한글, 영문, 숫자, 밑줄만 사용할 수 있습니다.",
                ApiErrorCode.NICKNAME_INVALID,
                "nickname"
            )
        }
        return normalized
    }

    fun validatePassword(value: String) {
        val utf8Length = value.toByteArray(StandardCharsets.UTF_8).size
        val valid = value.length >= 8 &&
            utf8Length <= 72 &&
            value.all { it in '!'..'~' } &&
            value.any { it in 'A'..'Z' || it in 'a'..'z' } &&
            value.any { it in '0'..'9' }
        if (!valid) {
            throw CustomException(
                HttpStatus.BAD_REQUEST,
                "비밀번호는 8자 이상, UTF-8 72바이트 이하이며 영문과 숫자를 포함해야 합니다. 공백·한글은 사용할 수 없고 ASCII 특수문자는 선택 사항입니다.",
                ApiErrorCode.PASSWORD_INVALID,
                "password"
            )
        }
    }
}
