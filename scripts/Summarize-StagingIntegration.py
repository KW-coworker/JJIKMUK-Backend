"""Collect non-secret version fingerprints and JUnit evidence for an isolated audit."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8").strip()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_fingerprint(root, paths):
    files = [{"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": digest(p)} for p in sorted(paths) if p.is_file()]
    return {"fileCount": len(files), "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), "files": files}


def junit(paths):
    counts = dict(tests=0, passed=0, skipped=0, failures=0, errors=0)
    cases = []
    for path in paths:
        root = ET.parse(path).getroot()
        for suite in ([root] if root.tag == "testsuite" else root.findall("testsuite")):
            for key in ["tests", "skipped", "failures", "errors"]:
                counts[key] += int(suite.get(key, 0))
            for case in suite.findall("testcase"):
                result = "failed" if case.find("failure") is not None else "error" if case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
                cases.append({"class": case.get("classname"), "name": case.get("name"), "result": result})
    counts["passed"] = counts["tests"] - counts["skipped"] - counts["failures"] - counts["errors"]
    return {**counts, "cases": cases}


def main():
    p = argparse.ArgumentParser()
    for key in ["backend", "android", "remote-repository", "output"]:
        p.add_argument("--" + key, type=Path, required=True)
    args = p.parse_args()
    backend, android, out = args.backend.resolve(), args.android.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    ai = backend.parent / "AI"
    paths = [backend / name for name in git(backend, "ls-files", "--cached", "--others", "--exclude-standard", ".").splitlines()
             if name.endswith((".kt", ".kts", ".sql", ".properties", ".py")) and "__pycache__" not in name and "local.properties" not in name]
    # git ls-files from a subdirectory yields paths relative to that directory.
    manifest = {"createdAt": datetime.now(timezone.utc).isoformat(), "scope": "LOCAL_ISOLATED_WRITE_REMOTE_GET_ONLY",
                "remoteDeploymentChanged": False, "mysqlChanged": False, "mergedOrPushed": False,
                "backend": {"head": git(backend, "rev-parse", "HEAD"), "workingTreeModified": True,
                            "source": source_fingerprint(backend, paths),
                            "jarSha256": digest(backend / "build/libs/backend-0.0.1-SNAPSHOT.jar"),
                            "schemaFilesUpTo": "V14", "mysqlMigrationsExecuted": False},
                "android": {"branch": "feature/product-search", "head": git(android, "rev-parse", "HEAD"),
                            "productionSourceChanged": False, "contractHarnessAdded": True,
                            "apkSha256": digest(android / "app/build/outputs/apk/debug/app-debug.apk")},
                "remoteRepository": {"head": git(args.remote_repository, "rev-parse", "HEAD"), "aiCodeFound": False, "migrationFilesUpTo": "V12"},
                "localAi": {"source": source_fingerprint(ai, list((ai / "app").rglob("*.py"))), "latestTeamVersionConfirmed": False},
                "remoteRuntime": json.loads((out / "network-observation.json").read_text(encoding="utf-8")),
                "tests": {"backend": junit((backend / "build/test-results/test").glob("*.xml")),
                          "androidBaseline": junit((out / "android-baseline/junit").glob("*.xml")),
                          "androidNewContract": junit((android / "app/build/test-results/testDebugUnitTest").glob("*.xml")),
                          "localAi": junit([out / "ai-tests.xml"])}}
    for source, destination in [(backend / "build/integration/core-flow-samples.json", "core-flow-samples.json"),
                                (backend / "build/integration/core-http-checks.json", "core-http-checks.json"),
                                (android / "app/src/test/java/com/coworker/jjikmuk/data/repository/BackendSnapshotContractTest.kt", "BackendSnapshotContractTest.kt")]:
        shutil.copy2(source, out / destination)
    for source, destination in [(backend / "build/test-results/test", "backend-junit"),
                                (android / "app/build/test-results/testDebugUnitTest", "android-contract-junit")]:
        (out / destination).mkdir(exist_ok=True)
        for file in source.glob("*.xml"):
            shutil.copy2(file, out / destination / file.name)
    (out / "version-and-test-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: {k: v for k, v in value.items() if k != "cases"} for key, value in manifest["tests"].items()}))
    print("Backend source SHA-256:", manifest["backend"]["source"]["sha256"])


if __name__ == "__main__":
    main()
