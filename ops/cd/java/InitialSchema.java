import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.net.URI;
import java.util.Base64;
import java.util.Set;
import java.util.TreeSet;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.io.PrintWriter;
import java.nio.channels.FileChannel;
import java.nio.ByteBuffer;
import java.nio.file.StandardOpenOption;
import java.util.logging.Logger;

/** One-time, V17-V20 only. Credentials are supplied through a private stdin pipe. */
public final class InitialSchema {
    private static String phase = "INPUT";
    static Flyway configured(Path stage, String url, String user, String password) {
        return configured(stage, new TrackedSource(url, user, password, null));
    }

    static Flyway configured(Path stage, DataSource source) {
        return Flyway.configure()
            .dataSource(source)
            .locations("filesystem:" + stage.resolve("sql"))
            .target("20").cleanDisabled(true).baselineOnMigrate(false)
            .outOfOrder(false).validateOnMigrate(true).validateMigrationNaming(true)
            .placeholderReplacement(false).skipDefaultCallbacks(true)
            .ignoreMigrationPatterns(new String[0]).connectRetries(0).lockRetryCount(0)
            .initSql("SET SESSION lock_wait_timeout=10, innodb_lock_wait_timeout=10")
            .loggers("slf4j").load();
    }

    /** Persist ownership before Flyway can execute SQL on any connection. */
    static final class TrackedSource implements DataSource {
        private final String url, user, password;
        private final Path journal;
        TrackedSource(String url, String user, String password, Path journal) {
            this.url=url; this.user=user; this.password=password; this.journal=journal;
        }
        public Connection getConnection() throws SQLException {
            Connection connection = DriverManager.getConnection(url, user, password);
            try {
                if (journal != null) {
                    long id;
                    try (var statement = connection.createStatement();
                         var row = statement.executeQuery("SELECT CONNECTION_ID()")) {
                        if (!row.next() || (id=row.getLong(1)) <= 0 || row.next()) throw new SQLException();
                    }
                    byte[] bytes=(Long.toString(id)+"\n").getBytes(StandardCharsets.US_ASCII);
                    try (FileChannel channel=FileChannel.open(journal, StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
                        ByteBuffer buffer=ByteBuffer.wrap(bytes);
                        while(buffer.hasRemaining()) channel.write(buffer);
                        channel.force(true);
                    }
                }
                return connection;
            } catch (Exception error) {
                connection.close(); throw new SQLException("CONNECTION_REGISTRATION_FAILED");
            }
        }
        public Connection getConnection(String u,String p) throws SQLException { throw new SQLException(); }
        public PrintWriter getLogWriter() { return null; }
        public void setLogWriter(PrintWriter writer) { }
        public int getLoginTimeout() { return 5; }
        public void setLoginTimeout(int seconds) { }
        public Logger getParentLogger() { return Logger.getGlobal(); }
        public boolean isWrapperFor(Class<?> type) { return false; }
        public <T> T unwrap(Class<T> type) throws SQLException { throw new SQLException(); }
    }

    static void apply(Flyway flyway) {
        phase = "INFO";
        Set<String> pending = new TreeSet<>();
        MigrationInfo[] migrations = flyway.info().pending();
        for (MigrationInfo migration : migrations) {
            if (!migration.getType().name().equals("SQL") || migration.getVersion() == null)
                throw new IllegalStateException();
            pending.add(migration.getVersion().toString());
        }
        if (migrations.length != 4 || !pending.equals(Set.of("17", "18", "19", "20")))
            throw new IllegalStateException();
        phase = "MIGRATE";
        if (flyway.migrate().migrationsExecuted != 4) throw new IllegalStateException();
        phase = "VALIDATE";
        flyway.validate();
    }

    private static String input(BufferedReader reader) throws Exception {
        String line = reader.readLine();
        if (line == null || line.length() > 90000) throw new IllegalArgumentException();
        return new String(Base64.getDecoder().decode(line), StandardCharsets.UTF_8);
    }

    public static void main(String[] args) {
        PrintStream publicOutput = System.out;
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        try {
            if (args.length != 1) throw new IllegalArgumentException();
            Path stage = Path.of(args[0]).toRealPath();
            if (!stage.toString().matches("/opt/jjikmuk-initial-[a-f0-9]{16}"))
                throw new IllegalArgumentException();
            BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
            String url = input(reader), user = input(reader), password = input(reader);
            if (!url.startsWith("jdbc:mysql://")) throw new IllegalArgumentException();
            URI target = URI.create(url.substring(5));
            if (reader.readLine() != null ||
                    !"jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com".equals(target.getHost()) ||
                    !(target.getPort() == -1 || target.getPort() == 3306) ||
                    !"/jjikmuk".equals(target.getPath()) || target.getUserInfo() != null || target.getFragment() != null)
                throw new IllegalArgumentException();
            Path journal=stage.resolve("flyway-owned/connections");
            if (!java.nio.file.Files.isRegularFile(journal, java.nio.file.LinkOption.NOFOLLOW_LINKS))
                throw new IllegalArgumentException();
            apply(configured(stage, new TrackedSource(url, user, password, journal)));
            publicOutput.println("{\"status\":\"SCHEMA_PREPARED\",\"migrations\":4}");
        } catch (Throwable error) {
            // Database URLs, credentials, SQL and driver messages never reach SSM output.
            String type = error.getClass().getSimpleName().toUpperCase(java.util.Locale.ROOT);
            if (!type.matches("[A-Z]{1,45}")) type = "OTHER";
            publicOutput.println("{\"status\":\"SCHEMA_STOPPED_KEEP_RECORDS_NO_RETRY\",\"phase\":\""
                + phase + "\",\"type\":\"" + type + "\"}");
            System.exit(1);
        }
    }
}
