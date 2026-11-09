# Commissioning observation: observed JDBC option correction (pending approval)

The basic `inspect` workflow has already succeeded. It checks service activity and a Python source digest; it does not establish DB compatibility or installation readiness. This separate, fixed plan collects the next observations through the existing GitHub OIDC connection. No new CloudShell setup or IAM expansion is needed.

The first approved observation ran once in [run 42683718598](https://github.com/KW-coworker/JJIKMUK-Backend/actions/runs/42683718598). It returned `PREFLIGHT_FAILED / JDBC_OPTIONS_REQUIRES_REVIEW` before the DB child or service-metadata collection. Its SSM transport succeeded, while the workflow correctly failed on the report status. The old plan `plans/commissioning-readiness.json`, approval, S3 receipts and stage directory remain preserved; that approval is consumed and must not be replayed.

The institution migration code configured Java trust-store options that the first probe omitted from its JDBC allowlist. Those documented options reproduce the failure locally. The live report did not expose which option names failed, so the exact current options remain unverified. The correction recognizes only the known institution profile: `sslMode=VERIFY_IDENTITY`, the fixed local institution trust-store URL, `PKCS12`, disabled system-store fallback, and a nonempty bounded store password kept in memory. Unknown/duplicate options or a different trust profile still stop. The probe's PyMySQL connection independently retains its fixed PEM CA and certificate/hostname verification. No production JDBC configuration is changed. [Connector/J server-authentication documentation](https://dev.mysql.com/doc/connector-j/en/connector-j-server-authentication.html).

The TLS correction also stopped before DB connection. The separately approved [option-name diagnostic run 42690400943](https://github.com/KW-coworker/JJIKMUK-Backend/actions/runs/42690400943) succeeded and observed eight names, no duplicates, no case variants and no malformed names. `rewriteBatchedStatements` is the only observed name missing from the corrected allowlist. Its actual value was not exported. This is a Connector/J `executeBatch()` rewriting option ([official documentation](https://dev.mysql.com/doc/connector-j/en/connector-j-connp-props-performance-extensions.html)). The new probe recognizes only boolean true/false values, case-insensitively. It never passes this Java option to PyMySQL, enables multi-statements, or changes the fixed read-only SQL.

The new `plans/commissioning-readiness-observed.json` is deliberately **`approved: false`** with a `PENDING_` approval ID. It has a new content-derived stage directory and requires a new explicit one-run approval. Merging these files alone cannot execute it or enable CD. After approval, only its `approved` and `approval_id` fields may change. Its document hash must stay unchanged; repeat CI and verify the exact main before dispatch. The generator verifies all three consumed plans' exact hashes instead of regenerating or overwriting them. The completed diagnostic's `--check` likewise verifies its approved archive because shared helpers have evolved. Do not fabricate approval or dispatch a pending plan.

## Exact scope to approve

- Institution account `076767081522`, Seoul; backend/chatbot instance `i-06350403fe0400e1b` only. No command to the OCR instance.
- Use the existing `JjikmukOperationsExecute` role and `production` environment. Create/verify one content-addressed SSM document and send it once. The existing runner records intent, command ID, and result in private S3, and GitHub retains the sanitized report. No IAM, network, EC2 lifecycle or RDS settings change.
- Create one new `/opt/jjikmuk-readiness-<24 hex>` folder, containing **four files**: two reviewed Python source files, one non-secret contract, and one pinned PyMySQL wheel. The directory is root-owned 0755; files are 0644 and contain no credentials. This is a real but bounded server filesystem write. Existing paths cause a stop; no overwrite, deletion or automatic cleanup.
- Retrieve PyMySQL 1.2.3 from its fixed official `files.pythonhosted.org` URL. Require HTTPS, no proxy/redirect, 46,740 bytes, and SHA256 `14f1c68e2ed859243ae5ca41ffbe677027fc46bc136a9f0be8a4e928e5e7415a` before import. No pip, system Python change, application venv modification or package install.
- Verify the observed backend user/cwd/argv/JAR and read systemd reference paths and ownership/modes. Read the fixed backend process environment and properties only in memory to validate the DB target/overrides. Never emit their raw values. Compare process identities, referenced file metadata, environment/properties bytes and JAR before/after.
- Observe chatbot service executable/work directory, referenced files, requirements digest, `.env` metadata and candidate RAG paths. Do not run/import the chatbot or traverse its venv/RAG contents. Paths derived from process environment/defaults are **not** proof of effective dotenv configuration or RAG readiness.
- Run one DB child as `ubuntu`, with isolated system Python and the verified wheel. Target only `jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com:3306/jjikmuk`, with the existing CA and mandatory TLS certificate/hostname verification. Existing backend DB credentials are consumed on the host, never sent to GitHub or command arguments.

The old JAR must still match `e3dc8ec36dca14dd7d9edfde1c6ed5e5a083073d7b6f00e62159af7f8382f2f1` and preserve `-Dchatbot.developer-test-auto-consent=true`. If it changed, stop and review the new state; do not change the guard to make a deployment pass.

## Fixed SQL and limits

One connection, 5-second connect/write and 10-second read timeouts. Set this session's `MAX_EXECUTION_TIME=10000` and `lock_wait_timeout=5`, then `START TRANSACTION READ ONLY`.

1. Read `information_schema.COLUMNS` for schema `jjikmuk`, at most 4,097 rows; reject more than 4,096.
2. Read `information_schema.STATISTICS` for the same schema, with the same bound.
3. If the migration history table exists, read `version, script, checksum, success, type` from `flyway_schema_history`, at most 102 rows; reject more than 101.
4. Always `ROLLBACK` and close the established connection, including query failures.

No account, chat-message or product data rows are queried. No INSERT/UPDATE/DELETE/DDL, stored procedure, migration, data import, snapshot creation or data repair. A read-only transaction supplements fixed SQL; it does not change the database account's underlying grants.

Output includes booleans for V18–V20 required-column presence, exact migration-history agreement, chatbot policy-version capacity, counts and combined schema/history digests. It contains no raw SQL rows or credentials. Column-presence checks are a triage aid, not full column-type/foreign-key/API compatibility verification.

## Results and failure handling

`status: OK` means the observation completed, **not that deployment is approved or safe**. `checks.deployment_ready` is always false. A DB failure or incomplete metadata is retained as an explicit failed check/code; do not treat workflow success as installation readiness. HTTP, RAG, backups and actual deployment/rollback remain unverified.

The final report is capped at 16 KiB. Path keys and roots are allowlisted. Metadata overflow is rejected before the DB child; each report map retains the runner's 100-entry limit. Exceptions are reduced to fixed codes, with no raw stderr/traceback. SSM and local files are preserved after any uncertain outcome; do not rerun or remove the intent/stage to bypass the once-only guard.

## Verification and preparation sequence

```text
PYTHONPATH=ops/operations:ops/cd python3 -B ops/operations/readiness_document.py --check
PYTHONPATH=ops/operations:ops/cd python3 -B -m unittest discover -s ops/operations/tests -v
```

The tests use simulated DB/downloads only. Linux fixtures exercise directory-FD symlink refusal, FIFO/size limits, restrictive umask, bad downloads and preservation of an existing stage. Additional tests cover TLS settings, one connection, rollback on failure, silent error output, metadata bounds, changed processes/references, and pending approval refusal. No production fault injection.

After these observations, prepare exact disabled-install configuration and artifact hashes, then separately request initial installation/transition approval. Missing DB history/structure requires a separately reviewed manual DB operation. RAG/runtime changes require their own preparation. Preserve GitHub application source; never patch the server or relax gates to fit it.
