package org.jjikmuk.backend.global.exception

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice

@RestControllerAdvice // 💡 프로젝트 전체의 에러를 감시하는 레이더 역할입니다!
class GlobalExceptionHandler {

    // 🎯 1. 우리가 만든 CustomException이 터졌을 때 낚아채는 곳
    @ExceptionHandler(CustomException::class)
    fun handleCustomException(ex: CustomException): ResponseEntity<ErrorResponse> {
        val errorResponse = ErrorResponse(
            status = ex.status.value(),
            message = ex.message
        )
        return ResponseEntity.status(ex.status).body(errorResponse)
    }

    // 🎯 2. 예상치 못한 진짜 서버 에러(500)가 터졌을 때 방어하는 곳 (최후의 보루)
    @ExceptionHandler(Exception::class)
    fun handleGeneralException(ex: Exception): ResponseEntity<ErrorResponse> {
        // 에러 원인을 백엔드 콘솔에만 출력 (프론트엔드엔 비밀!)
        ex.printStackTrace()

        val errorResponse = ErrorResponse(
            status = 500,
            message = "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )
        return ResponseEntity.status(500).body(errorResponse)
    }
}