import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.net.URI;
import java.util.Base64;
import org.flywaydb.core.Flyway;

/** Only the reviewed V21, using the original migration bytes in the candidate JAR. */
public final class CatalogSchema {
    public static void main(String[] args) {
        PrintStream output=System.out;
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        try {
            if(args.length!=1) throw new IllegalArgumentException();
            Path stage=Path.of(args[0]).toRealPath();
            if(!stage.toString().matches("/opt/jjikmuk-catalog-[a-f0-9]{16}")) throw new IllegalArgumentException();
            var reader=new BufferedReader(new InputStreamReader(System.in,StandardCharsets.UTF_8));
            String[] values=new String[3];
            for(int i=0;i<3;i++) {
                String line=reader.readLine();
                if(line==null||line.length()>90000)throw new IllegalArgumentException();
                values[i]=new String(Base64.getDecoder().decode(line),StandardCharsets.UTF_8);
            }
            if(reader.readLine()!=null||!values[0].startsWith("jdbc:mysql://"))throw new IllegalArgumentException();
            URI target=URI.create(values[0].substring(5));
            if(!"jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com".equals(target.getHost())||
                !(target.getPort()==-1||target.getPort()==3306)||!"/jjikmuk".equals(target.getPath())||
                target.getUserInfo()!=null||target.getFragment()!=null)throw new IllegalArgumentException();
            Path journal=stage.resolve("flyway-owned/connections");
            if(!java.nio.file.Files.isRegularFile(journal,java.nio.file.LinkOption.NOFOLLOW_LINKS))throw new IllegalArgumentException();
            Flyway flyway=Flyway.configure().dataSource(new InitialSchema.TrackedSource(values[0],values[1],values[2],journal))
                .locations("filesystem:"+stage.resolve("sql")).target("21").cleanDisabled(true).baselineOnMigrate(false)
                .outOfOrder(false).validateOnMigrate(true).validateMigrationNaming(true).placeholderReplacement(false)
                .skipDefaultCallbacks(true).ignoreMigrationPatterns(new String[0]).connectRetries(0).lockRetryCount(0)
                .initSql("SET SESSION lock_wait_timeout=10,innodb_lock_wait_timeout=10").loggers("slf4j").load();
            var pending=flyway.info().pending();
            if(pending.length!=1||!"21".equals(pending[0].getVersion().toString())||!"SQL".equals(pending[0].getType().name()))
                throw new IllegalStateException();
            if(flyway.migrate().migrationsExecuted!=1)throw new IllegalStateException();
            flyway.validate();
            output.println("{\"status\":\"SCHEMA_PREPARED\",\"migrations\":1}");
        } catch(Throwable error) {
            output.println("{\"status\":\"SCHEMA_STOPPED_KEEP_RECORDS_NO_RETRY\"}");
            System.exit(1);
        }
    }
}
