package org.jjikmuk.backend.domain.user

import org.jjikmuk.backend.domain.allergy.AllergyCatalog
import org.jjikmuk.backend.domain.auth.AccountInputPolicy
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus

/** Explicit key presence preserves omitted fields; null and empty strings clear optional fields. */
object ProfileInputs {
    val fields = setOf("nickname", "allergies", "diseases", "specialDiet", "dislikedIngredients")
    fun validateKeys(body: Map<String, Any?>, extra: Set<String> = emptySet()) {
        val unknown = body.keys - fields - extra
        if (unknown.isNotEmpty()) throw invalid(unknown.first(), "지원하지 않는 프로필 필드입니다.")
    }
    fun expectedVersion(raw: Any?): Long {
        val value = when (raw) {
            is Byte, is Short, is Int, is Long, is java.math.BigInteger -> raw.toString().toLongOrNull()
            else -> null
        }
        return value?.takeIf { it >= 0 }
            ?: throw invalid("version", "조회한 version을 0 이상의 정수로 전달해주세요.")
    }
    fun text(body: Map<String, Any?>, field: String, previous: String?): String? {
        if (!body.containsKey(field)) return previous
        val raw = body[field]
        if (raw != null && raw !is String) throw invalid(field, "문자열 또는 null만 사용할 수 있습니다. 배열은 지원하지 않습니다.")
        val value = raw as String?
        if (value != null && value.length > 1000) throw invalid(field, "입력값이 너무 깁니다.")
        return try {
            when (field) {
                "nickname" -> AccountInputPolicy.normalizeNickname(value ?: "")
                "allergies" -> AllergyCatalog.normalizeForStorage(value)
                "specialDiet" -> DietPreferenceCatalog.normalizeForStorage(value)
                else -> DelimitedProfileNormalizer.normalizeForStorage(value, field)
            }
        } catch (e: IllegalArgumentException) { throw invalid(field, e.message ?: "잘못된 입력입니다.") }
    }
    fun invalid(field: String, message: String) = CustomException(HttpStatus.BAD_REQUEST, message, "VALIDATION_FAILED", field)
}
