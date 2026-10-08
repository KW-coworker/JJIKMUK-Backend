package org.jjikmuk.backend.domain.recommendation

import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.domain.user.User
import org.jjikmuk.backend.domain.user.UserRepository
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import java.util.UUID
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
class RecommendationFeedbackServiceTest @Autowired constructor(
    private val feedbackService: RecommendationFeedbackService,
    private val productRepository: ProductRepository,
    private val userRepository: UserRepository,
    private val jdbcTemplate: JdbcTemplate
) {
    @BeforeEach
    fun createFeedbackTable() {
        jdbcTemplate.execute(
            """
            CREATE TABLE IF NOT EXISTS product_recommendation_feedback (
                feedback_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                request_id CHAR(36) NOT NULL,
                user_id BIGINT NOT NULL,
                product_barcode VARCHAR(32) NOT NULL,
                feedback_type VARCHAR(32) NOT NULL,
                rank_position INT NULL,
                created_at TIMESTAMP NOT NULL,
                CONSTRAINT uk_recommendation_feedback_test
                    UNIQUE (request_id, user_id, product_barcode, feedback_type)
            )
            """.trimIndent()
        )
    }

    @Test
    fun `stores recommendation feedback for a real product`() {
        val product = productRepository.save(Product(barcode = "8800000400001", productName = "피드백 상품"))
        val user = userRepository.save(
            User(
                email = "recommendation-feedback@example.com",
                nickname = "피드백 사용자",
                password = "test-password"
            )
        )
        val requestId = UUID.randomUUID().toString()

        val response = feedbackService.record(
            userId = requireNotNull(user.id),
            request = RecommendationFeedbackRequest(requestId, product.barcode, "click", 2)
        )

        assertEquals("CLICK", response.feedbackType)
        assertEquals(
            1,
            jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM product_recommendation_feedback WHERE request_id = ?",
                Int::class.java,
                requestId
            )
        )
    }
}
