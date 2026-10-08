package org.jjikmuk.backend.domain.user

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class UserPreferenceCatalogTest {
    @Test
    fun `normalizes one vegetarian type and multiple nutrition preferences`() {
        assertEquals(
            "lactoOvoVegetarian,lowSugar,highProtein",
            DietPreferenceCatalog.normalizeForStorage("고단백 | 락토 오보, low_sugar, 고단백")
        )
    }

    @Test
    fun `rejects conflicting vegetarian types and unknown IDs`() {
        assertFailsWith<IllegalArgumentException> {
            DietPreferenceCatalog.normalizeForStorage("vegan,pescatarian")
        }
        assertFailsWith<IllegalArgumentException> {
            DietPreferenceCatalog.normalizeForStorage("lowSugar,unknown-diet")
        }
    }

    @Test
    fun `empty values clear the profile and free text lists are canonicalized`() {
        assertEquals(null, DietPreferenceCatalog.normalizeForStorage("  "))
        assertEquals(
            "고수,땅콩버터",
            DelimitedProfileNormalizer.normalizeForStorage(" 고수, 땅콩버터, 고수 ", "기피 식재료")
        )
    }
}
