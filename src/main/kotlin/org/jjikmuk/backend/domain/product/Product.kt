package org.jjikmuk.backend.domain.product

import com.fasterxml.jackson.annotation.JsonIgnore
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.EnumType
import jakarta.persistence.Enumerated
import jakarta.persistence.Id
import jakarta.persistence.Table

@Entity
@Table(name = "products")
class Product(
    @Id
    @Column(name = "barcode", nullable = false)
    val barcode: String,

    @Column(name = "product_name", length = 1000)
    val productName: String? = null,

    @Column(name = "manufacturer", length = 1000)
    val manufacturer: String? = null,

    @Column(name = "report_no")
    val reportNo: String? = null,

    @Column(name = "allergy", columnDefinition = "TEXT")
    val allergy: String? = null,

    @Column(name = "nutrient_text", columnDefinition = "TEXT")
    val nutrientText: String? = null,

    @Column(name = "image_url", length = 2000)
    val imageUrl: String? = null,

    @Column(name = "source", length = 1000)
    val source: String? = null,

    @Column(name = "raw_materials", columnDefinition = "TEXT")
    val rawMaterials: String? = null,

    @Column(name = "energy_kcal")
    val energyKcal: Double? = null,

    @Column(name = "carbs_g")
    val carbsG: Double? = null,

    @Column(name = "protein_g")
    val proteinG: Double? = null,

    @Column(name = "fat_g")
    val fatG: Double? = null,

    @Column(name = "sugar_g")
    val sugarG: Double? = null,

    @Column(name = "sodium_mg")
    val sodiumMg: Double? = null,

    @Column(name = "cholesterol_mg")
    val cholesterolMg: Double? = null,

    @Column(name = "allergy_warning", columnDefinition = "TEXT")
    val allergyWarning: String? = null,

    @Column(name = "clean_product_name", length = 1000)
    val cleanProductName: String? = null,

    @Column(name = "total_weight")
    val totalWeight: String? = null,

    @Column(name = "food_type", length = 500)
    val foodType: String? = null,

    @Column(name = "carbs_percent")
    val carbsPercent: Double? = null,

    @Column(name = "protein_percent")
    val proteinPercent: Double? = null,

    @Column(name = "fat_percent")
    val fatPercent: Double? = null,

    @Column(name = "sodium_g")
    val sodiumG: Double? = null,

    @Column(name = "cholesterol_g")
    val cholesterolG: Double? = null,

    @Column(name = "is_vegan", nullable = false)
    val vegan: Boolean = false,

    @Column(name = "is_lacto_vegetarian", nullable = false)
    val lactoVegetarian: Boolean = false,

    @Column(name = "is_ovo_vegetarian", nullable = false)
    val ovoVegetarian: Boolean = false,

    @Column(name = "is_lacto_ovo_vegetarian", nullable = false)
    val lactoOvoVegetarian: Boolean = false,

    @Column(name = "is_pescatarian", nullable = false)
    val pescatarian: Boolean = false,

    @Column(name = "is_pollotarian", nullable = false)
    val pollotarian: Boolean = false,

    @Column(name = "is_low_sugar", nullable = false)
    val lowSugar: Boolean = false,

    @Column(name = "is_low_sodium", nullable = false)
    val lowSodium: Boolean = false,

    @Column(name = "is_gluten_free", nullable = false)
    val glutenFree: Boolean = false,

    @Column(name = "is_low_calorie", nullable = false)
    val lowCalorie: Boolean = false,

    @Column(name = "is_low_fat", nullable = false)
    val lowFat: Boolean = false,

    @Column(name = "is_high_protein", nullable = false)
    val highProtein: Boolean = false,

    @JsonIgnore
    @Column(name = "product_group_key", length = 64)
    val productGroupKey: String? = null,

    @JsonIgnore
    @Enumerated(EnumType.STRING)
    @Column(name = "allergy_evidence_level", nullable = false, length = 32)
    val allergyEvidenceLevel: AllergyEvidenceLevel = AllergyEvidenceLevel.UNKNOWN,

    @JsonIgnore
    @Column(name = "allergy_data_confidence")
    val allergyDataConfidence: Double? = null,

    @JsonIgnore
    @Enumerated(EnumType.STRING)
    @Column(name = "nutrition_data_origin", nullable = false, length = 32)
    val nutritionDataOrigin: ProductDataOrigin = ProductDataOrigin.UNKNOWN,

    @JsonIgnore
    @Column(name = "nutrition_data_confidence")
    val nutritionDataConfidence: Double? = null,

    @JsonIgnore
    @Enumerated(EnumType.STRING)
    @Column(name = "dietary_data_origin", nullable = false, length = 32)
    val dietaryDataOrigin: ProductDataOrigin = ProductDataOrigin.INFERRED,

    @JsonIgnore
    @Column(name = "dietary_data_confidence")
    val dietaryDataConfidence: Double? = null
) {
    init {
        allergyDataConfidence?.let { confidence ->
            require(confidence in 0.0..1.0) {
                "allergyDataConfidence must be between 0 and 1"
            }
        }
        nutritionDataConfidence?.let { confidence ->
            require(confidence in 0.0..1.0) {
                "nutritionDataConfidence must be between 0 and 1"
            }
        }
        dietaryDataConfidence?.let { confidence ->
            require(confidence in 0.0..1.0) {
                "dietaryDataConfidence must be between 0 and 1"
            }
        }
    }
}
