package org.jjikmuk.backend.domain.chat

import org.junit.jupiter.api.Test
import java.sql.DriverManager
import java.sql.SQLException
import java.util.UUID
import kotlin.test.*

class ChatMigrationTest {
    @Test fun `V18 creates owner scoped keys and cascades account and room deletion in MySQL compatibility mode`() {
        DriverManager.getConnection("jdbc:h2:mem:chat-migration-${UUID.randomUUID()};MODE=MySQL;DATABASE_TO_UPPER=false", "sa", "").use { c ->
            c.createStatement().use { s ->
                s.execute("CREATE TABLE users (id BIGINT PRIMARY KEY)")
                s.execute("INSERT INTO users VALUES (1),(2)")
                val sql = javaClass.getResource("/db/migration/V18__add_account_chat_conversations.sql")!!.readText()
                    .lineSequence().filterNot { it.trimStart().startsWith("--") }.joinToString("\n")
                sql.split(';').filter { it.isNotBlank() }.forEach { s.execute(it) }
                val key = UUID.randomUUID()
                s.execute("INSERT INTO chat_conversations(owner_id,client_conversation_id,title,created_at,updated_at) VALUES (1,'$key','가족 대화 👨',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),(2,'$key','B',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
                assertFailsWith<SQLException> { s.execute("INSERT INTO chat_conversations(owner_id,client_conversation_id,title,created_at,updated_at) VALUES (1,'$key','duplicate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)") }
                for (room in 1..2) s.execute("INSERT INTO chat_turns(conversation_id,client_message_id,request_hash,context_hash,message,status,created_at,expires_at) VALUES ($room,'$key','hash','context','질문','PENDING',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
                s.execute("DELETE FROM users WHERE id=1")
                s.executeQuery("SELECT COUNT(*) FROM chat_conversations").use { it.next(); assertEquals(1,it.getInt(1)) }
                s.executeQuery("SELECT COUNT(*) FROM chat_turns").use { it.next(); assertEquals(1,it.getInt(1)) }
                s.execute("DELETE FROM chat_conversations WHERE owner_id=2")
                s.executeQuery("SELECT COUNT(*) FROM chat_turns").use { it.next(); assertEquals(0,it.getInt(1)) }
            }
        }
    }
}
