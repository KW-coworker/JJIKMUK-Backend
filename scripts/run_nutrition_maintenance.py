"""Run the reviewed JAR's nutrition maintenance without starting Spring.

Credentials are supplied via NUTRITION_USER / NUTRITION_PASSWORD, never CLI arguments.
See docs/api-spec/v17-deployment-checklist.md before any write action.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("migrate", "plan", "apply", "verify"))
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--java", default="java", help="Java 21 executable")
    args = parser.parse_args()
    required = ["NUTRITION_URL", "NUTRITION_SCHEMA", "NUTRITION_UUID", "NUTRITION_HOST",
                "NUTRITION_USER", "NUTRITION_PASSWORD"]
    if args.action in ("plan", "apply"):
        required += ["NUTRITION_CSV"]
    if args.action in ("migrate", "apply"):
        required += ["NUTRITION_WRITE_APPROVAL"]
        if os.environ.get("NUTRITION_WRITE_APPROVAL") != "backup-clone-reviewed":
            parser.error("Write approval requires completed backup and clone review")
    if args.action == "apply":
        required += ["NUTRITION_PLAN_DIR", "NUTRITION_PLAN_SHA256"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        parser.error("Missing environment variable names: " + ", ".join(missing))
    jar = args.jar.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    with jar.open("rb") as stream:
        jar_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    env = os.environ.copy()
    env["NUTRITION_OUTPUT"] = str(output)
    env["NUTRITION_BUILD_SHA256"] = jar_hash
    source = Path(__file__).resolve().with_name("NutritionBasisMaintenance.java")
    with tempfile.TemporaryDirectory(prefix="nutrition-runtime-") as directory:
        root = Path(directory).resolve()
        with zipfile.ZipFile(jar) as archive:
            for entry in archive.infolist():
                if not entry.filename.startswith(("BOOT-INF/classes/", "BOOT-INF/lib/")):
                    continue
                if not (root / entry.filename).resolve().is_relative_to(root):
                    raise ValueError("Unsafe JAR entry")
                archive.extract(entry, root)
        classpath = os.pathsep.join((str(root / "BOOT-INF/classes"), str(root / "BOOT-INF/lib/*")))
        result = subprocess.run([args.java, "--class-path", classpath, str(source), args.action], env=env)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
