// Launched only by the loopback/host-checked Python helper. No credentials in argv.
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import org.flywaydb.core.Flyway;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.PayloadApplicationEvent;
import org.jjikmuk.backend.BackendApplication;
import org.jjikmuk.backend.domain.recommendation.RecommendationCompletedEvent;
import tools.jackson.databind.json.JsonMapper;

class LocalRecommendationEvaluation {
    public static void main(String[] args) throws Exception {
        String url = System.getenv("LOCAL_EVAL_URL");
        if (url == null || !url.matches("jdbc:mysql://127\\.0\\.0\\.1:[0-9]+/jjikmuk\\?.*"))
            throw new IllegalStateException("Loopback jjikmuk URL required");
        String user = System.getenv("LOCAL_EVAL_USER"), password = System.getenv("LOCAL_EVAL_PASSWORD");
        try (var connection = DriverManager.getConnection(url, user, password);
             var statement = connection.createStatement();
             var rows = statement.executeQuery("SELECT @@server_uuid, @@hostname, DATABASE()")) {
            rows.next();
            if (!rows.getString(1).equals(System.getenv("LOCAL_EVAL_UUID")) ||
                !rows.getString(2).equalsIgnoreCase(System.getenv("LOCAL_EVAL_HOST")) ||
                !rows.getString(3).equals("jjikmuk"))
                throw new IllegalStateException("Database identity changed");
        }
        if (args[0].equals("migrate")) {
            var flyway = Flyway.configure().dataSource(url, user, password)
                .locations("classpath:db/migration").target("13")
                .baselineOnMigrate(false).cleanDisabled(true).validateOnMigrate(true).load();
            var result = flyway.migrate();
            System.out.println("LOCAL_MIGRATION_SUCCESS migrations=" + result.migrationsExecuted + " target=" + result.targetSchemaVersion);
            return;
        }
        if (!args[0].equals("evaluate")) throw new IllegalArgumentException("Unknown operation");
        var events = new ArrayList<RecommendationCompletedEvent>();
        var application = new SpringApplication(BackendApplication.class);
        application.addListeners(event -> {
            if (event instanceof PayloadApplicationEvent<?> payload &&
                payload.getPayload() instanceof RecommendationCompletedEvent completed) events.add(completed);
        });
        int code = 0;
        try (ConfigurableApplicationContext context = application.run()) {
            System.out.println("LOCAL_EVALUATION_COMPLETED");
        } catch (Exception failure) {
            boolean gate = false;
            for (Throwable cause = failure; cause != null; cause = cause.getCause())
                if (String.valueOf(cause.getMessage()).contains("Recommendation quality gate failed")) gate = true;
            if (!gate) throw failure;
            System.out.println("LOCAL_EVALUATION_COMPLETED_GATE_FAILED");
            code = 2;
        } finally {
            var mapper = JsonMapper.builder().findAndAddModules().build();
            Files.writeString(Path.of(System.getenv("LOCAL_EVAL_AUDIT")), mapper.writerWithDefaultPrettyPrinter().writeValueAsString(events),
                StandardOpenOption.CREATE_NEW);
        }
        System.exit(code);
    }
}
