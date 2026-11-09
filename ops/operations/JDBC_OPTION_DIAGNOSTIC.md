# Read the option names that blocked commissioning

Both fixed commissioning attempts stopped before opening a DB connection with `JDBC_OPTIONS_REQUIRES_REVIEW`. The second attempt supports the historical institution trust-store profile, so the current file still has an unrecognized name or duplicate decoded key. The reports intentionally did not export the names. Do not guess another allowlist expansion or rerun either consumed plan.

`plans/commissioning-jdbc-option-names.json` is a separate **pending** plan for one backend-host observation through the existing operations connection. It creates a content-addressed SSM document and private execution receipts. It uses isolated system Python to load the hash-bound probe helpers and diagnostic from the SSM command into memory. It does not create a new staging directory, download a library, install anything, connect to a database, run SQL, restart services or deploy.

SSM still creates its normal agent work files and execution logs. No application configuration or service file is written by this diagnostic.

The diagnostic verifies the fixed running backend JAR, service/user/cwd/argv and fixed properties file. It accepts only the institution DB host, port and schema as the observed file target. It reports decoded option **names and occurrence counts**, never their values, passwords, raw URL or configuration hashes. Names have a bounded ASCII identifier format; malformed names are withheld and counted. At most 64 pairs are parsed. Exact duplicates and case variants are counted separately. It compares the process identity, environment/properties bytes and JAR again before emitting the report.

`file_options_only=true` means these are observations of the designated properties file, not proof of the application's effective DB configuration or a new acceptance policy. `deployment_ready=false` remains fixed. A diagnostic `OK` is not DB compatibility, installation or deployment approval. A failed report must stop; retain the old stages and all receipts.

The old `commissioning-readiness.json` and `commissioning-readiness-tls.json` remain unchanged. Only after a new explicit approval may the new plan's two approval-marker fields be finalized, CI rerun and its exact main command dispatched once. No CloudShell input, session download, IAM change or account switch is needed.

Validation commands:

```text
PYTHONPATH=ops/operations:ops/cd python3 -B ops/operations/jdbc_diagnostic_document.py --check
PYTHONPATH=ops/operations:ops/cd python3 -B -m unittest discover -s ops/operations/tests -q
```

Tests use synthetic configuration and mocks only. They cover output value redaction, wrong DB target refusal, duplicate/case-variant counts, malformed names and pair limits, observation stability, exception redaction and pending plan generation. Live execution has not been authorized or performed.
