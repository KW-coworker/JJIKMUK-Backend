package org.jjikmuk.backend.global.exception

// 💡 프론트엔드에게 전달할 예쁜 에러 JSON 모양입니다.
data class ErrorResponse(
    val status: Int,
    val message: String
)