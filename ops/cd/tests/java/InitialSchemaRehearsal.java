import java.nio.file.Path;
import java.sql.DriverManager;
import org.flywaydb.core.Flyway;

/** Disposable localhost MySQL only, synthetic rows. Never accepts a server URL. */
public final class InitialSchemaRehearsal {
    public static void main(String[] args) throws Exception {
        String url = "jdbc:mysql://127.0.0.1:3306/jjikmuk?sslMode=DISABLED&allowPublicKeyRetrieval=true";
        try (var c = DriverManager.getConnection(url, "root", "rehearsal_only"); var s = c.createStatement()) {
            s.execute("CREATE TABLE products (id BIGINT PRIMARY KEY, note VARCHAR(20)) ENGINE=InnoDB");
            s.execute("CREATE TABLE products_rollback LIKE products");
            s.execute("CREATE TABLE users (id BIGINT PRIMARY KEY, note VARCHAR(20)) ENGINE=InnoDB");
            s.execute("CREATE TABLE family_profiles (id BIGINT PRIMARY KEY, note VARCHAR(20)) ENGINE=InnoDB");
            for (String table : new String[]{"products", "products_rollback", "users", "family_profiles"})
                s.execute("INSERT INTO " + table + " VALUES(1,'preserve-existing')");
        }
        // Only this disposable test database uses a synthetic baseline at 16.
        // Production preflight requires the real V1-V16 SQL history and baseline 0.
        Flyway.configure().dataSource(url, "root", "rehearsal_only").baselineVersion("16")
            .loggers("console").load().baseline();
        var flyway = InitialSchema.configured(Path.of(args[0]), url, "root", "rehearsal_only");
        InitialSchema.apply(flyway);
        try (var c = DriverManager.getConnection(url, "root", "rehearsal_only"); var s = c.createStatement()) {
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
        System.out.println("MYSQL_V17_V20_PRESERVATION_AND_NO_REPLAY_PASSED");
    }
}
