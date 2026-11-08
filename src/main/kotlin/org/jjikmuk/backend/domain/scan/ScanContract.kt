package org.jjikmuk.backend.domain.scan

import tools.jackson.databind.JsonNode
import com.fasterxml.jackson.annotation.JsonInclude
import java.util.UUID

class ScanFailure(val status: Int, val code: String) : RuntimeException(code)
data class ScanCandidate(val productId: Long, val barcode: String, val sourceProductName: String, val sourceManufacturer: String?)
data class ScanCandidates(val scanId: String, val catalogVersion: String, val status: String, val method: String,
                          val gptUsed: Boolean, val candidates: List<ScanCandidate>)
@JsonInclude(JsonInclude.Include.ALWAYS)
data class ScanProduct(val productId: Long, val barcode: String, val productName: String,
                       val manufacturer: String?, val imageUrl: String?, val allergy: String?)
@JsonInclude(JsonInclude.Include.ALWAYS)
data class ScanItem(val product: ScanProduct, val analysis: Nothing? = null)
data class ScanData(val schemaVersion: String = "scan-list-v1", val scanId: String, val requestId: String,
                    val catalogVersion: String, val status: String, val method: String, val gptUsed: Boolean,
                    val dbAbsenceConfirmed: Boolean = false, val products: List<ScanItem>)
data class ScanResponse(val message: String = "상품 스캔 결과", val data: ScanData)

internal fun validScanId(value: String): Boolean = runCatching {
    val id = UUID.fromString(value)
    id.version() == 4 && id.variant() == 2 && id.toString() == value
}.getOrDefault(false)

internal fun parseCandidates(root: JsonNode, scanId: String, requestId: String, version: String): ScanCandidates {
    try {
        require(root.isObject && root["schemaVersion"]?.stringValue() == "scan-candidates-v1")
        require(root["scanId"]?.stringValue() == scanId && root["requestId"]?.stringValue() == requestId)
        require(root["catalogVersion"]?.stringValue() == version)
        require(root["dbAbsenceConfirmed"]?.isBoolean == true && !root["dbAbsenceConfirmed"].booleanValue())
        val status = root["status"]?.stringValue()
        val method = root["method"]?.stringValue()
        require(status in setOf("MATCHES_FOUND", "MANUAL_SEARCH_REQUIRED"))
        require(method in setOf("LOCAL_OCR_MATCHING", "IMAGE_GPT_MATCHING"))
        require(root["gptUsed"]?.isBoolean == true)
        val used = root["gptUsed"].booleanValue()
        require(used == (method == "IMAGE_GPT_MATCHING"))
        val rows = root["candidates"]
        require(rows?.isArray == true && rows.size() <= 50)
        require((status == "MATCHES_FOUND") == (rows.size() > 0))
        fun text(row: JsonNode, key: String, limit: Int): String {
            require(row[key]?.isString == true)
            return row[key].stringValue().also { require(it.isNotBlank() && it.length <= limit) }
        }
        val candidates = (0 until rows.size()).map { index ->
            val row = rows[index]
            require(row.isObject && row["productId"]?.isIntegralNumber == true && row["productId"].canConvertToLong())
            val id = row["productId"].longValue().also { require(it > 0) }
            val maker = row["sourceManufacturer"]
            require(maker != null && (maker.isNull || (maker.isString && maker.stringValue().length <= 1000)))
            ScanCandidate(id, text(row, "barcode", 255), text(row, "sourceProductName", 1000),
                if (maker.isNull) null else maker.stringValue())
        }
        require(candidates.map { it.productId }.toSet().size == candidates.size)
        require(candidates.map { it.barcode }.toSet().size == candidates.size)
        return ScanCandidates(scanId, version, status!!, method!!, used, candidates)
    } catch (_: Exception) { throw ScanFailure(502, "SCAN_UPSTREAM_INVALID_RESPONSE") }
}
