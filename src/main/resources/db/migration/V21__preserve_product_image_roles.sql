-- DB 담당자 2026-11-09 전달본의 nullable 이미지 메타데이터 원본 정의.
-- 실제 이미지 데이터는 승인된 별도 상품 반영 작업에서 처리한다.
-- 기존 FULLTEXT를 유지한다. INSTANT를 가정하지 않는다.
ALTER TABLE products
    ADD COLUMN image_role varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    ADD COLUMN image_display_notice varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    ADD COLUMN image_asset_sha256 char(64) CHARACTER SET ascii COLLATE ascii_general_ci DEFAULT NULL,
    ADD COLUMN image_assignment_run varchar(64) CHARACTER SET ascii COLLATE ascii_general_ci DEFAULT NULL,
    ALGORITHM=COPY, LOCK=SHARED;
