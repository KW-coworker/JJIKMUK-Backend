package org.jjikmuk.backend.domain.product

enum class ProductFilter(
    val key: String,
    val label: String,
    val description: String,
    val entityField: String,
    val databaseColumn: String,
    private val aliases: Set<String> = emptySet()
) {
    VEGAN(
        key = "vegan",
        label = "비건",
        description = "오직 식물성 음식만 섭취해요",
        entityField = "vegan",
        databaseColumn = "is_vegan"
    ),
    LACTO_VEGETARIAN(
        key = "lactoVegetarian",
        label = "락토",
        description = "식물성 음식과 유제품을 섭취해요",
        entityField = "lactoVegetarian",
        databaseColumn = "is_lacto_vegetarian",
        aliases = setOf("lacto")
    ),
    OVO_VEGETARIAN(
        key = "ovoVegetarian",
        label = "오보",
        description = "식물성 음식과 계란을 섭취해요",
        entityField = "ovoVegetarian",
        databaseColumn = "is_ovo_vegetarian",
        aliases = setOf("ovo")
    ),
    LACTO_OVO_VEGETARIAN(
        key = "lactoOvoVegetarian",
        label = "락토 오보",
        description = "식물성 음식, 유제품, 계란을 섭취해요",
        entityField = "lactoOvoVegetarian",
        databaseColumn = "is_lacto_ovo_vegetarian",
        aliases = setOf("lactoOvo", "락토오보")
    ),
    PESCATARIAN(
        key = "pescatarian",
        label = "페스코",
        description = "채식에 해산물까지 섭취해요",
        entityField = "pescatarian",
        databaseColumn = "is_pescatarian",
        aliases = setOf("pesco")
    ),
    POLLOTARIAN(
        key = "pollotarian",
        label = "폴로",
        description = "채식, 해산물, 가금류까지 섭취해요",
        entityField = "pollotarian",
        databaseColumn = "is_pollotarian",
        aliases = setOf("pollo")
    ),
    LOW_SUGAR(
        key = "lowSugar",
        label = "저당",
        description = "당류 섭취 제한",
        entityField = "lowSugar",
        databaseColumn = "is_low_sugar"
    ),
    LOW_SODIUM(
        key = "lowSodium",
        label = "저염",
        description = "나트륨 섭취 제한",
        entityField = "lowSodium",
        databaseColumn = "is_low_sodium"
    ),
    GLUTEN_FREE(
        key = "glutenFree",
        label = "글루텐프리",
        description = "밀단백질 제외",
        entityField = "glutenFree",
        databaseColumn = "is_gluten_free",
        aliases = setOf("gluten-free")
    ),
    LOW_CALORIE(
        key = "lowCalorie",
        label = "저칼로리",
        description = "다이어트 체중조절",
        entityField = "lowCalorie",
        databaseColumn = "is_low_calorie"
    ),
    LOW_FAT(
        key = "lowFat",
        label = "저지방",
        description = "지방 섭취 제한",
        entityField = "lowFat",
        databaseColumn = "is_low_fat"
    ),
    HIGH_PROTEIN(
        key = "highProtein",
        label = "고단백",
        description = "단백질 위주 식단",
        entityField = "highProtein",
        databaseColumn = "is_high_protein"
    );

    private val acceptedKeys: Set<String> =
        (aliases.toList() + key + label).map(::normalizeFilterKey).toSet()

    fun toMetadata(): Map<String, String> = mapOf(
        "key" to key,
        "label" to label,
        "description" to description
    )

    fun matches(product: Product): Boolean = when (this) {
        VEGAN -> product.vegan
        LACTO_VEGETARIAN -> product.lactoVegetarian
        OVO_VEGETARIAN -> product.ovoVegetarian
        LACTO_OVO_VEGETARIAN -> product.lactoOvoVegetarian
        PESCATARIAN -> product.pescatarian
        POLLOTARIAN -> product.pollotarian
        LOW_SUGAR -> product.lowSugar
        LOW_SODIUM -> product.lowSodium
        GLUTEN_FREE -> product.glutenFree
        LOW_CALORIE -> product.lowCalorie
        LOW_FAT -> product.lowFat
        HIGH_PROTEIN -> product.highProtein
    }

    companion object {
        fun fromRequest(value: String): ProductFilter? {
            val normalized = normalizeFilterKey(value)
            return entries.firstOrNull { normalized in it.acceptedKeys }
        }

        fun supportedKeys(): List<String> = entries.map { it.key }

        fun detectInText(value: String?): Set<ProductFilter> {
            if (value.isNullOrBlank()) return emptySet()
            val normalized = normalizeFilterKey(value)
            val detected = entries.filterTo(linkedSetOf()) { filter ->
                filter.acceptedKeys.any { key -> key.length >= 2 && normalized.contains(key) }
            }
            if (LACTO_OVO_VEGETARIAN in detected) {
                detected.remove(LACTO_VEGETARIAN)
                detected.remove(OVO_VEGETARIAN)
            }
            return detected
        }
    }
}

enum class ProductFilterMatchMode {
    ALL,
    ANY;

    val responseValue: String
        get() = name.lowercase()

    companion object {
        fun fromRequest(value: String): ProductFilterMatchMode? = when (value.trim().lowercase()) {
            "all", "and", "모두" -> ALL
            "any", "or", "하나이상" -> ANY
            else -> null
        }
    }
}

private fun normalizeFilterKey(value: String): String =
    value.trim()
        .lowercase()
        .filterNot { it.isWhitespace() || it == '_' || it == '-' }
