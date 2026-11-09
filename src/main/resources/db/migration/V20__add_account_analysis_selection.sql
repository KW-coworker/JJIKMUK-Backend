-- Persist account toggle choices only. Never import device-local profiles or legacy ON/OFF flags.
-- No backfill: unconfigured accounts retain the existing self-only default.
CREATE TABLE account_analysis_selections (
    owner_id BIGINT NOT NULL PRIMARY KEY,
    include_self BOOLEAN NOT NULL DEFAULT TRUE,
    version BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT fk_analysis_selection_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE account_analysis_selection_families (
    owner_id BIGINT NOT NULL,
    family_profile_id BIGINT NOT NULL,
    PRIMARY KEY (owner_id, family_profile_id),
    CONSTRAINT fk_analysis_selected_settings FOREIGN KEY (owner_id)
        REFERENCES account_analysis_selections(owner_id) ON DELETE CASCADE,
    CONSTRAINT fk_analysis_selected_family FOREIGN KEY (family_profile_id)
        REFERENCES family_profiles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
