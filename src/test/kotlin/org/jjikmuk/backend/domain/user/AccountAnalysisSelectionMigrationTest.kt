package org.jjikmuk.backend.domain.user

import org.junit.jupiter.api.Test
import java.sql.DriverManager
import java.sql.SQLException
import java.util.UUID
import kotlin.test.*

class AccountAnalysisSelectionMigrationTest {
    @Test fun `V20 imports nothing and enforces account family references uniqueness and deletion cleanup`() {
        DriverManager.getConnection("jdbc:h2:mem:selection-migration-${UUID.randomUUID()};MODE=MySQL;DATABASE_TO_UPPER=false", "sa", "").use { c ->
            c.createStatement().use { s ->
                s.execute("CREATE TABLE users(id BIGINT PRIMARY KEY)")
                s.execute("CREATE TABLE family_profiles(id BIGINT PRIMARY KEY,owner_id BIGINT,nickname VARCHAR(20))")
                s.execute("INSERT INTO users VALUES(1),(2)")
                s.execute("INSERT INTO family_profiles VALUES(11,1,'가족1'),(22,2,'가족2')")
                val sql = javaClass.getResource("/db/migration/V20__add_account_analysis_selection.sql")!!.readText()
                    .lineSequence().filterNot { it.trimStart().startsWith("--") }.joinToString("\n")
                sql.split(';').filter { it.isNotBlank() }.forEach { s.execute(it) }
                s.executeQuery("SELECT COUNT(*) FROM account_analysis_selections").use { it.next(); assertEquals(0, it.getInt(1)) }
                s.executeQuery("SELECT COUNT(*) FROM family_profiles").use { it.next(); assertEquals(2, it.getInt(1)) }
                assertFailsWith<SQLException> { s.execute("INSERT INTO account_analysis_selections(owner_id) VALUES(99)") }
                s.execute("INSERT INTO account_analysis_selections(owner_id) VALUES(1),(2)")
                s.execute("INSERT INTO account_analysis_selection_families VALUES(1,11),(2,22)")
                assertFailsWith<SQLException> { s.execute("INSERT INTO account_analysis_selection_families VALUES(1,11)") }
                assertFailsWith<SQLException> { s.execute("INSERT INTO account_analysis_selection_families VALUES(1,99)") }
                s.execute("DELETE FROM family_profiles WHERE id=11")
                s.executeQuery("SELECT COUNT(*) FROM account_analysis_selection_families").use { it.next(); assertEquals(1, it.getInt(1)) }
                s.execute("DELETE FROM users WHERE id=2")
                s.executeQuery("SELECT COUNT(*) FROM account_analysis_selection_families").use { it.next(); assertEquals(0, it.getInt(1)) }
                s.executeQuery("SELECT COUNT(*) FROM account_analysis_selections").use { it.next(); assertEquals(1, it.getInt(1)) }
            }
        }
    }
}
