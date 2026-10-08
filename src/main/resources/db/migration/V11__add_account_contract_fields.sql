-- Preserve existing accounts while enforcing the new account/profile contract.
ALTER TABLE users
    ADD COLUMN auth_provider VARCHAR(32) NOT NULL DEFAULT 'LOCAL',
    ADD COLUMN profile_completed BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN token_version INT NOT NULL DEFAULT 0;

-- Resolve legacy duplicates deterministically before adding the final unique guard.
UPDATE users AS target
JOIN (
    SELECT id, duplicate_rank
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY LOWER(TRIM(nickname))
                ORDER BY id
            ) AS duplicate_rank
        FROM users
    ) AS ranked_users
) AS duplicates ON duplicates.id = target.id
SET target.nickname = CONCAT(LEFT(TRIM(target.nickname), 220), '_', target.id)
WHERE duplicates.duplicate_rank > 1;

ALTER TABLE users
    ADD CONSTRAINT uk_users_nickname UNIQUE (nickname);
