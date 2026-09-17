package org.jjikmuk.backend.global.exception

import org.springframework.http.HttpStatus

// 💡 "내가 원하는 상태 코드랑 메시지로 에러 터뜨릴 거야!" 할 때 사용하는 클래스입니다.
class CustomException(
    val status: HttpStatus,
    override val message: String
) : RuntimeException(message)