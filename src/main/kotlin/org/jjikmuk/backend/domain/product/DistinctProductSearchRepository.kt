package org.jjikmuk.backend.domain.product

import org.jjikmuk.backend.domain.allergy.FoodAllergy
import org.jjikmuk.backend.domain.product.search.ProductSearchKeywordBuilder
import org.springframework.beans.factory.annotation.Value
import org.springframework.data.domain.Page
import org.springframework.data.domain.PageImpl
import org.springframework.data.domain.Pageable
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Repository

/**
 * Returns one representative product for cards that show the same information.
 * Hidden fields such as barcode, nutrients, source and report number intentionally
 * do not participate in the display identity.
 */
@Repository
class DistinctProductSearchRepository(
    private val jdbcTemplate: JdbcTemplate,
    private val productRepository: ProductRepository,
    @Value("\${product.search.mode:locate}") configuredSearchMode: String,
    @Value("\${product.grouping.mode:legacy}") configuredGroupingMode: String
) {
    private val searchMode = ProductSearchMode.from(configuredSearchMode)
    private val groupingMode = ProductGroupingMode.from(configuredGroupingMode)
    private val displayGroupExpressions = when (groupingMode) {
        ProductGroupingMode.LEGACY -> LEGACY_DISPLAY_GROUP_EXPRESSIONS
        ProductGroupingMode.KEY -> PRODUCT_GROUP_KEY_EXPRESSION
    }
    private val displayOrderExpressions = when (groupingMode) {
        ProductGroupingMode.LEGACY -> LEGACY_DISPLAY_ORDER_EXPRESSIONS
        ProductGroupingMode.KEY -> GROUP_KEY_DISPLAY_ORDER_EXPRESSIONS
    }

    fun searchByProductName(keyword: String, limit: Int): List<Product> {
        val keywordSearch = createKeywordSearch(keyword) ?: return emptyList()
        val whereClause = "WHERE ${keywordSearch.conditionSql}"
        val barcodes = findRepresentativeBarcodes(
            whereClause = whereClause,
            parameters = keywordSearch.conditionParameters,
            limit = limit,
            offset = 0L,
            score = keywordSearch.score
        )
        return findProductsInOrder(barcodes)
    }

    fun activeSearchMode(): String = searchMode.name.lowercase()

    fun searchByFilters(
        filters: Set<ProductFilter>,
        matchMode: ProductFilterMatchMode,
        categories: Set<ProductFoodCategory>,
        categoryMatchMode: ProductFilterMatchMode,
        allergens: Set<FoodAllergy>,
        allergenMatchMode: ProductFilterMatchMode,
        keyword: String?,
        pageable: Pageable
    ): Page<Product> {
        val conditions = mutableListOf<String>()
        val parameters = mutableListOf<Any>()

        if (filters.isNotEmpty()) {
            val filterConditions = filters.map { filter -> "${filter.databaseColumn} = TRUE" }
            val filterJoiner = when (matchMode) {
                ProductFilterMatchMode.ALL -> " AND "
                ProductFilterMatchMode.ANY -> " OR "
            }
            conditions.add("(${filterConditions.joinToString(filterJoiner)})")
        }
        addStoredTokenConditions(
            conditions = conditions,
            parameters = parameters,
            membershipTable = "product_food_category_memberships",
            membershipColumn = "category_id",
            values = categories.map(ProductFoodCategory::id),
            matchMode = categoryMatchMode
        )
        addStoredTokenConditions(
            conditions = conditions,
            parameters = parameters,
            membershipTable = "product_allergy_classification_memberships",
            membershipColumn = "allergy_id",
            values = allergens.map(FoodAllergy::id),
            matchMode = allergenMatchMode
        )

        val keywordSearch = keyword?.let(::createKeywordSearch)
        if (keyword != null && keywordSearch == null) return Page.empty(pageable)
        keywordSearch?.let {
            conditions.add(it.conditionSql)
            parameters.addAll(it.conditionParameters)
        }

        val whereClause = if (conditions.isEmpty()) {
            ""
        } else {
            "WHERE ${conditions.joinToString(" AND ")}"
        }
        val totalElements = countDistinctProducts(whereClause, parameters)
        if (totalElements == 0L) return Page.empty(pageable)

        val barcodes = findRepresentativeBarcodes(
            whereClause = whereClause,
            parameters = parameters,
            limit = pageable.pageSize,
            offset = pageable.offset,
            score = keywordSearch?.score
        )
        val products = findProductsInOrder(barcodes)
        return PageImpl(products, pageable, totalElements)
    }

    private fun addStoredTokenConditions(
        conditions: MutableList<String>,
        parameters: MutableList<Any>,
        membershipTable: String,
        membershipColumn: String,
        values: List<String>,
        matchMode: ProductFilterMatchMode
    ) {
        if (values.isEmpty()) return
        require(CLASSIFICATION_MEMBERSHIPS[membershipTable] == membershipColumn) {
            "Unsupported classification membership: $membershipTable.$membershipColumn"
        }
        val tokenConditions = values.map {
            "EXISTS (SELECT 1 FROM $membershipTable membership " +
                "WHERE membership.barcode = products.barcode AND membership.$membershipColumn = ?)"
        }
        val joiner = when (matchMode) {
            ProductFilterMatchMode.ALL -> " AND "
            ProductFilterMatchMode.ANY -> " OR "
        }
        conditions.add("(${tokenConditions.joinToString(joiner)})")
        parameters.addAll(values)
    }

    private fun createKeywordSearch(keyword: String): KeywordSearch? {
        val trimmedKeyword = keyword.trim()
        if (trimmedKeyword.isEmpty()) return null

        return when (searchMode) {
            ProductSearchMode.LOCATE -> {
                val normalizedQuery = ProductSearchKeywordBuilder.normalizeQuery(trimmedKeyword)
                if (normalizedQuery.isEmpty()) return null

                KeywordSearch(
                    conditionSql = LOCATE_KEYWORD_CONDITION,
                    conditionParameters = List(3) { normalizedQuery },
                    score = SearchScore(
                        sql = LOCATE_SCORE,
                        parameters = List(5) { normalizedQuery }
                    )
                )
            }

            ProductSearchMode.FULLTEXT -> {
                val normalizedQuery = ProductSearchKeywordBuilder.normalizeQuery(trimmedKeyword)
                if (normalizedQuery.isEmpty()) return null
                val booleanPhrase = ProductSearchKeywordBuilder.toBooleanPhrase(normalizedQuery)

                KeywordSearch(
                    conditionSql = FULLTEXT_KEYWORD_CONDITION,
                    conditionParameters = listOf(booleanPhrase),
                    score = SearchScore(
                        sql = FULLTEXT_SCORE,
                        parameters = listOf(
                            normalizedQuery,
                            normalizedQuery,
                            normalizedQuery,
                            normalizedQuery
                        )
                    )
                )
            }
        }
    }

    private fun findRepresentativeBarcodes(
        whereClause: String,
        parameters: List<Any>,
        limit: Int,
        offset: Long,
        score: SearchScore? = null
    ): List<String> {
        val scoreSelection = score?.let { ", MAX(${it.sql}) AS search_score" }.orEmpty()
        val orderBy = if (score == null) {
            "$displayOrderExpressions, MIN(barcode)"
        } else {
            "search_score DESC, $displayOrderExpressions, MIN(barcode)"
        }
        val sql = """
            SELECT MIN(barcode) AS barcode$scoreSelection
            FROM products
            $whereClause
            GROUP BY $displayGroupExpressions
            ORDER BY $orderBy
            LIMIT ? OFFSET ?
        """.trimIndent()
        val orderedParameters = score?.parameters.orEmpty() + parameters + limit + offset

        return jdbcTemplate.query(
            sql,
            { resultSet, _ -> resultSet.getString("barcode") },
            *orderedParameters.toTypedArray()
        )
    }

    private fun countDistinctProducts(whereClause: String, parameters: List<Any>): Long {
        val sql = """
            SELECT COUNT(*)
            FROM (
                SELECT 1
                FROM products
                $whereClause
                GROUP BY $displayGroupExpressions
            ) distinct_products
        """.trimIndent()

        return jdbcTemplate.queryForObject(sql, Long::class.java, *parameters.toTypedArray()) ?: 0L
    }

    private fun findProductsInOrder(barcodes: List<String>): List<Product> {
        if (barcodes.isEmpty()) return emptyList()
        val productsByBarcode = productRepository.findAllById(barcodes).associateBy(Product::barcode)
        return barcodes.mapNotNull(productsByBarcode::get)
    }

    private data class KeywordSearch(
        val conditionSql: String,
        val conditionParameters: List<Any>,
        val score: SearchScore? = null
    )

    private data class SearchScore(
        val sql: String,
        val parameters: List<Any>
    )

    internal enum class ProductSearchMode {
        LOCATE,
        FULLTEXT;

        companion object {
            fun from(value: String): ProductSearchMode = entries.firstOrNull {
                it.name.equals(value.trim(), ignoreCase = true)
            } ?: error("product.search.mode must be locate or fulltext: $value")
        }
    }

    private enum class ProductGroupingMode {
        LEGACY,
        KEY;

        companion object {
            fun from(value: String): ProductGroupingMode = entries.firstOrNull {
                it.name.equals(value.trim(), ignoreCase = true)
            } ?: error("product.grouping.mode must be legacy or key: $value")
        }
    }

    private companion object {
        const val NORMALIZED_PRODUCT_NAME = "LOWER(TRIM(COALESCE(product_name, '')))"
        const val NORMALIZED_MANUFACTURER = "LOWER(TRIM(COALESCE(manufacturer, '')))"
        const val NORMALIZED_RAW_MATERIALS =
            "REPLACE(LOWER(TRIM(COALESCE(raw_materials, ''))), ' ', '')"
        const val NORMALIZED_IMAGE_URL = "TRIM(COALESCE(image_url, ''))"
        const val COMPACT_PRODUCT_NAME =
            "REGEXP_REPLACE(LOWER(COALESCE(product_name, '')), '[^0-9a-z가-힣]+', '')"
        const val COMPACT_CLEAN_PRODUCT_NAME =
            "REGEXP_REPLACE(LOWER(COALESCE(clean_product_name, '')), '[^0-9a-z가-힣]+', '')"
        const val COMPACT_MANUFACTURER =
            "REGEXP_REPLACE(LOWER(COALESCE(manufacturer, '')), '[^0-9a-z가-힣]+', '')"

        const val LOCATE_KEYWORD_CONDITION =
            "(LOCATE(?, $COMPACT_PRODUCT_NAME) > 0 OR " +
                "LOCATE(?, $COMPACT_CLEAN_PRODUCT_NAME) > 0 OR " +
                "LOCATE(?, $COMPACT_MANUFACTURER) > 0)"
        const val LOCATE_SCORE =
            "CASE WHEN $COMPACT_CLEAN_PRODUCT_NAME = ? THEN 120.0 ELSE 0.0 END + " +
                "CASE WHEN $COMPACT_PRODUCT_NAME = ? THEN 100.0 ELSE 0.0 END + " +
                "CASE WHEN $COMPACT_PRODUCT_NAME LIKE CONCAT(?, '%') THEN 40.0 ELSE 0.0 END + " +
                "CASE WHEN LOCATE(?, $COMPACT_PRODUCT_NAME) > 0 THEN 20.0 ELSE 0.0 END + " +
                "CASE WHEN $COMPACT_MANUFACTURER = ? THEN 10.0 ELSE 0.0 END"
        const val FULLTEXT_KEYWORD_CONDITION =
            "MATCH(search_keywords) AGAINST (? IN BOOLEAN MODE) > 0"
        const val FULLTEXT_SCORE =
            "MATCH(search_keywords) AGAINST (? IN NATURAL LANGUAGE MODE) + " +
                "CASE WHEN $COMPACT_CLEAN_PRODUCT_NAME = ? THEN 100.0 ELSE 0.0 END + " +
                "CASE WHEN $COMPACT_PRODUCT_NAME = ? THEN 80.0 ELSE 0.0 END + " +
                "CASE WHEN LOCATE(?, $COMPACT_PRODUCT_NAME) > 0 THEN 20.0 ELSE 0.0 END"

        const val LEGACY_DISPLAY_GROUP_EXPRESSIONS =
            "$NORMALIZED_PRODUCT_NAME, $NORMALIZED_MANUFACTURER, " +
                "$NORMALIZED_RAW_MATERIALS, $NORMALIZED_IMAGE_URL"
        const val PRODUCT_GROUP_KEY_EXPRESSION =
            "COALESCE(product_group_key, CONCAT('UNGROUPED:', barcode))"

        const val LEGACY_DISPLAY_ORDER_EXPRESSIONS =
            "$NORMALIZED_PRODUCT_NAME, $NORMALIZED_MANUFACTURER, " +
                "$NORMALIZED_RAW_MATERIALS, $NORMALIZED_IMAGE_URL"
        const val GROUP_KEY_DISPLAY_ORDER_EXPRESSIONS =
            "MIN($NORMALIZED_PRODUCT_NAME), MIN($NORMALIZED_MANUFACTURER), " +
                "MIN($NORMALIZED_RAW_MATERIALS), MIN($NORMALIZED_IMAGE_URL)"
        val CLASSIFICATION_MEMBERSHIPS = mapOf(
            "product_food_category_memberships" to "category_id",
            "product_allergy_classification_memberships" to "allergy_id"
        )
    }
}
