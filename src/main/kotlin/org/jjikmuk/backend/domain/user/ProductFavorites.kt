package org.jjikmuk.backend.domain.user

import jakarta.persistence.*
import org.jjikmuk.backend.domain.history.History
import org.jjikmuk.backend.domain.history.HistoryRepository
import org.jjikmuk.backend.domain.history.UserActionType
import org.jjikmuk.backend.domain.product.Product
import org.jjikmuk.backend.domain.product.ProductRepository
import org.jjikmuk.backend.global.exception.CustomException
import org.springframework.data.domain.PageRequest
import org.springframework.data.domain.Pageable
import org.springframework.data.domain.Slice
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.http.HttpStatus
import org.springframework.security.core.Authentication
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.*
import java.time.LocalDateTime

@Entity
@Table(name = "product_favorites", uniqueConstraints = [UniqueConstraint(
    name = "uk_favorite_user_product", columnNames = ["user_id", "product_id"])])
class ProductFavorite(
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) val id: Long? = null,
    @Column(nullable = false) val userId: Long,
    @Column(nullable = false) val productId: Long,
    @Column(nullable = false) val barcode: String,
    @Column(nullable = false) val createdAt: LocalDateTime = LocalDateTime.now()
)

interface ProductFavoriteRepository : JpaRepository<ProductFavorite, Long> {
    fun findByUserIdAndProductId(userId: Long, productId: Long): ProductFavorite?
    fun findByUserIdOrderByCreatedAtDescIdDesc(userId: Long, pageable: Pageable): Slice<ProductFavorite>
    fun deleteByUserId(userId: Long)
}

data class FavoriteState(val productId: Long, val isFavorite: Boolean, val favoritedAt: LocalDateTime?)
data class FavoriteItem(val productId: Long, val barcode: String, val favoritedAt: LocalDateTime,
    val product: Product?, val identityStatus: String, val isFavorite: Boolean = true)
data class FavoritePage(val items: List<FavoriteItem>, val page: Int, val size: Int, val hasNext: Boolean)

@Service
@Transactional(readOnly = true)
class ProductFavoriteService(
    private val favorites: ProductFavoriteRepository,
    private val users: UserRepository,
    private val products: ProductRepository,
    private val histories: HistoryRepository
) {
    fun list(ownerId: Long, page: Int, size: Int): FavoritePage {
        validateListPage(page, size)
        val result = favorites.findByUserIdOrderByCreatedAtDescIdDesc(ownerId, PageRequest.of(page, size))
        val productMap = if (result.isEmpty) emptyMap() else products
            .findAllByProductIdIn(result.content.map { it.productId }).associateBy { it.productId }
        return FavoritePage(result.content.map {
            val product = productMap[it.productId]
            FavoriteItem(it.productId, product?.barcode ?: it.barcode, it.createdAt, product,
                if (product == null) "NOT_IN_ACTIVE_DATASET" else "INTERNAL_ID")
        }, page, size, result.hasNext())
    }

    fun state(ownerId: Long, productId: Long): FavoriteState {
        validateProductId(productId)
        val favorite = favorites.findByUserIdAndProductId(ownerId, productId)
        return FavoriteState(productId, favorite != null, favorite?.createdAt)
    }

    @Transactional
    fun add(ownerId: Long, productId: Long): FavoriteState {
        validateProductId(productId)
        // Cross-device add/remove and account deletion share the owner lock.
        // State + event commit together; retrying PUT never duplicates events or changes ordering.
        val owner = lockOwner(ownerId)
        val existing = favorites.findByUserIdAndProductId(ownerId, productId)
        if (existing != null) return FavoriteState(productId, true, existing.createdAt)
        val product = products.findByProductId(productId) ?: throw CustomException(
            HttpStatus.NOT_FOUND, "현재 데이터셋에서 해당 상품 ID를 찾을 수 없습니다.", "PRODUCT_NOT_FOUND")
        val saved = favorites.saveAndFlush(ProductFavorite(userId = ownerId, productId = productId, barcode = product.barcode))
        histories.save(History(user = owner, barcode = product.barcode, actionType = UserActionType.FAVORITE,
            productId = productId, attributeSnapshotId = product.attributeSnapshotId))
        return FavoriteState(productId, true, saved.createdAt)
    }

    @Transactional
    fun remove(ownerId: Long, productId: Long): FavoriteState {
        validateProductId(productId)
        val owner = lockOwner(ownerId)
        val favorite = favorites.findByUserIdAndProductId(ownerId, productId)
            ?: return FavoriteState(productId, false, null)
        val product = products.findByProductId(productId)
        favorites.delete(favorite)
        histories.save(History(user = owner, barcode = product?.barcode ?: favorite.barcode,
            actionType = UserActionType.UNFAVORITE, productId = productId,
            attributeSnapshotId = product?.attributeSnapshotId))
        return FavoriteState(productId, false, null)
    }

    private fun lockOwner(id: Long) = users.lockById(id)
        ?: throw CustomException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.", "USER_NOT_FOUND")
    private fun validateProductId(id: Long) {
        if (id <= 0) throw ProfileInputs.invalid("productId", "productId는 양수여야 합니다.")
    }
}

internal fun validateListPage(page: Int, size: Int) {
    if (page !in 0..10000) throw ProfileInputs.invalid("page", "page는 0~10000 범위여야 합니다.")
    if (size !in 1..50) throw ProfileInputs.invalid("size", "size는 1~50 범위여야 합니다.")
}

@RestController
@RequestMapping("/api/users/me/favorites")
class ProductFavoriteController(private val service: ProductFavoriteService) {
    @GetMapping fun list(auth: Authentication, @RequestParam(defaultValue = "0") page: Int,
        @RequestParam(defaultValue = "20") size: Int) =
        mapOf("message" to "좋아요 상품 목록 조회 성공", "data" to service.list(auth.owner(), page, size))
    @GetMapping("/{productId}") fun state(auth: Authentication, @PathVariable productId: Long) =
        mapOf("message" to "좋아요 상태 조회 성공", "data" to service.state(auth.owner(), productId))
    @PutMapping("/{productId}") fun add(auth: Authentication, @PathVariable productId: Long) =
        mapOf("message" to "좋아요 등록 성공", "data" to service.add(auth.owner(), productId))
    @DeleteMapping("/{productId}") fun remove(auth: Authentication, @PathVariable productId: Long) =
        mapOf("message" to "좋아요 해제 성공", "data" to service.remove(auth.owner(), productId))
    private fun Authentication.owner() = principal.toString().toLong()
}
