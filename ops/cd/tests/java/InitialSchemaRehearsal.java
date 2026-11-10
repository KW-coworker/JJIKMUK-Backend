import java.nio.file.Path;
import java.sql.DriverManager;
import org.flywaydb.core.Flyway;

/** Disposable localhost MySQL only, synthetic rows. Never accepts a server URL. */
public final class InitialSchemaRehearsal {
    public static void main(String[] args) throws Exception {
        String url = "jdbc:mysql://127.0.0.1:3306/jjikmuk?sslMode=DISABLED&allowPublicKeyRetrieval=true";
        try (var c = DriverManager.getConnection(url, "root", "rehearsal_only"); var s = c.createStatement()) {
            s.execute("CREATE USER 'project_only'@'%' IDENTIFIED BY 'fixture_only'");
            s.execute("GRANT ALL PRIVILEGES ON jjikmuk.* TO 'project_only'@'%'");
            s.execute("CREATE TABLE products (id BIGINT PRIMARY KEY, note VARCHAR(20), search_keywords TEXT, FULLTEXT KEY ft_products_search_keywords(search_keywords) WITH PARSER ngram) ENGINE=InnoDB COMMENT='preserve-dataset-marker'");
            s.execute("CREATE TABLE products_rollback LIKE products");
            s.execute("ALTER TABLE products_rollback DROP INDEX ft_products_search_keywords");
            s.execute("OPTIMIZE TABLE products_rollback");
            s.execute("CREATE TABLE users (id BIGINT PRIMARY KEY, note VARCHAR(20)) ENGINE=InnoDB");
            s.execute("CREATE TABLE family_profiles (id BIGINT PRIMARY KEY, note VARCHAR(20)) ENGINE=InnoDB");
            for (String table : new String[]{"products", "products_rollback"})
                s.execute("INSERT INTO " + table + " VALUES(1,'preserve-existing','합성 우유 상품')");
            for (String table : new String[]{"users", "family_profiles"})
                s.execute("INSERT INTO " + table + " VALUES(1,'preserve-existing')");
            try (var r = s.executeQuery("SELECT VERSION()")) {
                r.next(); if (!r.getString(1).equals("8.4.11")) throw new IllegalStateException("production MySQL version required");
            }
            try (var r = s.executeQuery("SELECT id FROM products WHERE MATCH(search_keywords) AGAINST('우유' IN BOOLEAN MODE)")) {
                if (!r.next() || r.getLong(1) != 1 || r.next()) throw new IllegalStateException("original search fixture failed");
            }
        }
        // All maintenance DDL, Flyway and verification use schema-only grants.
        try (var c = DriverManager.getConnection(url, "project_only", "fixture_only"); var s = c.createStatement()) {
            s.execute("ALTER TABLE products DROP INDEX ft_products_search_keywords, ALGORITHM=INPLACE");
            try (var r = s.executeQuery("OPTIMIZE TABLE products")) {
                boolean ok = false;
                while (r.next()) {
                    if (r.getString(3).equals("error")) throw new IllegalStateException("rebuild failed");
                    if (r.getString(3).equals("status") && r.getString(4).equals("OK")) ok = true;
                }
                if (!ok) throw new IllegalStateException("rebuild status absent");
            }
        }
        // Only this disposable test database uses a synthetic baseline at 16.
        // Production preflight requires the real V1-V16 SQL history and baseline 0.
        Flyway.configure().dataSource(url, "project_only", "fixture_only").baselineVersion("16")
            .loggers("slf4j").load().baseline();
        var ownership=Path.of(args[0]).resolve("owned-connections");
        java.nio.file.Files.createFile(ownership);
        var flyway = InitialSchema.configured(Path.of(args[0]),
            new InitialSchema.TrackedSource(url,"project_only","fixture_only",ownership));
        InitialSchema.apply(flyway);
        var registered=java.nio.file.Files.readAllLines(ownership);
        if(registered.isEmpty() || registered.size()>32 ||
                registered.stream().anyMatch(x->!x.matches("[1-9][0-9]{0,18}")))
            throw new IllegalStateException("owned sessions were not registered");
        try (var c = DriverManager.getConnection(url, "project_only", "fixture_only"); var s = c.createStatement()) {
            s.execute("ALTER TABLE products ADD FULLTEXT INDEX ft_products_search_keywords(search_keywords) WITH PARSER ngram");
            try (var r = s.executeQuery("SELECT id FROM products WHERE MATCH(search_keywords) AGAINST('우유' IN BOOLEAN MODE)")) {
                if (!r.next() || r.getLong(1) != 1 || r.next()) throw new IllegalStateException("restored search changed");
            }
            try (var r = s.executeQuery("SELECT TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA='jjikmuk' AND TABLE_NAME='products'")) {
                if (!r.next() || !r.getString(1).equals("preserve-dataset-marker")) throw new IllegalStateException("dataset marker changed");
            }
            for (String table : new String[]{"products", "products_rollback", "users", "family_profiles"}) {
                try (var r = s.executeQuery("SELECT id,note FROM " + table)) {
                    if (!r.next() || r.getLong(1) != 1 || !r.getString(2).equals("preserve-existing") || r.next())
                        throw new IllegalStateException("existing row changed");
                }
            }
            try (var r = s.executeQuery("SELECT profile_version FROM users WHERE id=1")) {
                if (!r.next() || r.getLong(1) != 0) throw new IllegalStateException("default missing");
            }
            try (var r = s.executeQuery("SELECT nutrition_basis_raw FROM products WHERE id=1")) {
                if (!r.next() || r.getString(1) != null) throw new IllegalStateException("unexpected backfill");
            }
            for (String table : new String[]{"chat_conversations", "chat_turns", "account_analysis_selections", "account_analysis_selection_families"}) {
                try (var r = s.executeQuery("SELECT COUNT(*) FROM " + table)) {
                    r.next(); if (r.getLong(1) != 0) throw new IllegalStateException("unexpected new rows");
                }
            }
        }
        boolean rejected = false;
        try { InitialSchema.apply(flyway); } catch (IllegalStateException expected) { rejected = true; }
        if (!rejected) throw new IllegalStateException("repeat must stop");
        System.out.println("MYSQL_8_4_11_FULLTEXT_REBUILD_ORIGINAL_V17_V20_SEARCH_PRESERVATION_NO_REPLAY_PASSED");
    }
}
