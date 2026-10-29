package org.jjikmuk.backend.global.exception

import org.springframework.http.ResponseEntity
import org.springframework.http.HttpStatus
import org.springframework.http.converter.HttpMessageNotReadableException
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice

@RestControllerAdvice // 💡 프로젝트 전체의 에러를 감시하는 레이더 역할입니다!
class GlobalExceptionHandler {

    @ExceptionHandler(org.springframework.web.method.annotation.MethodArgumentTypeMismatchException::class)
    fun invalidParameter(ex: org.springframework.web.method.annotation.MethodArgumentTypeMismatchException): ResponseEntity<ErrorResponse> =
        ResponseEntity.badRequest().body(ErrorResponse(400, ApiErrorCode.VALIDATION_FAILED,
            "요청 파라미터 형식이 올바르지 않습니다.", ex.name))

    @ExceptionHandler(org.springframework.web.bind.MissingServletRequestParameterException::class,
        org.springframework.web.multipart.support.MissingServletRequestPartException::class)
    fun missingParameter(ex: Exception): ResponseEntity<ErrorResponse> =
        ResponseEntity.badRequest().body(ErrorResponse(400, ApiErrorCode.VALIDATION_FAILED, "필수 요청 항목이 누락되었습니다."))

    @ExceptionHandler(HttpMessageNotReadableException::class)
    fun handleUnreadableRequest(ex: HttpMessageNotReadableException): ResponseEntity<ErrorResponse> {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(
            ErrorResponse(
                status = HttpStatus.BAD_REQUEST.value(),
                code = ApiErrorCode.INVALID_REQUEST_BODY,
                message = "요청 본문 형식이 올바르지 않거나 필수 항목이 누락되었습니다."
            )
        )
    }

    // 🎯 1. 우리가 만든 CustomException이 터졌을 때 낚아채는 곳
    @ExceptionHandler(CustomException::class)
    fun handleCustomException(ex: CustomException): ResponseEntity<ErrorResponse> {
        val errorResponse = ErrorResponse(
            status = ex.status.value(),
            code = ex.code,
            message = ex.message,
            field = ex.field,
            retryAfterSeconds = ex.retryAfterSeconds,
            remainingAttempts = ex.remainingAttempts
        )
        val builder = ResponseEntity.status(ex.status)
        ex.retryAfterSeconds?.let { builder.header("Retry-After", it.toString()) }
        return builder.body(errorResponse)
    }

    @ExceptionHandler(org.springframework.orm.ObjectOptimisticLockingFailureException::class)
    fun concurrentEdit(ex: Exception): ResponseEntity<ErrorResponse> = ResponseEntity.status(409)
        .body(ErrorResponse(409, "PROFILE_VERSION_CONFLICT", "다른 기기에서 변경되었습니다. 다시 조회 후 수정해주세요."))

    @ExceptionHandler(org.springframework.web.multipart.MaxUploadSizeExceededException::class)
    fun tooLarge(ex: Exception): ResponseEntity<ErrorResponse> = ResponseEntity.status(413)
        .body(ErrorResponse(413, "PHOTO_TOO_LARGE", "사진 업로드 크기를 초과했습니다.", "file"))

    // 🎯 2. 예상치 못한 진짜 서버 에러(500)가 터졌을 때 방어하는 곳 (최후의 보루)
    @ExceptionHandler(Exception::class)
    fun handleGeneralException(ex: Exception): ResponseEntity<ErrorResponse> {
        // 에러 원인을 백엔드 콘솔에만 출력 (프론트엔드엔 비밀!)
        ex.printStackTrace()

        val errorResponse = ErrorResponse(
            status = 500,
            code = ApiErrorCode.INTERNAL_SERVER_ERROR,
            message = "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )
        return ResponseEntity.status(500).body(errorResponse)
    }
}
