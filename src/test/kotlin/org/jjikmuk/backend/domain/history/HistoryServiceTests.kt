package org.jjikmuk.backend.domain.history

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.test.context.ActiveProfiles
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
class HistoryServiceTests @Autowired constructor(
    private val historyService: HistoryService,
    private val historyRepository: HistoryRepository,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository
) {
    @Test
    fun `maps unknown legacy action to a neutral signal`() {
        assertEquals(UserActionType.OTHER, UserActionType.fromStored("legacy_action"))
        assertEquals(null, UserActionType.fromRequest("OTHER"))
    }

    @Test
    fun `records a normalized explicit preference event`() {
        val product = productRepository.save(Product(barcode = "8800000300001", productName = "행동 상품"))
        val user = userRepository.save(
            User(
                email = "history-action@example.com",
                nickname = "행동 사용자",
                password = "test-password"
            )
        )

        val response = historyService.recordAction(
            requireNotNull(user.id),
            UserActionEventRequest(product.barcode, "favorite")
        )

        assertEquals("FAVORITE", response.actionType)
        assertEquals(
            UserActionType.FAVORITE,
            historyRepository.findById(response.eventId).orElseThrow().actionType
        )
    }
}
