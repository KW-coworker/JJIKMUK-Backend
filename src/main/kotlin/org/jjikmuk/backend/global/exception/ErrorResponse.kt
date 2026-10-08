package org.jjikmuk.backend.global.exception

import com.fasterxml.jackson.annotation.JsonInclude

@JsonInclude(JsonInclude.Include.NON_NULL)
data class ErrorResponse(
    val status: Int,
    val code: String,
    val message: String,
    val field: String? = null
)
