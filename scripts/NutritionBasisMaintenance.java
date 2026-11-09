// Java 21 source launcher against bootJar's extracted BOOT-INF classpath.
// Explicit operator-run maintenance; never starts Spring or imports/replaces product rows.
import java.nio.file.*;
import java.io.*;
import java.sql.*;
import java.lang.reflect.*;
import java.security.MessageDigest;
import java.util.*;
import jakarta.persistence.Column;
import org.flywaydb.core.Flyway;
import org.jjikmuk.backend.domain.product.*;
import org.jjikmuk.backend.global.config.*;
import tools.jackson.databind.json.JsonMapper;

class NutritionBasisMaintenance {
    static final JsonMapper JSON=JsonMapper.builder().findAndAddModules().build();
    static final Path OUT=Path.of(System.getenv("NUTRITION_OUTPUT"));
    static final Path PLAN=System.getenv("NUTRITION_PLAN_DIR")==null?null:Path.of(System.getenv("NUTRITION_PLAN_DIR"));
    static final String SCHEMA=System.getenv("NUTRITION_SCHEMA");
    static final Map<String,Field> FIELDS=new HashMap<>();
    static final List<String> IDENTITY=List.of("product_name","manufacturer","report_no","source","total_weight",
        "energy_kcal","carbs_g","protein_g","fat_g","sugar_g","sodium_mg","cholesterol_mg");
    static {for(Field f:Product.class.getDeclaredFields()){var a=f.getAnnotation(Column.class);if(a!=null){f.setAccessible(true);FIELDS.put(a.name(),f);}}}
    record Change(String barcode,long productId,String signature,String basis) {}
    record Candidate(String barcode,ProductCsvRecord row) {}
    static void check(boolean b,String message){if(!b)throw new IllegalStateException(message);}
    static void save(String name,Object value)throws Exception{Files.writeString(OUT.resolve(name),JSON.writerWithDefaultPrettyPrinter().writeValueAsString(value),StandardOpenOption.CREATE_NEW);}
    static String hash(byte[] b)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));}
    static String fileHash(Path p)throws Exception{var h=MessageDigest.getInstance("SHA-256");try(var in=Files.newInputStream(p)){byte[] b=new byte[1024*1024];for(int n;(n=in.read(b))!=-1;)h.update(b,0,n);}return HexFormat.of().formatHex(h.digest());}
    static String signature(Product p)throws Exception{var v=new ArrayList<Object>();for(String k:IDENTITY){Object x=FIELDS.get(k).get(p);v.add(x instanceof String s?s.trim():x);}return hash(JSON.writeValueAsBytes(v));}
    static Product product(ResultSet r)throws Exception{
        Product p=Product.class.getDeclaredConstructor().newInstance();var m=r.getMetaData();
        for(int i=1;i<=m.getColumnCount();i++){Field f=FIELDS.get(m.getColumnLabel(i));if(f==null)continue;Object v=r.getObject(i);
            if(v!=null){Class<?> t=f.getType();if(t==Double.class)v=r.getDouble(i);else if(t==Long.class)v=r.getLong(i);else if(t==String.class)v=r.getString(i);}
            f.set(p,v);
        }return p;
    }
    static void approved() {
        check("backup-clone-reviewed".equals(System.getenv("NUTRITION_WRITE_APPROVAL")),
            "Write approval missing; operator must first verify backup and clone rehearsal");
    }
    static Connection connect()throws Exception{
        String url=System.getenv("NUTRITION_URL");
        check(SCHEMA!=null && SCHEMA.matches("[A-Za-z0-9_]+"),"Explicit schema required");
        check(url!=null && url.startsWith("jdbc:mysql://"),"Single MySQL endpoint required");
        var uri=java.net.URI.create(url.substring(5));
        check(uri.getHost()!=null && uri.getUserInfo()==null && ("/"+SCHEMA).equals(uri.getPath()),
            "URL must identify the expected schema without embedded credentials");
        check(uri.getQuery()==null || !uri.getQuery().toLowerCase(Locale.ROOT).matches(".*(password|user=|allowmultiqueries=true).*"),
            "Do not embed credentials or enable multiple statements in URL");
        var c=DriverManager.getConnection(url,System.getenv("NUTRITION_USER"),System.getenv("NUTRITION_PASSWORD"));
        try(var stmt=c.createStatement();var rs=stmt.executeQuery("SELECT @@server_uuid,@@hostname,DATABASE()")){rs.next();
            check(rs.getString(1).equals(System.getenv("NUTRITION_UUID")) &&
                rs.getString(2).equalsIgnoreCase(System.getenv("NUTRITION_HOST")) && rs.getString(3).equals(SCHEMA),
                "Server identity mismatch");
        }
        return c;
    }
    static Map<String,String> target(){
        return Map.of("schema",SCHEMA,"uuid",System.getenv("NUTRITION_UUID"),"hostname",System.getenv("NUTRITION_HOST"));
    }
    static void requireV17(Connection c)throws Exception{
        try(var stmt=c.createStatement();var rs=stmt.executeQuery("SELECT version,success FROM flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank DESC LIMIT 1")){
            check(rs.next() && "17".equals(rs.getString(1)) && rs.getBoolean(2),"Requires successful V17; review other versions separately");
        }
    }
    static List<Product> query(Connection c,List<String> barcodes,boolean lock)throws Exception{
        var results=new ArrayList<Product>();if(barcodes.isEmpty())return results;
        String sql="SELECT barcode,product_id,nutrition_basis_raw,"+String.join(",",IDENTITY)+" FROM products WHERE barcode IN ("+String.join(",",Collections.nCopies(barcodes.size(),"?"))+")"+(lock?" FOR UPDATE":"");
        try(var s=c.prepareStatement(sql)){for(int i=0;i<barcodes.size();i++)s.setString(i+1,barcodes.get(i));try(var r=s.executeQuery()){while(r.next())results.add(product(r));}}
        return results;
    }
    static void inc(Map<String,Long> counts,String key){counts.merge(key,1L,Long::sum);}
    static void plan(Connection c)throws Exception{
        requireV17(c);
        Path csv=Path.of(System.getenv("NUTRITION_CSV"));String csvHash=fileHash(csv);
        var duplicates=new HashSet<String>();var seen=new HashSet<String>();
        try(var reader=new ProductCsvReader(Files.newInputStream(csv))){for(ProductCsvRecord r;(r=reader.readRecord())!=null;){String key=r.text(ProductCsvColumn.BARCODE);if(key!=null&&!seen.add(key))duplicates.add(key);}}
        seen.clear();var counts=new TreeMap<String,Long>();var rawCounts=new TreeMap<String,Long>();long line=0;
        c.setReadOnly(true);c.setAutoCommit(false);
        var batch=new ArrayList<Candidate>();
        try(var reader=new ProductCsvReader(Files.newInputStream(csv));var out=Files.newBufferedWriter(OUT.resolve("plan.jsonl"),StandardOpenOption.CREATE_NEW)){
            for(ProductCsvRecord r;(r=reader.readRecord())!=null;){line++;check(r.getFieldCount()==reader.getHeaderCount(),"CSV field count changed");
                String key=r.text(ProductCsvColumn.BARCODE);if(key!=null)check(!key.startsWith("NO_BARCODE_ROW_"),"Reserved barcode");
                key=key==null?"NO_BARCODE_ROW_"+line:key;
                String basis=r.text(ProductCsvColumn.NUTRITION_BASIS_RAW);
                if(basis==null){inc(counts,"missing_csv_basis");continue;}
                if(duplicates.contains(key)){inc(counts,"duplicate_barcode_excluded");continue;}
                batch.add(new Candidate(key,r));if(batch.size()==500){planBatch(c,batch,counts,rawCounts,out);batch.clear();}
                if(line%100000==0)System.out.println("NUTRITION CSV rows "+line);
            }
            planBatch(c,batch,counts,rawCounts,out);
        }finally{c.rollback();}
        check(csvHash.equals(fileHash(csv)),"CSV changed during planning");
        save("plan-summary.json",Map.of("target",target(),"buildSha256",System.getenv("NUTRITION_BUILD_SHA256"),"csvRows",line,"csvSha256",csvHash,"counts",counts,"basisCounts",rawCounts,"duplicateBarcodes",duplicates,
            "planSha256",fileHash(OUT.resolve("plan.jsonl"))));System.out.println("NUTRITION plan "+counts);
    }
    static void planBatch(Connection c,List<Candidate> batch,Map<String,Long>counts,Map<String,Long>rawCounts,BufferedWriter out)throws Exception{
        var live=new HashMap<String,Product>();for(var p:query(c,batch.stream().map(Candidate::barcode).toList(),false))live.put(p.getBarcode(),p);
        for(var x:batch){var p=live.get(x.barcode());if(p==null){inc(counts,"missing_db_product");continue;}
            String basis=p.getNutritionBasisRaw()==null?ProductNutritionBasisRepair.INSTANCE.basisIfMatching(p,x.row()):null;
            if(basis==null){inc(counts,"mismatch_or_existing_basis");continue;}
            check(p.getProductId()!=null,"Missing stable product ID");
            out.write(JSON.writeValueAsString(new Change(p.getBarcode(),p.getProductId(),signature(p),basis))+"\n");
            inc(counts,"planned");inc(rawCounts,basis);
        }
    }
    static void apply(Connection c)throws Exception{
        approved();requireV17(c);check(PLAN!=null,"NUTRITION_PLAN_DIR required");
        try(var stmt=c.createStatement();var rs=stmt.executeQuery("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND event_object_table='products'")){
            rs.next();check(rs.getInt(1)==0,"Review product trigger side effects before backfill");
        }
        Path path=PLAN.resolve("plan.jsonl");var summary=JSON.readTree(Files.readString(PLAN.resolve("plan-summary.json")));
        check(summary.get("target").equals(JSON.valueToTree(target())),"Plan belongs to another server or schema");
        check(summary.get("buildSha256").asText().equals(System.getenv("NUTRITION_BUILD_SHA256")),"Use the same JAR as the reviewed plan");
        check(fileHash(path).equals(System.getenv("NUTRITION_PLAN_SHA256")),"Explicit reviewed plan SHA-256 required");
        check(fileHash(path).equals(summary.get("planSha256").asText()),"Plan hash changed");
        check(fileHash(Path.of(System.getenv("NUTRITION_CSV"))).equals(summary.get("csvSha256").asText()),"CSV changed after plan");
        try(var stmt=c.createStatement()){stmt.execute("SET SESSION innodb_lock_wait_timeout=5");}
        // Validate plan structure before writes; identity is rechecked under row locks in each batch.
        var seen=new HashSet<String>();long planned=0;
        try(var in=Files.newBufferedReader(path)){for(String line;(line=in.readLine())!=null;){
            var x=JSON.readValue(line,Change.class);
            check(x.productId()>0 && x.basis()!=null && !x.basis().isBlank() && x.basis().length()<=255 &&
                x.signature().matches("[a-f0-9]{64}") && seen.add(x.barcode()),"Malformed or duplicate plan row");
            planned++;
        }}
        check(planned==summary.get("counts").path("planned").asLong(),"Plan count mismatch");
        c.setAutoCommit(false);long n=0;var batch=new ArrayList<Change>();
        try(var in=Files.newBufferedReader(path);var log=Files.newBufferedWriter(OUT.resolve("commits.jsonl"),StandardOpenOption.CREATE_NEW)){
            for(String line;(line=in.readLine())!=null;){batch.add(JSON.readValue(line,Change.class));if(batch.size()==500){applyBatch(c,batch);n+=batch.size();log.write("{\"applied\":"+n+"}\n");log.flush();batch.clear();}}
            if(!batch.isEmpty()){applyBatch(c,batch);n+=batch.size();log.write("{\"applied\":"+n+"}\n");}
        }catch(Exception e){c.rollback();throw e;}
        check(n==summary.get("counts").path("planned").asLong(),"Count mismatch");
        save("applied.json",Map.of("schema",SCHEMA,"updated",n,"planSha256",fileHash(path),"changedColumns",List.of("nutrition_basis_raw")));
        System.out.println("NUTRITION applied "+n);
    }
    static void applyBatch(Connection c,List<Change> batch)throws Exception{
        var live=new HashMap<String,Product>();for(var p:query(c,batch.stream().map(Change::barcode).toList(),true))live.put(p.getBarcode(),p);
        for(var x:batch){Product p=live.get(x.barcode());check(p!=null && Objects.equals(p.getProductId(),x.productId()) && signature(p).equals(x.signature()) && p.getNutritionBasisRaw()==null,"Product changed before apply: "+x.barcode());}
        try(var s=c.prepareStatement("UPDATE products SET nutrition_basis_raw=? WHERE barcode=? AND product_id=? AND nutrition_basis_raw IS NULL")){
            for(var x:batch){s.setString(1,x.basis());s.setString(2,x.barcode());s.setLong(3,x.productId());s.addBatch();}for(int n:s.executeBatch())check(n==1,"Update count mismatch");
        }
        for(var p:query(c,batch.stream().map(Change::barcode).toList(),false)){
            var x=batch.stream().filter(y->y.barcode().equals(p.getBarcode())).findFirst().orElseThrow();
            check(x.basis().equals(p.getNutritionBasisRaw()),"Read-after-write mismatch");
        }c.commit();
    }
    static void verify(Connection c)throws Exception{
        requireV17(c);c.setReadOnly(true);
        var samples=new ArrayList<Object>();for(var p:query(c,List.of("8801019311673","8801019312137"),false)){
            var n=p.getNutrition();check(n.getPerPackage()!=null && Double.valueOf(220).equals(n.getPerPackage().getValues().getEnergyKcal()),"Pocky must be 220kcal");
            samples.add(Map.of("barcode",p.getBarcode(),"productName",p.getProductName(),"energyKcal",p.getEnergyKcal(),"totalWeight",p.getTotalWeight(),"nutrition",n));
        }save("pocky-samples.json",samples);
        long n=0;var status=new TreeMap<String,Long>();var bases=new TreeMap<String,Long>();
        try(var s=c.prepareStatement("SELECT barcode,product_id,nutrition_basis_raw,"+String.join(",",IDENTITY)+" FROM products WHERE nutrition_basis_raw IS NOT NULL")){
            s.setFetchSize(1000);try(var r=s.executeQuery()){while(r.next()){var p=product(r);var nutrition=p.getNutrition();inc(status,nutrition.getPackageCalculationReason()==null?"CALCULATED":nutrition.getPackageCalculationReason());inc(bases,nutrition.getSourceBasis().getStatus());n++;}}
        }save("verification.json",Map.of("schema",SCHEMA,"rowsWithBasis",n,"sourceBasisStatuses",bases,"packageCalculationStatuses",status,"pockyVerified",samples.size()));
        System.out.println("NUTRITION verified "+n+" "+status);
    }
    public static void main(String[] args)throws Exception{
        check(args.length==1 && Set.of("migrate","plan","apply","verify").contains(args[0]),"Use migrate, plan, apply or verify");
        Files.createDirectories(OUT);
        try(var c=connect()){
            switch(args[0]){
                case "migrate" -> {
                    approved();
                    try(var stmt=c.createStatement();var rs=stmt.executeQuery("SELECT version,success FROM flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank DESC LIMIT 1")){
                        check(rs.next() && Set.of("16","17").contains(rs.getString(1)) && rs.getBoolean(2),"Migrate only reviewed V16 or V17 targets");
                    }
                    var result=Flyway.configure().dataSource(System.getenv("NUTRITION_URL"),System.getenv("NUTRITION_USER"),System.getenv("NUTRITION_PASSWORD"))
                        .locations("classpath:db/migration").target("17").load().migrate();
                    requireV17(c);
                    save("migration.json",Map.of("schema",SCHEMA,"executed",result.migrationsExecuted,"target","17"));
                }
                case "plan" -> plan(c);
                case "apply" -> apply(c);
                case "verify" -> verify(c);
                default -> throw new IllegalArgumentException("Unknown action");
            }
        }
    }
}
