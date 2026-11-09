# Unified server access and application CD

User-authorized scope: prepare code, tests and PRs. No AWS changes, remote server
commands, initial installations, deployments or activation until explicit approval.
The human's final CloudShell setup must include all required roles and documents;
normal subsequent operations must not require credential downloads or account switching.

## Architecture

- Keep backend source in KW-coworker/JJIKMUK-Backend/main and chatbot source in
  Alphrit/jjikmuk-CO-WORKER-/chatbot. Never patch application source on the server.
- Backend and chatbot have separate automatic roles, fixed SSM documents, private
  artifact prefixes and activation variables. Both deploy on protected-branch push
  after tests, with no deployment reviewer after initial activation.
- One root-owned host lock serializes application transitions and approved DB/OCR
  operations. Repository-specific Actions concurrency alone is insufficient.
- Manual operations are requested through the backend's production environment.
  Private OCR/SQL/package content stays outside GitHub, identified by version and
  SHA256. A public approval record contains only scope and immutable references.
- Existing schema, API contract, runtime configuration and RAG compatibility are
  gates. CD never migrates production DB or rebuilds embeddings. Incompatibility
  means stop, report why, and preserve the running version.
- Chatbot releases use exact tracked AI source and a verified Linux runtime bundle.
  Preserve conversation data, RAG indices, budgets, nonce records and secrets.
- Failure notifications show sanitized codes, known server outcome and next owner
  action. Mention fisfin, associated PR author and merger; no raw remote logs.
  Unknown outcomes never become 'old server unchanged'.
- Initial approval establishes scoped ongoing automation; ordinary code pushes do
  not need a second chat approval. DB/OCR/config changes remain explicit operations.

## Deliverables and acceptance

1. Connection/manual runner: one reproducible CloudFormation setup, exact OIDC
   identity checks for both repos, bounded private package input, useful read-only
   service/source inspection. Offline IAM/SSM shape and denial tests pass.
2. Notifications/backend: failure/rejection/rollback reach a dedicated notification
   job even when build fails; existing backend tests remain green and no silent
   pass for failed inspection/collection.
3. Chatbot package/host: immutable source manifest, supported runtime, DB/RAG and
   API compatibility gates, bounded switch/verification/conditional rollback.
4. Chatbot Actions: no application source edits, full offline AI tests, exact
   source packaging, source branch and immutable controller binding, OFF default.
5. Review: Windows and Linux tests, workflow/template lint, failure injection,
   hostile archive/path/input tests, independent review and one mutation test.
6. PRs + human runbook: draft PRs with exact tested heads and outstanding real-AWS
   validation. Only after merge/settings/OIDC checks supply a single setup command
   with fixed source/template hashes for user approval.

## Initial known blockers and limits

- GitHub environments for backend already exist; do not recreate them.
- Chatbot branch currently has no Actions or branch protection. Repository admins
  must set its required CI, environment and disabled deployment variable.
- Current backend includes V17; chatbot includes policy_version width SQL. Current
  production DB compatibility has not been verified; no automatic application.
- Initial systemd paths, runtime config, baseline and shared lock installation must
  be reviewed against real server observations after access exists.
- GitHub notifications/email depend on account settings; comments and failed runs
  are auditable delivery records, not proof that a person read a notification.

Local experimental/root tasks are unrelated and remain untouched. Implementation
checkpoints are automated verification; the user's preparation request authorizes
continuing through code and PR publication, not operational activation.
