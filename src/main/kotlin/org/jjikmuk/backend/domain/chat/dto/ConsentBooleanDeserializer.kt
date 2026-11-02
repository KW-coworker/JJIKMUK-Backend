package org.jjikmuk.backend.domain.chat.dto

import tools.jackson.core.JsonParser
import tools.jackson.core.JsonToken
import tools.jackson.databind.DeserializationContext
import tools.jackson.databind.ValueDeserializer

/** Consent must be an explicit JSON boolean, never a coerced string or number. */
class ConsentBooleanDeserializer : ValueDeserializer<Boolean>() {
    override fun deserialize(parser: JsonParser, context: DeserializationContext): Boolean =
        when (parser.currentToken()) {
            JsonToken.VALUE_TRUE -> true
            JsonToken.VALUE_FALSE -> false
            else -> throw IllegalArgumentException("externalAiConsent must be a boolean")
        }

    override fun getNullValue(context: DeserializationContext): Boolean = false
}
