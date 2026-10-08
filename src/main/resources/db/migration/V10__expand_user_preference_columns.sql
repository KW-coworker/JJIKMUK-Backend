-- Canonical comma-separated IDs and free-form profile lists can exceed the
-- original Hibernate default VARCHAR(255). Keep all profile columns aligned.
ALTER TABLE users
    MODIFY COLUMN allergies VARCHAR(1000) NULL,
    MODIFY COLUMN diseases VARCHAR(1000) NULL,
    MODIFY COLUMN special_diet VARCHAR(1000) NULL,
    MODIFY COLUMN disliked_ingredients VARCHAR(1000) NULL;
