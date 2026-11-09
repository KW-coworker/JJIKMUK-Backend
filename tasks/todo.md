# Unified access/CD preparation

- [x] Extend one-time connection for chatbot role/document and private manual work.
  Verify policy isolation, setup consistency and adverse input handling.
- [x] Fix inspection/collection reporting and add source provenance reads.
  Verify secret-free outputs and correct inactive/failed outcomes.
- [x] Add sanitized failure notifications and backend outcome reporting.
  Verify build failure, preflight refusal, rollback, unknown outcome and API failure.
- [x] Implement chatbot source packaging, immutable-runtime gates and host deployment gates.
  Verify hostile artifacts, schema/config/RAG drift, shared lock and rollback.
- [x] Add chatbot CI/CD and required repository configuration instructions.
  Verify exact-source tests/packaging and disabled deployment behavior.
- [x] Validate Linux/Windows, lint workflows/template, inject failures and review.
- [x] Publish draft PRs and inspect their CI; document exact approval boundary.
- [x] Write human setup/application checklist. Do not execute AWS setup.

Server-specific commissioning remains deliberately separate: fresh OIDC inspection,
actual DB/RAG/runtime/config compatibility, reviewed install packages and user approval.
No AWS setup, server installation, paid inference, DB mutation or deployment was run.
Draft backend PR17, chatbot branch PR14 and default-main observer PR15 are unmerged.
Final backend CI is rerun on the last test-fixture correction; see PR checks.
