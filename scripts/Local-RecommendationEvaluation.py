"""Local-only recommendation benchmark operations; no remote hosts or credential output.

Generated evidence/results belong outside Git. Product data is never updated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import zipfile
from datetime import datetime
import secrets

BACKEND = Path(__file__).resolve().parents[1]
MYSQL_BIN = Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin")


def properties(path):
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith(("#", "!")) and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def resolve(value):
    def replacement(match):
        key, separator, default = match[1].partition(":")
        if key in os.environ:
            return os.environ[key]
        if separator:
            return default
        raise ValueError(f"Missing environment variable {key}")
    return re.sub(r"\$\{([^}]+)\}", replacement, value)


class LocalDatabase:
    def __init__(self):
        self.config = properties(BACKEND / "src/main/resources/application.properties")
        self.config.update(properties(BACKEND / "application-local.properties"))
        url = resolve(self.config["spring.datasource.url"])
        match = re.fullmatch(r"jdbc:mysql://([^/:?]+)(?::(\d+))?/([A-Za-z0-9_]+)(?:\?.*)?", url)
        if not match or match[1] not in ("localhost", "127.0.0.1") or match[3] != "jjikmuk":
            raise ValueError("Only the configured local jjikmuk database is allowed")
        self.port = int(match[2] or 3306)
        self.username = resolve(self.config["spring.datasource.username"])
        self.password = resolve(self.config["spring.datasource.password"])
        self.identity = self.select("SELECT JSON_OBJECT('hostname',@@hostname,'uuid',@@server_uuid,"
            "'version',VERSION(),'database',DATABASE(),'port',@@port)")[0]
        if self.identity["hostname"].lower() != socket.gethostname().lower():
            raise ValueError("MySQL hostname is not this PC; tunnels/remote servers are prohibited")

    def environment(self):
        env = dict(os.environ)
        env["MYSQL_PWD"] = self.password
        return env

    def args(self, executable="mysql.exe"):
        return [str(MYSQL_BIN / executable), "--no-defaults", "--protocol=TCP", "--host=127.0.0.1",
            f"--port={self.port}", f"--user={self.username}", "--default-character-set=utf8mb4"]

    def execute(self, sql, timeout=180):
        result = subprocess.run(self.args() + ["--database=jjikmuk", "--batch", "--raw", "--skip-column-names"],
            input=sql, encoding="utf-8", errors="replace", capture_output=True, env=self.environment(), timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.replace(self.password, "[REDACTED]")[:2000])
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def select(self, sql):
        if not re.match(r"^\s*SELECT\b", sql, re.I) or ";" in sql:
            raise ValueError("One SELECT statement only")
        return self.execute("SET SESSION MAX_EXECUTION_TIME=120000; START TRANSACTION READ ONLY;\n" + sql + ";\nROLLBACK;")

    def backup(self, output):
        output.mkdir(parents=True, exist_ok=True)
        dump = output / "pre-migration-private-backup.sql"
        if dump.exists():
            raise ValueError("Refusing to overwrite a backup")
        tables = ["users", "email_verifications", "flyway_schema_history",
            "product_recommendation_evaluation_cases", "product_recommendation_evaluation_runs",
            "product_recommendation_evaluation_results"]
        with dump.open("xb") as target:
            result = subprocess.run(self.args("mysqldump.exe") + ["--single-transaction", "--skip-lock-tables",
                "--no-tablespaces", "--set-gtid-purged=OFF", "--hex-blob", "jjikmuk"] + tables,
                stdout=target, stderr=subprocess.PIPE, env=self.environment(), timeout=180)
        if result.returncode:
            raise RuntimeError("Backup failed; do not use incomplete backup")
        metadata = {"server": self.identity, "tables": tables, "file": str(dump),
            "bytes": dump.stat().st_size, "sha256": hashlib.sha256(dump.read_bytes()).hexdigest()}
        save(output / "backup-metadata.json", metadata)
        return metadata


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def inspect(db):
    return {"server": db.identity,
        "migrations": db.select("SELECT JSON_OBJECT('version',version,'success',success,'script',script) FROM flyway_schema_history ORDER BY installed_rank"),
        "counts": {table: db.select(f"SELECT JSON_OBJECT('n',COUNT(*)) FROM {table}")[0]["n"] for table in
            ["products", "product_neighbor_sets", "users", "histories", "email_verifications",
             "product_recommendation_evaluation_cases", "product_recommendation_evaluation_runs"]},
        "account_migration_impact": db.select("SELECT JSON_OBJECT('duplicate_nicknames',"
            "(SELECT COUNT(*) FROM (SELECT LOWER(TRIM(nickname)) AS n FROM users GROUP BY n HAVING COUNT(*)>1) t),"
            "'legacy_google_prefix',(SELECT COUNT(*) FROM users WHERE nickname LIKE '구글유저_%'))"),
        "origins": db.select("SELECT JSON_OBJECT('allergy',allergy_evidence_level,'diet',dietary_data_origin,"
            "'nutrition',nutrition_data_origin,'n',COUNT(*)) FROM products GROUP BY allergy_evidence_level,dietary_data_origin,nutrition_data_origin"),
        "evaluation_cases": db.select("SELECT JSON_OBJECT('id',case_id,'active',active) FROM product_recommendation_evaluation_cases"),
        "indexes": db.select("SELECT JSON_OBJECT('name',INDEX_NAME,'column',COLUMN_NAME,'type',INDEX_TYPE) "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='products'")}


PRODUCT_COLUMNS = ["barcode", "product_name", "manufacturer", "raw_materials", "allergy", "allergy_warning",
    "food_type", "food_categories", "allergy_classification", "total_weight", "allergy_evidence_level",
    "dietary_data_origin", "dietary_data_confidence", "nutrition_data_origin", "nutrition_data_confidence",
    "sugar_g", "sodium_mg", "energy_kcal", "protein_g", "fat_g", "is_vegan", "is_low_sugar", "is_gluten_free"]


def product_json(alias="p"):
    return "JSON_OBJECT(" + ",".join(f"'{column}'," +
        (f"CAST({alias}.{column} AS UNSIGNED)" if column.startswith("is_") else f"{alias}.{column}")
        for column in PRODUCT_COLUMNS) + ")"


def quote(value):
    # SQL hex literals avoid SQL-mode-dependent string escaping.
    return "_utf8mb4 0x" + value.encode("utf-8").hex() if value else "''"


def seeds(db):
    results = []
    for term in ["포키", "새우깡", "포카칩", "두유", "초코파이", "두부", "라면", "사이다", "오트", "요거트", "김치", "현미"]:
        rows = db.select("SELECT JSON_OBJECT('product'," + product_json() + ",'neighbors',n.recommendations) FROM products p "
            "JOIN product_neighbor_sets n ON n.source_barcode=p.barcode "
            f"WHERE LOCATE({quote(term)},p.product_name)>0 AND p.barcode REGEXP '^[0-9]{{13}}$' LIMIT 2")
        results.append({"term": term, "rows": rows})
    return results


REFERENCE_BARCODES = ["8801019309830", "8801043004107", "8801117678302", "4580372910412",
    "8801062007394", "0000088001494", "8801056001261", "8800251190022", "3150012065201", "2000000021345"]


def collect(db):
    references = db.select("SELECT JSON_OBJECT('product'," + product_json() +
        ",'neighbors',n.recommendations,'model',n.model_version) FROM products p "
        "JOIN product_neighbor_sets n ON n.source_barcode=p.barcode WHERE p.barcode IN (" +
        ",".join(quote(b) for b in REFERENCE_BARCODES) + ")")
    wanted = sorted({part.split('|')[0] for ref in references for part in ref["neighbors"].split(',')})
    candidates = []
    for offset in range(0, len(wanted), 200):
        candidates.extend(db.select("SELECT " + product_json() + " FROM products p WHERE p.barcode IN (" +
            ",".join(quote(b) for b in wanted[offset:offset + 200]) + ")"))
    return {"server": db.identity, "references": references, "candidates": candidates,
        "missing_candidates": sorted(set(wanted) - {p["barcode"] for p in candidates})}


def verify_benchmark(db, manifest_path, snapshot_path):
    if snapshot_path is None:
        raise ValueError("--snapshot is required to verify unchanged evaluation inputs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != manifest["evidence_sha256"]:
        raise ValueError("Frozen evidence hash mismatch")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    current = collect(db)
    for key, item_key in [("references", lambda x: x["product"]["barcode"]), ("candidates", lambda x: x["barcode"])]:
        if {item_key(x): x for x in snapshot[key]} != {item_key(x): x for x in current[key]}:
            raise ValueError("Product/neighbor evidence changed since labeling")
    definitions = db.select("SELECT JSON_OBJECT('id',c.case_id,'reference',c.reference_barcode,"
        "'expected',c.expected_relevant_barcodes,'outcome',c.expected_outcome,'forbidden',c.forbidden_barcodes,"
        "'email',u.email,'allergies',u.allergies,'diet',u.special_diet,'diseases',u.diseases,"
        "'disliked',u.disliked_ingredients,'histories',(SELECT COUNT(*) FROM histories h WHERE h.user_id=u.id)) "
        "FROM product_recommendation_evaluation_cases c JOIN users u ON u.id=c.user_id WHERE c.active=TRUE")
    by_id = {d["id"]: d for d in definitions}
    if set(by_id) != {c["case_id"] for c in manifest["cases"]}:
        raise ValueError("Active cases do not match the frozen pilot")
    for case in manifest["cases"]:
        row = by_id[case["case_id"]]
        profile = manifest["profiles"][case["profile"]]
        expected = {"reference": case["reference_barcode"], "outcome": case["expected_outcome"],
            "expected": ",".join(case["expected_relevant_barcodes"]),
            "forbidden": ",".join(case["forbidden_barcodes"]),
            "email": "local-benchmark-20261023-" + case["profile"] + "@example.invalid",
            "allergies": profile["allergies"], "diet": profile["specialDiet"],
            "diseases": None, "disliked": None, "histories": 0}
        if any(row[k] != value for k, value in expected.items()):
            raise ValueError("Evaluation label/profile/history changed: " + case["case_id"])
    return {"manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "evidence_sha256": manifest["evidence_sha256"], "cases_verified": len(definitions),
        "references_verified": len(current["references"]), "candidates_verified": len(current["candidates"]),
        "server": db.identity}


def run_java(db, action, output, manifest_path, snapshot_path=None):
    output.mkdir(parents=True, exist_ok=True)
    if action == "migrate":
        metadata_path = output / "backup/backup-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        backup = Path(metadata["file"])
        if metadata["server"]["uuid"] != db.identity["uuid"] or hashlib.sha256(backup.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError("Backup identity/hash mismatch")
    runtime = output / "java-runtime"
    jar = BACKEND / "build/libs/backend-0.0.1-SNAPSHOT.jar"
    # Extract only known boot classpath entries under our dedicated output directory.
    with zipfile.ZipFile(jar) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or not entry.filename.startswith(("BOOT-INF/lib/", "BOOT-INF/classes/")):
                continue
            target = (runtime / entry.filename).resolve()
            if not target.is_relative_to(runtime.resolve()):
                raise ValueError("Unsafe archive entry")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))
    url = f"jdbc:mysql://127.0.0.1:{db.port}/jjikmuk?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Seoul&characterEncoding=UTF-8"
    env = db.environment()
    env.update(LOCAL_EVAL_URL=url, LOCAL_EVAL_USER=db.username, LOCAL_EVAL_PASSWORD=db.password,
        LOCAL_EVAL_UUID=db.identity["uuid"], LOCAL_EVAL_HOST=db.identity["hostname"],
        LOCAL_EVAL_AUDIT=str(output / "evaluation-events.json"))
    if action == "evaluate":
        save(output / "input-verification.json", verify_benchmark(db, manifest_path, snapshot_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        active = {r["id"] for r in db.select("SELECT JSON_OBJECT('id',case_id) FROM product_recommendation_evaluation_cases WHERE active=TRUE")}
        if active != {c["case_id"] for c in manifest["cases"]}:
            raise ValueError("Active cases do not match frozen pilot; refusing to mix datasets")
        if (output / "evaluation-events.json").exists():
            raise ValueError("Refusing to overwrite evaluation audit")
        env["SPRING_APPLICATION_JSON"] = json.dumps({
            "spring.profiles.active": "recommendation-evaluation",
            "spring.datasource.url": url, "spring.datasource.username": db.username, "spring.datasource.password": db.password,
            "spring.flyway.url": url, "spring.flyway.user": db.username, "spring.flyway.password": db.password,
            "spring.flyway.target": "13", "spring.jpa.hibernate.ddl-auto": "validate",
            "spring.main.web-application-type": "servlet", "server.address": "127.0.0.1", "server.port": 0,
            "product.import.enabled": False, "product.import.rollback.enabled": False,
            "recommendation.import.enabled": False, "product.search.backfill.enabled": False,
            "product.search.evaluation.enabled": False, "product.data-model.backfill.enabled": False,
            "product.search.mode": "locate", "product.search.logging.enabled": False,
            "recommendation.logging.enabled": False, "recommendation.evaluation.enabled": True,
            "recommendation.evaluation.dataset-version": manifest["dataset_version"],
            "recommendation.evaluation.limit": 10, "recommendation.evaluation.min-similarity-score": 0.2,
            "recommendation.evaluation.minimum-hit-rate": 0.30, "recommendation.evaluation.minimum-ndcg": 0.15,
            "recommendation.evaluation.maximum-p95-ms": 1000,
            "recommendation.evaluation.maximum-verification-required-rate": 1.0,
            "recommendation.evaluation.maximum-unexpected-empty-response-rate": 0.0})
    java = r"C:\Program Files\Android\Android Studio\jbr\bin\java.exe"
    classpath = str(runtime / "BOOT-INF/classes") + os.pathsep + str(runtime / "BOOT-INF/lib/*")
    log = output / (action + ".log")
    if log.exists():
        log = output / (action + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
    process = subprocess.run([java, "-Dfile.encoding=UTF-8", "--class-path", classpath,
        str(BACKEND / "scripts/LocalRecommendationEvaluation.java"), action],
        cwd=BACKEND, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=240)
    # Avoid propagating credential values even on startup failure.
    content = (process.stdout + "\n" + process.stderr).replace(db.password, "[REDACTED]")
    log.write_text(content, encoding="utf-8")
    return {"operation": action, "exit_code": process.returncode, "log": str(log), "server": db.identity}


def seed_benchmark(db, manifest_path, snapshot_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != manifest["evidence_sha256"]:
        raise ValueError("Frozen evidence hash mismatch")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    current = collect(db)
    for key, item_key in [("references", lambda x: x["product"]["barcode"]), ("candidates", lambda x: x["barcode"])]:
        if {item_key(x): x for x in snapshot[key]} != {item_key(x): x for x in current[key]}:
            raise ValueError("Product/neighbor evidence changed since labeling")
    if db.select("SELECT JSON_OBJECT('n',COUNT(*)) FROM product_recommendation_evaluation_cases")[0]["n"]:
        raise ValueError("Evaluation cases already exist; do not overwrite or mix benchmarks")
    version = db.select("SELECT JSON_OBJECT('v',MAX(CAST(version AS UNSIGNED))) FROM flyway_schema_history WHERE success=TRUE")[0]["v"]
    if version != 13:
        raise ValueError("Successful V13 migration required")
    prefix = "local-benchmark-20261023-"
    if db.select("SELECT JSON_OBJECT('n',COUNT(*)) FROM users WHERE email LIKE " + quote(prefix + "%@example.invalid"))[0]["n"]:
        raise ValueError("Synthetic accounts already exist; refusing duplicates")
    statements = ["START TRANSACTION"]
    for index, (profile, values) in enumerate(manifest["profiles"].items(), 1):
        email = prefix + profile + "@example.invalid"
        # Non-deliverable email and non-bcrypt random password; no usable login secret is created.
        statements.append("INSERT INTO users(email,nickname,allergies,diseases,password,role,auth_provider,profile_completed,token_version,special_diet,disliked_ingredients) VALUES (" +
            ",".join([quote(email), quote(f"평가20261023_{index}"), quote(values["allergies"]), "NULL",
                quote("BENCHMARK_DISABLED_" + secrets.token_hex(32)), "'USER'", "'GOOGLE'", "TRUE", "0",
                quote(values["specialDiet"]), "NULL"]) + ")")
        statements.append(f"SET @benchmark_user_{index} = LAST_INSERT_ID()")
        for case in manifest["cases"]:
            if case["profile"] != profile:
                continue
            statements.append("INSERT INTO product_recommendation_evaluation_cases "
                "(case_id,user_id,reference_barcode,expected_relevant_barcodes,expected_outcome,forbidden_barcodes,notes,active) VALUES (" +
                ",".join([quote(case["case_id"]), f"@benchmark_user_{index}", quote(case["reference_barcode"]),
                    quote(",".join(case["expected_relevant_barcodes"])), quote(case["expected_outcome"]),
                    quote(",".join(case["forbidden_barcodes"])), quote("AI-assisted pilot; " + case["judgment_reason"]), "TRUE"]) + ")")
    statements.append("COMMIT")
    db.execute(";\n".join(statements) + ";")
    return {"manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "synthetic_users": db.select("SELECT JSON_OBJECT('id',id,'email',email,'allergies',allergies,'specialDiet',special_diet) "
            "FROM users WHERE email LIKE " + quote(prefix + "%@example.invalid") + " ORDER BY id"),
        "cases_created": len(manifest["cases"]), "product_writes": 0}


def results(db):
    result = {"server": db.identity}
    for table in ["product_recommendation_evaluation_runs", "product_recommendation_evaluation_results"]:
        columns = db.select("SELECT JSON_OBJECT('name',COLUMN_NAME) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=" + quote(table) + " ORDER BY ORDINAL_POSITION")
        expression = "JSON_OBJECT(" + ",".join(f"'{c['name']}',`{c['name']}`" for c in columns) + ")"
        result[table] = db.select("SELECT " + expression + " FROM " + table + " ORDER BY 1")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "query", "backup", "seeds", "collect", "migrate", "evaluate", "seed-benchmark", "results"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sql-file", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--confirm-local-write", action="store_true")
    args = parser.parse_args()
    db = LocalDatabase()
    if args.action in ("migrate", "evaluate"):
        if not args.confirm_local_write:
            raise ValueError("Explicit --confirm-local-write is required")
        operation = run_java(db, args.action, args.output, args.manifest, args.snapshot)
        print(json.dumps(operation, ensure_ascii=False))
        sys.exit(operation["exit_code"])
    if args.action == "seed-benchmark":
        if not args.confirm_local_write:
            raise ValueError("Explicit --confirm-local-write is required")
        result = seed_benchmark(db, args.manifest, args.snapshot)
    elif args.action == "results":
        result = results(db)
    elif args.action == "inspect":
        result = inspect(db)
    elif args.action == "seeds":
        result = seeds(db)
    elif args.action == "collect":
        result = collect(db)
    elif args.action == "query":
        result = db.select(args.sql_file.read_text(encoding="utf-8-sig").strip().rstrip(';'))
    else:
        result = db.backup(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    save(args.output, result)
    if args.action in ("collect", "seeds", "results"):
        print(json.dumps({"saved": str(args.output), "bytes": args.output.stat().st_size}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
