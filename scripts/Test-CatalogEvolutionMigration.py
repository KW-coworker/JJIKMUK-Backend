"""Test V15/ID preservation/swap in disposable localhost schemas, never the real jjikmuk tables."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_eval", ROOT / "scripts/Local-RecommendationEvaluation.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite test record")
    db = local.LocalDatabase()  # independently verifies loopback host/UUID/PC identity
    suffix = uuid.uuid4().hex[:8]
    created = []
    results = []

    def run(schema, sql):
        assert schema == "information_schema" or re.fullmatch(r"jjikmuk_v15_test_[a-f0-9]{8}_(new|legacy)", schema)
        result = subprocess.run(db.args() + ["--database=" + schema, "--batch", "--raw", "--skip-column-names"],
            input=sql, encoding="utf-8", capture_output=True, env=db.environment(), timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr.replace(db.password, "[REDACTED]")[:1000])
        return result.stdout

    try:
        for mode in ("new", "legacy"):
            schema = f"jjikmuk_v15_test_{suffix}_{mode}"
            # CREATE (without IF NOT EXISTS) guarantees we never take ownership of an existing schema.
            run("information_schema", f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            created.append(schema)
            pid = ", product_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT UNIQUE" if mode == "legacy" else ""
            run(schema, "CREATE TABLE products (barcode VARCHAR(255) PRIMARY KEY" + pid + ") ENGINE=InnoDB;"
                "CREATE TABLE histories(id BIGINT AUTO_INCREMENT PRIMARY KEY,barcode VARCHAR(255)) ENGINE=InnoDB;"
                "INSERT INTO products(barcode) VALUES ('00001'),('NO_BARCODE_ROW_1');")
            migration = (ROOT / "src/main/resources/db/migration/V15__expand_product_ids_and_attribute_history.sql").read_text(encoding="utf-8")
            run(schema, migration)
            if mode == "new":
                run(schema, "ALTER TABLE products ADD UNIQUE INDEX uk_products_product_id(product_id),ALGORITHM=INPLACE,LOCK=NONE;"
                    "UPDATE products SET product_id=CASE barcode WHEN '00001' THEN 1 ELSE 2 END;")
            run(schema, "UPDATE product_id_sequence SET next_id=1003 WHERE sequence_name='products';"
                "CREATE TABLE products_staging LIKE products; ALTER TABLE products_staging AUTO_INCREMENT=1001;"
                "INSERT INTO products_staging(barcode) VALUES ('00001'),('NO_BARCODE_ROW_1');")
            if mode == "new":
                run(schema, "UPDATE products_staging SET product_id=CASE barcode WHEN '00001' THEN 1001 ELSE 1002 END;")
            run(schema, "UPDATE products_staging staged INNER JOIN products live ON live.barcode=staged.barcode "
                "SET staged.product_id=live.product_id,staged.attribute_snapshot_id=live.attribute_snapshot_id "
                "WHERE LEFT(staged.barcode,15)<>'NO_BARCODE_ROW_' AND live.product_id IS NOT NULL;")
            # Validate both branches and atomic table swap without changing sequence/snapshot tables.
            before = json.loads(run(schema, "SELECT JSON_OBJECT('real',(SELECT product_id FROM products_staging WHERE barcode='00001'),"
                "'synthetic',(SELECT product_id FROM products_staging WHERE barcode='NO_BARCODE_ROW_1'));").strip())
            assert before["real"] == 1 and before["synthetic"] > 2, before
            run(schema, "RENAME TABLE products TO products_rollback,products_staging TO products;"
                "RENAME TABLE products TO products_swap,products_rollback TO products,products_swap TO products_rollback;")
            after = json.loads(run(schema, "SELECT JSON_OBJECT('database',DATABASE(),'nextId',(SELECT next_id FROM product_id_sequence WHERE sequence_name='products'),"
                "'real',(SELECT product_id FROM products WHERE barcode='00001'),'snapshots',(SELECT COUNT(*) FROM product_attribute_snapshots));").strip())
            assert after["database"] == schema and after["nextId"] == 1003 and after["real"] == 1
            results.append({"mode": mode, "passed": True, "checks": ["V15", "nullable_or_existing_autoincrement", "real_id_preserved", "synthetic_id_not_reused", "swap_rollback", "sequence_not_rolled_back"]})
    finally:
        for schema in created:
            assert schema in created and schema.startswith(f"jjikmuk_v15_test_{suffix}_")
            run("information_schema", f"DROP DATABASE `{schema}`;")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"mysql_version": db.identity["version"], "results": results,
        "temporary_schemas_removed": created, "source_jjikmuk_writes": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
