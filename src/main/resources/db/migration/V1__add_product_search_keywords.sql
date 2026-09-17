-- The FULLTEXT index is intentionally not created in this startup migration.
-- Creating the first InnoDB FULLTEXT index can rebuild the table and block DML.
ALTER TABLE products
    ADD COLUMN search_keywords TEXT NULL,
    ALGORITHM=INSTANT;
