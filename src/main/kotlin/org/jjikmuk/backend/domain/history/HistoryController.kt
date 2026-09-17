package org.jjikmuk.backend.domain.history

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.security.core.Authentication
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.http.HttpStatus

@RestController
@RequestMapping("/api/histories")
class HistoryController(
    private val historyService: HistoryService
) {
    @PostMapping("/events")
    fun recordUserAction(
        @RequestBody request: UserActionEventRequest,
        authentication: Authentication
    ): ResponseEntity<*> {
        val currentUserId = authentication.principal.toString().toLong()
        val data = historyService.recordAction(currentUserId, request)
        return ResponseEntity.ok(
            mapOf(
                "message" to "사용자 행동 기록 성공",
                "data" to data
            )
        )
    }

    @GetMapping("/user/{userId}")
    fun getUserHistory(@PathVariable userId: Long, authentication: Authentication): ResponseEntity<*> {
        // 🚀 1. 토큰에서 현재 요청한 사람의 ID와 권한을 꺼냅니다.
        val currentUserId = authentication.principal.toString().toLong()
        val isAdmin = authentication.authorities.any { it.authority == "ROLE_ADMIN" }

        // 🚀 2. 본인이 아니면서 관리자도 아니라면 쫓아냅니다 (403 Forbidden)
        if (currentUserId != userId && !isAdmin) {
            throw CustomException(HttpStatus.FORBIDDEN, "다른 사용자의 검색 기록을 볼 수 없습니다.")
        }

        val historyList = historyService.getUserHistory(userId)

        return ResponseEntity.ok(mapOf(
            "message" to "사용자 히스토리 조회 성공",
            "data" to historyList
        ))
    }
}
