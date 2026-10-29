"""Run opt-in tests with loopback-only credentials in child environment, never command arguments."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--original-manifest", type=Path, required=True)
    args = parser.parse_args()
    out = args.directory.resolve()
    for name in ["recommendation-results.json", "search-results.json", "search-progress.jsonl"]:
        if (out / name).exists(): raise ValueError("Refusing to overwrite prior benchmark run: " + name)
    spec = importlib.util.spec_from_file_location("local_eval", ROOT / "scripts/Local-RecommendationEvaluation.py")
    local = importlib.util.module_from_spec(spec); spec.loader.exec_module(local)
    db = local.LocalDatabase()
    env = dict(os.environ)
    env.update(JAVA_HOME=r"C:\Program Files\Java\jdk-21", JJIKMUK_BENCHMARK_DIR=str(out),
        JJIKMUK_ORIGINAL_BENCHMARK=str(args.original_manifest.resolve()), JJIKMUK_ORIGINAL_EVIDENCE=str(out / "original-enriched-evidence.json"),
        JJIKMUK_SEARCH_JDBC=f"jdbc:mysql://127.0.0.1:{db.port}/jjikmuk?useSSL=false&allowPublicKeyRetrieval=true&characterEncoding=UTF-8",
        JJIKMUK_SEARCH_USER=db.username, JJIKMUK_SEARCH_PASSWORD=db.password, JJIKMUK_SEARCH_UUID=db.identity["uuid"])
    command = [str(ROOT / "gradlew.bat"), "test", "--tests", "*ExpandedOfflineBenchmarkTest", "--no-daemon", "--console=plain"]
    with (out / "execution.log").open("x", encoding="utf-8") as log:
        proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            safe = line.replace(db.password, "[REDACTED]") if db.password else line
            log.write(safe); log.flush(); print(safe, end="", flush=True)
        sys.exit(proc.wait())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
