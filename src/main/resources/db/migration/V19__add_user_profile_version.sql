-- Revision for editable self-profile fields and explicit profile completion.
-- Existing values/identities/auth sessions are preserved. V18 remains a separate migration.
ALTER TABLE users ADD COLUMN profile_version BIGINT NOT NULL DEFAULT 0;
