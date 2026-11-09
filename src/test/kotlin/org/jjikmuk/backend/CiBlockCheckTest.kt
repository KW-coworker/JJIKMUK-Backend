package org.jjikmuk.backend

import kotlin.test.Test
import kotlin.test.assertEquals

// CI 실패 차단 확인용 임시 테스트. 머지하지 않고 PR을 닫는다.
class CiBlockCheckTest {
    @Test
    fun `일부러 실패하는 테스트`() {
        assertEquals(1, 2)
    }
}
