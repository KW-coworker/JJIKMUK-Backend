package org.jjikmuk.backend.domain.product

import kotlin.test.*

class ProductNutritionTest {
    @Test fun `Pocky 44g package uses 220kcal while retaining 500kcal per100g`() {
        val p = Product("8801019311673", energyKcal = 500.0, totalWeight = "44g", nutritionBasisRaw = "100g",
            carbsG = 70.45, proteinG = 6.82, fatG = 20.45, sugarG = 36.36, sodiumMg = 341.0, cholesterolMg = 6.82)
        assertEquals(500.0, p.energyKcal)
        assertEquals(500.0, p.nutrition.per100g!!.values.energyKcal)
        assertEquals(220.0, p.nutrition.perPackage!!.values.energyKcal)
        assertEquals(11L, p.nutrition.perPackage!!.dailyReferencePercents["energyPercent"])
        assertEquals(NutrientValues(220.0, 30.998, 3.0008, 8.998, 15.9984, 150.04, 3.0008),
            p.nutrition.perPackage!!.values)
        assertNull(p.nutrition.per100ml)
    }

    @Test fun `serving basis is not double scaled`() {
        val n = Product("1", energyKcal = 220.0, nutritionBasisRaw = "44g", totalWeight = "44g").nutrition
        assertEquals(220.0, n.perPackage!!.values.energyKcal)
        assertEquals(500.0, n.per100g!!.values.energyKcal)
    }

    @Test fun `liquid is per100ml not per100g without density`() {
        val n = Product("1", energyKcal = 80.0, nutritionBasisRaw = "200ml", totalWeight = "1L").nutrition
        assertEquals(40.0, n.per100ml!!.values.energyKcal)
        assertEquals(400.0, n.perPackage!!.values.energyKcal)
        assertNull(n.per100g)
        val mismatch = Product("2", energyKcal = 80.0, nutritionBasisRaw = "100g", totalWeight = "200ml").nutrition
        assertNull(mismatch.perPackage)
        assertEquals("UNIT_MISMATCH", mismatch.packageCalculationReason)
    }

    @Test fun `explicit multipack and kg conversion preserve whole package meaning`() {
        assertEquals(880.0, Product("1", energyKcal = 500.0, nutritionBasisRaw = "100g", totalWeight = "44g x 4봉").nutrition.perPackage!!.values.energyKcal)
        assertEquals(500.0, Product("1", energyKcal = 1000.0, nutritionBasisRaw = "1kg", totalWeight = "500g").nutrition.perPackage!!.values.energyKcal)
    }

    @Test fun `missing or ambiguous basis never defaults to 100g or raw label text`() {
        for (basis in listOf(null, "", "0g", "-100g", "1회", "100g/30g", "100g x 2", "총내용량당", "NaNg")) {
            val n = Product("1", energyKcal = 500.0, totalWeight = "44g", nutritionBasisRaw = basis,
                nutrientText = "1봉지 44g당 220kcal").nutrition
            assertEquals("UNKNOWN", n.sourceBasis.status, basis)
            assertNull(n.perPackage, basis)
            assertNull(n.per100g, basis)
        }
    }

    @Test fun `missing weight does not erase known per100 and missing nutrients do not become zero`() {
        val n = Product("1", nutritionBasisRaw = "100g", energyKcal = 0.0, sugarG = null, sodiumMg = -1.0).nutrition
        assertEquals("PACKAGE_QUANTITY_UNKNOWN", n.packageCalculationReason)
        assertEquals(0.0, n.per100g!!.values.energyKcal)
        assertNull(n.per100g!!.values.sugarG)
        assertNull(n.per100g!!.values.sodiumMg)
        assertNull(n.per100g!!.dailyReferencePercents["sugarPercent"])
    }
}
