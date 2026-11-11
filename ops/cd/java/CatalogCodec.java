import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import org.jjikmuk.backend.domain.product.CatalogAttributePayload;
import org.jjikmuk.backend.domain.product.ProductGroupKeyBuilder;
import tools.jackson.databind.json.JsonMapper;

/** Pure pipe codec. No DB, files, network or application context. */
public final class CatalogCodec {
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        var mapper = JsonMapper.builder().findAndAddModules().build();
        var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line=input.readLine()) != null) {
            if (line.length()>16*1024*1024) throw new IllegalArgumentException();
            var values = mapper.readValue(line, ArrayList.class);
            if (values.size()>500) throw new IllegalArgumentException();
            var outputs = new ArrayList<Map<String,Object>>();
            for (Object item:values) {
                Map<String,Object> value=(Map<String,Object>)item;
                Map<String,Object> row=(Map<String,Object>)value.get("row");
                // MySQL JDBC DOUBLE -> Java Double, including integral-valued doubles.
                for (String name: new String[]{"energy_kcal","carbs_g","protein_g","fat_g","sugar_g","sodium_mg","cholesterol_mg","allergy_data_confidence","nutrition_data_confidence","dietary_data_confidence"})
                    if (row.get(name) instanceof Number number) row.put(name,number.doubleValue());
                String encoded=CatalogAttributePayload.INSTANCE.encode(row);
                var output=new LinkedHashMap<String,Object>();
                output.put("payload_json",encoded);
                output.put("payload_hash",CatalogAttributePayload.INSTANCE.hash(encoded));
                output.put("changed_fields",String.join(",",CatalogAttributePayload.INSTANCE.changedFields((String)value.get("previous"),encoded)));
                output.put("group_key",ProductGroupKeyBuilder.INSTANCE.build((String)row.get("product_name"),(String)row.get("manufacturer"),(String)row.get("raw_materials"),(String)row.get("image_url")));
                outputs.add(output);
            }
            System.out.println(mapper.writeValueAsString(outputs));
        }
    }
}
