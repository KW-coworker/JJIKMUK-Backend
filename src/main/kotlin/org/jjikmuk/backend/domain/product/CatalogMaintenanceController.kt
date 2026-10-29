package org.jjikmuk.backend.domain.product

import org.springframework.data.domain.PageRequest
import org.springframework.web.bind.annotation.*
import org.springframework.security.core.Authentication
import org.springframework.http.HttpStatus
import org.jjikmuk.backend.global.exception.CustomException

data class AttributeCaptureRequest(val datasetVersion: String, val reason: String, val afterBarcode: String = "", val batchSize: Int = 200)

/** Network policy requires ADMIN; these writes are never exposed under public product routes. */
@RestController
@RequestMapping("/api/admin/catalog")
class CatalogMaintenanceController(private val evolution: CatalogEvolutionService, private val snapshots: ProductAttributeSnapshotRepository,
                                   private val products: ProductRepository) {
    @PostMapping("/ids/backfill")
    fun backfill(@RequestParam(defaultValue = "500") batchSize: Int): Map<String, Any> {
        validate(batchSize in 1..1000)
        return mapOf("data" to evolution.assignMissingIds(batchSize))
    }

    @PostMapping("/attributes/capture")
    fun capture(@RequestBody request: AttributeCaptureRequest, authentication: Authentication): Map<String, Any> {
        validate(request.batchSize in 1..1000 && request.afterBarcode.length <= 255 &&
            request.datasetVersion.isNotBlank() && request.datasetVersion.length <= 128 &&
            request.reason.isNotBlank() && request.reason.length <= 500)
        return mapOf("data" to evolution.captureAttributes(request.datasetVersion, request.reason,
            request.afterBarcode, request.batchSize, observedBy = "ADMIN:${authentication.name}"))
    }

    @GetMapping("/products/{productId}/attribute-history")
    fun history(@PathVariable productId: Long, @RequestParam(defaultValue = "0") page: Int,
                @RequestParam(defaultValue = "20") size: Int): Map<String, Any?> {
        validate(productId > 0 && page in 0..10000 && size in 1..100)
        return mapOf("data" to snapshots.findByProductIdOrderByIdDesc(productId, PageRequest.of(page, size)),
            "activeSnapshotId" to products.findByProductId(productId)?.attributeSnapshotId,
            "semantics" to "OBSERVATIONS_NOT_CONFIRMED_PHYSICAL_REVISIONS")
    }
    private fun validate(valid: Boolean) {
        if (!valid) throw CustomException(HttpStatus.BAD_REQUEST, "관리 작업의 입력 범위가 올바르지 않습니다.")
    }
}
