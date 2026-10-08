# Product data model — stage 1

This stage uses an expand/migrate/contract strategy so existing barcode APIs,
history rows, and precomputed recommendation data continue to work.

## Decisions

- `barcode` remains the JPA and database primary key during stage 1.
- `product_id` is added as a generated unique internal identifier only through
  the maintenance SQL in `db/operations/add_product_internal_id.sql`.
- The primary-key switch and nullable barcode are deferred until the product
  importer uses a staging-table swap and preserves existing product IDs.
- `product_group_key` is a deterministic SHA-256 key based on the four values
  used by search-card deduplication: name, manufacturer, raw materials, image.
- Provenance is stored by safety-relevant data group rather than one metadata
  row per field. This avoids creating millions of sparse metadata rows.
- Legacy allergy and nutrition data default to `UNKNOWN`. A populated warning
  can be classified as `DECLARED_LABEL`, but only separately reviewed data may
  use `VERIFIED_SOURCE`; no legacy value is given numeric confidence automatically.
- Dietary flags default to `INFERRED` because they were created by the CSV rule
  pipeline. Confidence stays null until the rules are evaluated against a
  reviewed gold set.

## Internal ID transition

1. Complete the stage-1 metadata and group-key rollout.
2. In a measured maintenance window, add `product_id` without changing barcode.
3. Convert the stage-2 product importer from delete/reinsert to staging/upsert,
   preserving `product_id` for a matching barcode or curated product identity.
4. Migrate history and recommendation references to `product_id` while keeping
   barcode lookup as a public alternate key.
5. Only then make `product_id` the primary key and make barcode nullable/unique.
6. Replace `NO_BARCODE_ROW_*` values with null after every consumer supports the
   internal identifier.

## Metadata rollout

1. Flyway adds the nullable group key and provenance columns.
2. New CSV imports populate `product_group_key` automatically.
3. Run a separate one-off process with `PRODUCT_DATA_MODEL_BACKFILL_ENABLED=true`.
4. Confirm `PRODUCT_DATA_MODEL_BACKFILL_STATUS=COMPLETED` and zero missing keys.
5. Create the group-key index during a low-traffic window.
6. Set `PRODUCT_GROUPING_MODE=key` only after the backfill and index are ready.
