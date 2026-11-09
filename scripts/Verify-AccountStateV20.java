// Java 21 source launcher with the built JAR's BOOT-INF/classes and BOOT-INF/lib/* classpath.
// Only an explicitly pinned loopback MySQL server is allowed. Smoke writes: disposable clone only.
// Credentials are environment-only; reports contain check labels, not accounts, tokens or chat bodies.
import java.nio.file.*;
import java.sql.*;
import java.time.Duration;
import java.util.*;
import java.net.*;
import java.net.http.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import com.sun.net.httpserver.HttpServer;
import org.flywaydb.core.Flyway;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.jjikmuk.backend.BackendApplication;
import org.jjikmuk.backend.domain.user.UserService;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

class VerifyAccountStateV20 {
    static final JsonMapper JSON = JsonMapper.builder().findAndAddModules().build();
    static final List<String> checks = Collections.synchronizedList(new ArrayList<>());
    static final List<String> newTables = List.of("chat_conversations", "chat_turns", "account_analysis_selections", "account_analysis_selection_families");
    static void check(boolean ok, String label) {
        if (!ok) throw new IllegalStateException("V20 verification failed: " + label);
        checks.add(label);
    }
    static void save(String name, Object value) throws Exception {
        Files.writeString(Path.of(System.getenv("V20_OUTPUT")).resolve(name),
            JSON.writerWithDefaultPrettyPrinter().writeValueAsString(value), StandardOpenOption.CREATE_NEW);
    }
    static long number(Connection c, String sql) throws Exception {
        try (var s=c.createStatement(); var r=s.executeQuery(sql)) { r.next(); return r.getLong(1); }
    }
    static JsonNode request(HttpClient http, int port, String method, String path, String token, Object body, int expected) throws Exception {
        var response = send(http,port,method,path,token,body);
        if(response.statusCode()!=expected) {
            var error=JSON.readTree(response.body());
            String code=error.path("code").asString("").replaceAll("[^A-Z0-9_]", "");
            String field=error.path("field").asString("").replaceAll("[^A-Za-z0-9_]", "");
            throw new IllegalStateException(method+" "+path.split("\\?")[0]+" expected "+expected+" actual "+response.statusCode()+" code="+code+" field="+field);
        }
        check(true, method+" "+path.split("\\?")[0]+" HTTP "+expected);
        return response.body().isBlank()?JSON.createObjectNode():JSON.readTree(response.body());
    }
    static HttpResponse<String> send(HttpClient http, int port, String method, String path, String token, Object body) throws Exception {
        var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path)).timeout(Duration.ofSeconds(45));
        if(token!=null)b.header("Authorization","Bearer "+token);
        b.header("Content-Type","application/json").method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body)));
        return http.send(b.build(),HttpResponse.BodyHandlers.ofString());
    }
    public static void main(String[] args) throws Exception {
        String schema=System.getenv("V20_SCHEMA"), url=System.getenv("V20_URL");
        boolean clone=schema!=null&&schema.matches("jjikmuk_v20_rehearsal_[0-9]{8}");
        if((!clone&&!"jjikmuk".equals(schema))||url==null||!url.matches("jdbc:mysql://127\\.0\\.0\\.1:[0-9]+/"+schema+"\\?.*"))
            throw new IllegalArgumentException("Pinned local source or disposable V20 clone required");
        String action=args.length==1?args[0]:"", user=System.getenv("V20_USER"), password=System.getenv("V20_PASSWORD");
        if(!Set.of("migrate","verify","smoke","startup").contains(action))throw new IllegalArgumentException("Unknown action");
        if(action.equals("smoke")&&!clone)throw new IllegalArgumentException("Smoke writes require a clone");
        if(action.equals("migrate")&&!clone&&!"backup-and-clone-verified".equals(System.getenv("V20_ALLOW_LOCAL_APPLY")))
            throw new IllegalArgumentException("Verified backup/clone and explicit local approval required");
        try(var c=DriverManager.getConnection(url,user,password)) {
            try(var s=c.createStatement();var r=s.executeQuery("SELECT @@server_uuid,@@hostname,DATABASE()")) {
                r.next();check(r.getString(1).equals(System.getenv("V20_UUID"))&&r.getString(2).equalsIgnoreCase(System.getenv("V20_HOST"))&&r.getString(3).equals(schema),"pinned local server identity");
            }
            var fw=Flyway.configure().dataSource(url,user,password).locations("classpath:db/migration")
                .target("20").baselineOnMigrate(false).cleanDisabled(true).validateOnMigrate(true).load();
            if(action.equals("migrate")) {
                check("17".equals(fw.info().current().getVersion().toString()),"starts at V17");
                // migrate validates applied checksums while allowing the three intentional pending migrations.
                var result=fw.migrate();check(result.migrationsExecuted==3,"exactly V18 V19 V20 applied");
                fw.validate();check(fw.migrate().migrationsExecuted==0,"repeat migration no-op");
                save("migration.json",Map.of("schema",schema,"version","20","executed",3,"repeatExecuted",0,"validated",true));
            } else fw.validate();
            check("20".equals(fw.info().current().getVersion().toString()),"current version V20");
            check(number(c,"SELECT COUNT(*) FROM flyway_schema_history WHERE success=0")==0,"no failed migrations");
            check(number(c,"SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND COLUMN_NAME='profile_version' AND DATA_TYPE='bigint' AND IS_NULLABLE='NO' AND COLUMN_DEFAULT='0'")==1,"profile revision schema");
            check(number(c,"SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME IN ('chat_conversations','chat_turns','account_analysis_selections','account_analysis_selection_families') AND DELETE_RULE='CASCADE'")==5,"all five ownership and lifecycle foreign keys");
            check(number(c,"SELECT COUNT(DISTINCT INDEX_NAME) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND INDEX_NAME IN ('uk_chat_conversation_owner_client','uk_chat_turn_conversation_client') AND NON_UNIQUE=0")==2,"chat retry uniqueness");
            if(action.equals("migrate")) {
                for(String table:newTables)check(number(c,"SELECT COUNT(*) FROM "+table)==0,"no invented rows in "+table);
                check(number(c,"SELECT COUNT(*) FROM users WHERE profile_version<>0")==0,"legacy profile default zero");
            }
        }
        if(action.equals("smoke")||action.equals("startup"))runApplication(url,user,password,action.equals("smoke"));
        save("checks.json",Map.of("schema",schema,"action",action,"passed",true,"checks",checks));
        System.out.println("V20_VERIFICATION "+JSON.writeValueAsString(Map.of("schema",schema,"action",action,"passed",true,"checks",checks.size())));
    }
    static void runApplication(String url,String username,String password,boolean smoke) throws Exception {
        var upstream=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        var aiCalls=new AtomicInteger();var payloads=Collections.synchronizedList(new ArrayList<JsonNode>());
        upstream.createContext("/chat",exchange->{
            try {
                var payload=JSON.readTree(exchange.getRequestBody().readAllBytes());payloads.add(payload);aiCalls.incrementAndGet();
                exchange.getResponseHeaders().set("Content-Type","application/json");
                for(String key:List.of("X-Jjikmuk-Analysis-Contract","X-Jjikmuk-Analysis-Context"))exchange.getResponseHeaders().set(key,exchange.getRequestHeaders().getFirst(key));
                byte[] reply=JSON.writeValueAsBytes(Map.of("answer","로컬 검증용 응답","selection",payload.get("analysisContext").get("selection")));
                exchange.sendResponseHeaders(200,reply.length);exchange.getResponseBody().write(reply);
            } finally { exchange.close(); }
        });upstream.start();
        var properties=new LinkedHashMap<String,String>();
        properties.put("spring.config.import","");properties.put("spring.profiles.active","v20-verification");
        properties.put("spring.datasource.url",url);properties.put("spring.datasource.username",username);properties.put("spring.datasource.password",password);
        properties.put("spring.datasource.driver-class-name","com.mysql.cj.jdbc.Driver");properties.put("spring.datasource.hikari.maximum-pool-size","6");
        properties.put("spring.jpa.hibernate.ddl-auto","validate");properties.put("spring.flyway.enabled","false");
        properties.put("spring.sql.init.mode","never");properties.put("server.address","127.0.0.1");properties.put("server.port","0");
        properties.put("jwt.secret",UUID.randomUUID().toString()+UUID.randomUUID());properties.put("google.client-id","");
        properties.put("spring.mail.host","127.0.0.1");properties.put("spring.mail.port","1");properties.put("product.search.mode","locate");
        properties.put("chat.ai.url","http://127.0.0.1:"+upstream.getAddress().getPort()+"/chat");
        properties.put("chatbot.api-token",UUID.randomUUID().toString());properties.put("chatbot.external-ai-consent-secret",UUID.randomUUID().toString()+UUID.randomUUID());
        properties.put("chatbot.developer-test-auto-consent","false");
        properties.put("logging.level.org.springframework.boot.security.autoconfigure", "ERROR");
        for(String flag:List.of("product.import","product.import.rollback","recommendation.import","product.search.backfill",
            "product.data-model.backfill","product.search.logging","product.search.evaluation","recommendation.logging","recommendation.evaluation","ocr.proxy","ocr.debug","scan","scan.image-fallback"))properties.put(flag+".enabled","false");
        String[] options=properties.entrySet().stream().map(e->"--"+e.getKey()+"="+e.getValue()).toArray(String[]::new);
        try(var context=new SpringApplication(BackendApplication.class).run(options)) {
            int port=((WebServerApplicationContext)context).getWebServer().getPort();
            var http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
            request(http,port,"GET","/api/products/filters",null,null,200);
            request(http,port,"GET","/api/users/me/analysis-selection",null,null,401);
            check(true,"Hibernate validates migrated MySQL schema and backend starts");
            if(smoke) {
                var jdbc=context.getBean(JdbcTemplate.class);var users=context.getBean(UserService.class);
                // Only explicit synthetic fixture IDs in the disposable clone can be recovered after a failed run.
                String prior=System.getenv("V20_CLEANUP_IDS");
                if(prior!=null&&!prior.isBlank())for(String id:prior.split(","))cleanupFixture(jdbc,users,Long.parseLong(id));
                try { exercise(jdbc,http,port,aiCalls,payloads); }
                finally {
                    var file=Path.of(System.getenv("V20_OUTPUT")).resolve("fixture-ids.json");
                    if(Files.exists(file)) {
                        var ids=JSON.readTree(Files.readString(file));
                        cleanupFixture(jdbc,users,ids.get("owner").asLong());
                        cleanupFixture(jdbc,users,ids.get("other").asLong());
                    }
                }
            }
            else check(aiCalls.get()==0,"source startup makes no AI calls or test-account writes");
        } finally { upstream.stop(0); }
    }
    static void cleanupFixture(JdbcTemplate jdbc,UserService users,long id) {
        var emails=jdbc.queryForList("SELECT email FROM users WHERE id=?",String.class,id);
        if(emails.isEmpty())return;
        if(!emails.get(0).matches("v20(-other)?-[0-9a-f]{10}@jjikmuk\\.invalid"))throw new IllegalStateException("Not a synthetic fixture");
        users.deleteUser(id);
    }
    static void exercise(JdbcTemplate jdbc,HttpClient http,int port,AtomicInteger aiCalls,List<JsonNode> payloads) throws Exception {
        var encoder=new BCryptPasswordEncoder();String suffix=UUID.randomUUID().toString().replace("-","").substring(0,10),pwd=UUID.randomUUID()+"a9!";
        String email="v20-"+suffix+"@jjikmuk.invalid",otherEmail="v20-other-"+suffix+"@jjikmuk.invalid";
        for(String address:List.of(email,otherEmail))jdbc.update("INSERT INTO users(email,nickname,password,role,auth_provider,profile_completed,token_version,has_profile_photo,profile_version) VALUES(?,?,?,'USER','LOCAL',TRUE,0,FALSE,0)",address,"v20"+UUID.randomUUID().toString().replace("-", "").substring(0,12),encoder.encode(pwd));
        long owner=jdbc.queryForObject("SELECT id FROM users WHERE email=?",Long.class,email),other=jdbc.queryForObject("SELECT id FROM users WHERE email=?",Long.class,otherEmail);
        save("fixture-ids.json",Map.of("owner",owner,"other",other));
        String a=request(http,port,"POST","/api/auth/login",null,Map.of("email",email,"password",pwd),200).get("token").asString();
        String b=request(http,port,"POST","/api/auth/login",null,Map.of("email",email,"password",pwd),200).get("token").asString();
        String stranger=request(http,port,"POST","/api/auth/login",null,Map.of("email",otherEmail,"password",pwd),200).get("token").asString();
        String self="/api/users/me",families=self+"/family-profiles",selection=self+"/analysis-selection";
        check(request(http,port,"GET",self,a,null,200).get("data").get("version").asLong()==0,"profile revision exposed");
        request(http,port,"PATCH",self,a,Map.of("version",0,"allergies","milk"),200);
        check(request(http,port,"PATCH",self,b,Map.of("version",0,"allergies","soy"),409).get("code").asString().equals("PROFILE_VERSION_CONFLICT"),"profile stale write rejected");
        check(request(http,port,"GET",self,b,null,200).get("data").get("allergies").asString().equals("milk"),"profile winner retained");
        long family=request(http,port,"POST",families,a,Map.of("nickname","가족","emoji","👩🏽‍🦱","relation","보호자","allergies","peanut"),201).get("data").get("id").asLong();
        check(request(http,port,"GET",selection,b,null,200).get("data").get("familyProfileIds").isEmpty(),"new families never auto-selected");
        request(http,port,"PUT",selection,a,Map.of("version",0,"includeSelf",false,"familyProfileIds",List.of(family)),200);
        check(request(http,port,"GET",selection,b,null,200).get("data").get("familyProfileIds").get(0).asLong()==family,"account selection shared across devices");
        request(http,port,"PUT",selection,stranger,Map.of("version",0,"includeSelf",false,"familyProfileIds",List.of(family)),404);
        request(http,port,"PUT",selection,b,Map.of("version",0,"includeSelf",true,"familyProfileIds",List.of()),409);
        String barcode=jdbc.queryForObject("SELECT barcode FROM products WHERE barcode REGEXP '^[0-9]{13}$' ORDER BY barcode LIMIT 1",String.class);
        check(request(http,port,"GET","/api/products/"+barcode,a,null,200).get("data").get("analysis").get("selection").get("familyProfileIds").get(0).asLong()==family,"real product analysis uses saved family");
        String rooms="/api/chat/conversations",clientRoom=UUID.randomUUID().toString();
        var create=Map.of("clientConversationId",clientRoom,"title","기기 간 대화 👨‍👩‍👧");
        long room=request(http,port,"POST",rooms,a,create,201).get("data").get("id").asLong();
        check(request(http,port,"POST",rooms,b,create,201).get("data").get("id").asLong()==room,"room create idempotent on MySQL");
        request(http,port,"GET",rooms+"/"+room,stranger,null,404);
        var question=Map.of("conversationId",room,"clientMessageId",UUID.randomUUID().toString(),"message","성분을 설명해주세요","externalAiConsent",false);
        request(http,port,"POST","/api/chat",a,question,200);request(http,port,"POST","/api/chat",b,question,200);
        check(aiCalls.get()==1,"same message replay invokes local AI stub once");
        check(payloads.get(0).get("analysisContext").get("selection").get("familyProfileIds").get(0).asLong()==family,"chat v2 uses saved family selection");
        var messages=request(http,port,"GET",rooms+"/"+room+"/messages",b,null,200).get("data").get("items");
        check(messages.size()==1&&messages.get(0).get("status").asString().equals("SUCCEEDED"),"chat persisted once across devices");
        request(http,port,"GET",rooms+"/"+room+"/messages",stranger,null,404);
        // Two independent HTTP transactions with the same revision: exactly one winner on MySQL.
        var pool=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try {
            var first=pool.submit(()->{start.await();return send(http,port,"PUT",selection,a,Map.of("version",1,"includeSelf",false,"familyProfileIds",List.of())).statusCode();});
            var second=pool.submit(()->{start.await();return send(http,port,"PUT",selection,b,Map.of("version",1,"includeSelf",true,"familyProfileIds",List.of(family))).statusCode();});
            start.countDown();var statuses=new ArrayList<>(List.of(first.get(60,TimeUnit.SECONDS),second.get(60,TimeUnit.SECONDS)));Collections.sort(statuses);
            check(statuses.equals(List.of(200,409)),"MySQL concurrent toggle writes have exactly one winner");
        } finally {start.countDown();pool.shutdownNow();}
        request(http,port,"PUT",selection,a,Map.of("version",2,"includeSelf",false,"familyProfileIds",List.of(family)),200);
        request(http,port,"DELETE",families+"/"+family+"?version=0",a,null,200);
        var off=request(http,port,"GET",selection,b,null,200).get("data");
        check(off.get("version").asLong()==4&&off.get("mode").asString().equals("none"),"family removal atomically prunes selection without self fallback");
        check(request(http,port,"GET","/api/products/"+barcode,a,null,200).get("data").get("analysis").get("status").asString().equals("NOT_EVALUATED"),"all OFF is not PASS");
        request(http,port,"POST","/api/chat",a,Map.of("conversationId",room,"clientMessageId",UUID.randomUUID().toString(),"message","일반 정보"),200);
        check(payloads.get(1).get("analysisContext").get("selection").get("mode").asString().equals("none"),"chat respects stored all OFF");
        check(payloads.get(1).get("chat_history").isEmpty(),"changed people cannot inherit previous private context");
        try(var c=jdbc.getDataSource().getConnection()) {
            c.setAutoCommit(false);
            try(var s=c.createStatement()) {
                try {s.executeUpdate("INSERT INTO account_analysis_selections(owner_id) VALUES(9223372036854775807)");throw new IllegalStateException("orphan accepted");}
                catch(SQLException expected){check(expected.getErrorCode()==1452,"MySQL foreign key rejects orphan account");}
                try {s.executeUpdate("INSERT INTO account_analysis_selections(owner_id) VALUES("+owner+")");throw new IllegalStateException("duplicate accepted");}
                catch(SQLException expected){check(expected.getErrorCode()==1062,"MySQL one settings row per account");}
            } finally {c.rollback();}
        }
        request(http,port,"DELETE","/api/users/"+owner,a,null,200);
        check(jdbc.queryForObject("SELECT COUNT(*) FROM chat_conversations WHERE owner_id=?",Long.class,owner)==0,"account deletion clears rooms");
        check(jdbc.queryForObject("SELECT COUNT(*) FROM chat_turns WHERE conversation_id=?",Long.class,room)==0,"account deletion clears turns");
        check(jdbc.queryForObject("SELECT COUNT(*) FROM account_analysis_selections WHERE owner_id=?",Long.class,owner)==0,"account deletion clears toggles");
        request(http,port,"GET",self,stranger,null,200);request(http,port,"DELETE","/api/users/"+other,stranger,null,200);
        for(String table:newTables)check(jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Long.class)==0,"clone fixture cleanup "+table);
    }
}
