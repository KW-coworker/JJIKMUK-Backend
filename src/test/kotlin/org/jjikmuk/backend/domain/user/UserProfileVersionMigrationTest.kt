package org.jjikmuk.backend.domain.user

import org.junit.jupiter.api.Test
import java.sql.DriverManager
import java.sql.SQLException
import java.util.UUID
import kotlin.test.*

class UserProfileVersionMigrationTest {
    @Test fun `V19 preserves existing users defaults both old and new rows and rejects null revisions`() {
        DriverManager.getConnection("jdbc:h2:mem:profile-migration-${UUID.randomUUID()};MODE=MySQL;DATABASE_TO_UPPER=false", "sa", "").use { c ->
            c.createStatement().use { s ->
                s.execute("CREATE TABLE users(id BIGINT PRIMARY KEY, nickname VARCHAR(20), allergies VARCHAR(1000))")
                s.execute("INSERT INTO users VALUES(1,'테스트','milk')")
                val sql = javaClass.getResource("/db/migration/V19__add_user_profile_version.sql")!!.readText()
                    .lineSequence().filterNot { it.trimStart().startsWith("--") }.joinToString("\n")
                sql.split(';').filter { it.isNotBlank() }.forEach { s.execute(it) }
                s.executeQuery("SELECT nickname,allergies,profile_version FROM users WHERE id=1").use {
                    assertTrue(it.next()); assertEquals("테스트", it.getString(1)); assertEquals("milk", it.getString(2)); assertEquals(0, it.getLong(3))
                }
                s.execute("INSERT INTO users(id,nickname) VALUES(2,'신규')")
                s.executeQuery("SELECT profile_version FROM users WHERE id=2").use { assertTrue(it.next()); assertEquals(0, it.getLong(1)) }
                assertFailsWith<SQLException> { s.execute("UPDATE users SET profile_version=NULL WHERE id=1") }
            }
        }
    }
}
