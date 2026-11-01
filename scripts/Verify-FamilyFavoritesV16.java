// Run with the built application's BOOT-INF/classes + BOOT-INF/lib/* classpath (Java 21).
// Credentials are environment-only. This verifier rejects non-loopback servers.
// migrate: approved local V15 -> V16; verify: read-only; smoke: disposable clone ONLY.
import java.nio.file.*;
import java.sql.*;
import java.time.Duration;
import java.util.*;
import java.net.URI;
import java.net.http.*;
import org.flywaydb.core.Flyway;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.jjikmuk.backend.BackendApplication;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

class VerifyFamilyFavoritesV16 {
    static final JsonMapper JSON = JsonMapper.builder().findAndAddModules().build();
    static final List<String> checks = new ArrayList<>();
    static void check(boolean ok, String label) {
        if (!ok) throw new IllegalStateException("V16 check failed: " + label);
        checks.add(label);
    }
    static void save(String name, Object value) throws Exception {
        Files.writeString(Path.of(System.getenv("V16_OUTPUT")).resolve(name),
            JSON.writerWithDefaultPrettyPrinter().writeValueAsString(value), StandardOpenOption.CREATE_NEW);
    }
    static long count(Connection c, String query) throws Exception {
        try (var s = c.createStatement(); var r = s.executeQuery(query)) { r.next(); return r.getLong(1); }
    }
    static JsonNode request(HttpClient http, int port, String method, String path, String token, Object body, int expected) throws Exception {
        var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).timeout(Duration.ofSeconds(30));
        if (token != null) builder.header("Authorization", "Bearer " + token);
        builder.header("Content-Type", "application/json").method(method, body == null
            ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body)));
        var response = http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        // Never print bodies: login responses contain credentials and user data.
        check(response.statusCode() == expected, method + " " + path.split("\\?")[0] + " HTTP " + expected);
        return response.body().isBlank() ? null : JSON.readTree(response.body());
    }
    public static void main(String[] args) throws Exception {
        String schema = System.getenv("V16_SCHEMA"), url = System.getenv("V16_URL");
        boolean clone = schema != null && schema.matches("jjikmuk_v16_rehearsal_[0-9]{8}_[a-f0-9]{8}");
        if ((!clone && !"jjikmuk".equals(schema)) || url == null ||
            !url.matches("jdbc:mysql://127\\.0\\.0\\.1:[0-9]+/" + schema + "\\?.*"))
            throw new IllegalArgumentException("Explicit loopback source or disposable V16 clone required");
        String user = System.getenv("V16_USER"), password = System.getenv("V16_PASSWORD");
        String action = args.length == 1 ? args[0] : "";
        if (!Set.of("migrate", "verify", "smoke").contains(action)) throw new IllegalArgumentException("Unknown action");
        if (action.equals("smoke") && !clone) throw new IllegalArgumentException("Test writes allowed only on clone");
        if (action.equals("migrate") && !clone && !"backup-and-clone-verified".equals(System.getenv("V16_ALLOW_LOCAL_APPLY")))
            throw new IllegalArgumentException("Verify backup + clone before explicit source approval");
        try (var c = DriverManager.getConnection(url, user, password)) {
            try (var s = c.createStatement(); var r = s.executeQuery("SELECT @@server_uuid,@@hostname,DATABASE()")) {
                r.next(); check(r.getString(1).equals(System.getenv("V16_UUID")) &&
                    r.getString(2).equalsIgnoreCase(System.getenv("V16_HOST")) && r.getString(3).equals(schema), "server identity");
            }
            var fw = Flyway.configure().dataSource(url, user, password).locations("classpath:db/migration")
                .target("16").baselineOnMigrate(false).cleanDisabled(true).validateOnMigrate(true).load();
            if (action.equals("migrate")) {
                check("15".equals(fw.info().current().getVersion().toString()), "source version 15");
                var result = fw.migrate();
                check(result.migrationsExecuted == 1, "exactly V16 applied");
                fw.validate(); check(fw.migrate().migrationsExecuted == 0, "repeat migrate no-op");
                save("migration.json", Map.of("schema", schema, "version", "16", "validated", true,
                    "migrationsExecuted", result.migrationsExecuted, "repeatMigrationsExecuted", 0));
            } else fw.validate();
            check("16".equals(fw.info().current().getVersion().toString()), "version 16");
            check(count(c, "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='family_profiles' AND COLUMN_NAME IN ('relationship','emoji') AND CHARACTER_SET_NAME='utf8mb4' AND IS_NULLABLE='YES' AND CHARACTER_MAXIMUM_LENGTH=32") == 2, "nullable utf8mb4 family metadata");
            check(count(c, "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='histories' AND COLUMN_NAME IN ('analysis_mode','personalization_allowed') AND IS_NULLABLE='NO'") == 2, "history context columns");
            check(count(c, "SELECT COUNT(DISTINCT INDEX_NAME) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='histories' AND INDEX_NAME IN ('idx_history_product_view','idx_history_personalization')") == 2, "history indexes");
            check(count(c, "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='product_favorites' AND INDEX_NAME='uk_favorite_user_product' AND NON_UNIQUE=0") == 2, "favorite unique owner/product");
            check(count(c, "SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='product_favorites' AND REFERENCED_TABLE_NAME='users' AND DELETE_RULE='CASCADE'") == 1, "favorite owner cascade");
            check(count(c, "SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='product_favorites' AND REFERENCED_TABLE_NAME='products'") == 0, "no catalog foreign key");
            if (action.equals("migrate")) {
                check(count(c, "SELECT COUNT(*) FROM histories WHERE analysis_mode <> 'self' OR personalization_allowed <> TRUE") == 0, "legacy history defaults preserved");
                check(count(c, "SELECT COUNT(*) FROM product_favorites") == 0, "no invented favorite states");
            }
        }
        if (action.equals("smoke")) smoke(url, user, password);
        save(action + "-checks.json", Map.of("schema", schema, "action", action, "passed", true, "checks", checks));
        System.out.println("V16_AUDIT " + JSON.writeValueAsString(Map.of("action", action, "schema", schema, "passed", true, "checks", checks.size())));
    }
    static void smoke(String url, String username, String password) throws Exception {
        var properties = new LinkedHashMap<String, String>();
        properties.put("spring.config.import", ""); properties.put("spring.datasource.url", url);
        properties.put("spring.datasource.username", username); properties.put("spring.datasource.password", password);
        properties.put("spring.datasource.driver-class-name", "com.mysql.cj.jdbc.Driver");
        properties.put("spring.datasource.hikari.maximum-pool-size", "4");
        properties.put("spring.jpa.hibernate.ddl-auto", "validate"); properties.put("spring.flyway.enabled", "false");
        properties.put("server.address", "127.0.0.1"); properties.put("server.port", "0");
        properties.put("jwt.secret", UUID.randomUUID().toString() + UUID.randomUUID());
        properties.put("google.client-id", ""); properties.put("spring.mail.host", "127.0.0.1"); properties.put("spring.mail.port", "1");
        for (String flag : List.of("product.import", "product.import.rollback", "recommendation.import", "product.search.backfill",
            "product.data-model.backfill", "product.search.logging", "product.search.evaluation", "recommendation.logging", "recommendation.evaluation"))
            properties.put(flag + ".enabled", "false");
        String[] options = properties.entrySet().stream().map(e -> "--" + e.getKey() + "=" + e.getValue()).toArray(String[]::new);
        try (var context = new SpringApplication(BackendApplication.class).run(options)) {
            var jdbc = context.getBean(JdbcTemplate.class);
            int port = ((WebServerApplicationContext)context).getWebServer().getPort();
            var http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
            String suffix = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
            String email = "v16-" + suffix + "@jjikmuk.invalid", pwd = UUID.randomUUID() + "a9!";
            jdbc.update("INSERT INTO users(email,nickname,password,role,auth_provider,profile_completed,token_version,has_profile_photo) VALUES(?,?,?,'USER','LOCAL',TRUE,0,FALSE)",
                email, "v16_" + suffix, new BCryptPasswordEncoder().encode(pwd));
            long owner = jdbc.queryForObject("SELECT id FROM users WHERE email=?", Long.class, email);
            String token = request(http, port, "POST", "/api/auth/login", null, Map.of("email", email, "password", pwd), 200).get("token").asText();
            String device2 = request(http, port, "POST", "/api/auth/login", null, Map.of("email", email, "password", pwd), 200).get("token").asText();
            String familyPath = "/api/users/me/family-profiles";
            var family = request(http, port, "POST", familyPath, token,
                Map.of("nickname", "엄마", "relation", "어머니", "emoji", "👩🏽‍🦱", "allergies", "peanut"), 201).get("data");
            long familyId = family.get("id").asLong();
            check(family.get("relation").asText().equals("어머니") && !family.has("relationship"), "canonical relation field");
            var saved = request(http, port, "GET", familyPath + "/" + familyId, device2, null, 200).get("data");
            check(saved.get("emoji").asText().equals("👩🏽‍🦱"), "MySQL composite emoji roundtrip across sessions");
            request(http, port, "PATCH", familyPath + "/" + familyId, token, Map.of("version", saved.get("version").asLong(), "relation", "보호자"), 200);
            request(http, port, "PATCH", familyPath + "/" + familyId, token, Map.of("version", saved.get("version").asLong(), "emoji", "👨"), 409);
            var productIds = jdbc.queryForList("SELECT product_id FROM products WHERE product_id IS NOT NULL ORDER BY product_id LIMIT 2", Long.class);
            check(productIds.size() == 2, "real catalog fixtures available");
            long pid = productIds.get(0), otherPid = productIds.get(1);
            String favoritePath = "/api/users/me/favorites/" + pid;
            request(http, port, "GET", favoritePath, null, null, 401);
            request(http, port, "PUT", favoritePath, token, null, 200);
            request(http, port, "PUT", favoritePath, device2, null, 200);
            check(jdbc.queryForObject("SELECT COUNT(*) FROM product_favorites WHERE user_id=? AND product_id=?", Long.class, owner, pid) == 1, "one favorite across retries");
            check(jdbc.queryForObject("SELECT COUNT(*) FROM histories WHERE user_id=? AND action_type='FAVORITE'", Long.class, owner) == 1, "one FAVORITE event");
            var list = request(http, port, "GET", "/api/users/me/favorites?page=0&size=1", device2, null, 200).get("data");
            check(list.get("items").size() == 1 && list.get("items").get(0).get("product").get("productId").asLong() == pid, "favorite paginated product identity");
            request(http, port, "GET", "/api/products/id/" + pid + "?analysisMode=selected&includeSelf=false&familyProfileIds=" + familyId, token, null, 200);
            request(http, port, "GET", "/api/products/id/" + pid + "?analysisMode=none", token, null, 200);
            request(http, port, "GET", "/api/products/id/" + otherPid, token, null, 200);
            check(jdbc.queryForObject("SELECT COUNT(*) FROM histories WHERE user_id=? AND action_type='SCAN' AND personalization_allowed=FALSE", Long.class, owner) == 2, "family and none do not train personal taste");
            check(jdbc.queryForObject("SELECT COUNT(*) FROM histories WHERE user_id=? AND action_type='SCAN' AND personalization_allowed=TRUE", Long.class, owner) == 1, "self scan retained for personal taste");
            var recent = request(http, port, "GET", "/api/histories/user/" + owner + "?view=recent&size=1", device2, null, 200).get("data");
            check(recent.get("items").size() == 1 && recent.get("hasNext").asBoolean(), "recent pagination on MySQL");
            var allRecent = request(http, port, "GET", "/api/histories/user/" + owner + "?view=recent&size=20", token, null, 200).get("data");
            check(allRecent.get("items").size() == 2, "recent dedup includes none and family");
            request(http, port, "DELETE", favoritePath, token, null, 200);
            request(http, port, "DELETE", favoritePath, device2, null, 200);
            check(jdbc.queryForObject("SELECT COUNT(*) FROM histories WHERE user_id=? AND action_type='UNFAVORITE'", Long.class, owner) == 1, "one UNFAVORITE event");
            // Check DB constraints in an independent rolled-back transaction.
            try (var c = DriverManager.getConnection(url, username, password)) {
                c.setAutoCommit(false);
                try (var s = c.prepareStatement("INSERT INTO product_favorites(user_id,product_id,barcode,created_at) VALUES(?,?,?,NOW(6))")) {
                    s.setLong(1, owner); s.setLong(2, pid); s.setString(3, "constraint-fixture"); s.executeUpdate();
                    try { s.executeUpdate(); throw new IllegalStateException("duplicate accepted"); }
                    catch (SQLException expected) { check(expected.getErrorCode() == 1062, "MySQL unique violation enforced"); }
                    s.setLong(1, Long.MAX_VALUE);
                    try { s.executeUpdate(); throw new IllegalStateException("orphan accepted"); }
                    catch (SQLException expected) { check(expected.getErrorCode() == 1452, "MySQL owner FK enforced"); }
                } finally { c.rollback(); }
            }
            request(http, port, "PUT", favoritePath, token, null, 200);
            request(http, port, "DELETE", "/api/users/" + owner, token, null, 200);
            check(jdbc.queryForObject("SELECT COUNT(*) FROM product_favorites WHERE user_id=?", Long.class, owner) == 0 &&
                jdbc.queryForObject("SELECT COUNT(*) FROM histories WHERE user_id=?", Long.class, owner) == 0 &&
                jdbc.queryForObject("SELECT COUNT(*) FROM family_profiles WHERE owner_id=?", Long.class, owner) == 0,
                "account deletion removes family favorites and history");
        }
    }
}
