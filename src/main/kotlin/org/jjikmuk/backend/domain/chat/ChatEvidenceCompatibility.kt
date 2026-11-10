package org.jjikmuk.backend.domain.chat

import org.jjikmuk.backend.domain.chat.dto.AiChatRequestDto
import org.jjikmuk.backend.domain.product.AllergyEvidenceLevel

/** chat-analysis-v2 has five evidence labels. Preserve the DB label elsewhere. */
internal object ChatEvidenceCompatibility {
    fun forV2(request: AiChatRequestDto): AiChatRequestDto {
        val context = request.analysisContext
        fun analysis(value: Map<String, Any>?): Map<String, Any>? =
            if (value?.get("evidenceLevel") == AllergyEvidenceLevel.SOURCE_INGREDIENTS.name)
                value + ("evidenceLevel" to AllergyEvidenceLevel.UNKNOWN.name)
            else value
        return request.copy(analysisContext = context.copy(
            analysis = analysis(context.analysis),
            profileAnalyses = context.profileAnalyses.map { it.copy(analysis = analysis(it.analysis)) },
            dataEvidence = context.dataEvidence?.let {
                if (it.allergyEvidenceLevel == AllergyEvidenceLevel.SOURCE_INGREDIENTS)
                    it.copy(allergyEvidenceLevel = AllergyEvidenceLevel.UNKNOWN)
                else it
            }
        ))
    }
}
