import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.sql.SQLException;

/** Reproduce the unchanged first V17 statement against a disposable FULLTEXT table. */
public final class V17FulltextRehearsal {
    public static void main(String[] args) throws Exception {
        String url = "jdbc:mysql://127.0.0.1:3306/?sslMode=DISABLED&allowPublicKeyRetrieval=true";
        try (var c = DriverManager.getConnection(url, "root", "rehearsal_only"); var s = c.createStatement()) {
            s.execute("CREATE DATABASE v17_fulltext_rehearsal");
            s.execute("USE v17_fulltext_rehearsal");
            s.execute("CREATE TABLE products (id BIGINT PRIMARY KEY, search_keywords TEXT, FULLTEXT ft_products_search_keywords(search_keywords)) ENGINE=InnoDB");
            s.execute("INSERT INTO products VALUES(1,'preserve original product')");
            String sql = Files.readString(Path.of(args[0]));
            boolean refused = false;
            try { s.execute(sql.substring(0, sql.indexOf(';') + 1)); }
            catch (SQLException e) {
                if (!e.getMessage().toUpperCase().contains("FULLTEXT")) throw e;
                refused = true;
                System.out.println("V17_FULLTEXT_MYSQL_ERROR_CODE=" + e.getErrorCode());
            }
            if (!refused) throw new IllegalStateException("expected FULLTEXT incompatibility not reproduced");
            try (var r = s.executeQuery("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='v17_fulltext_rehearsal' AND TABLE_NAME='products' AND COLUMN_NAME='nutrition_basis_raw'")) {
                r.next(); if (r.getInt(1) != 0) throw new IllegalStateException("column unexpectedly added");
            }
            try (var r = s.executeQuery("SELECT id,search_keywords FROM products")) {
                if (!r.next() || r.getLong(1) != 1 || !r.getString(2).equals("preserve original product") || r.next())
                    throw new IllegalStateException("original row changed");
            }
            System.out.println("V17_FULLTEXT_CONFLICT_REPRODUCED_WITH_NO_COLUMN_CHANGE");
        }
    }
}
