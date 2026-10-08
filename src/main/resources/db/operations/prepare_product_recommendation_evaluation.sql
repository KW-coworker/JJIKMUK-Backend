-- Human-reviewed offline evaluation set template.
-- Replace all sample values after checking that the user, reference product,
-- expected products, and neighbor set exist. Do not use this sample verbatim.

SELECT
    u.id AS user_id,
    u.allergies,
    u.special_diet,
    u.disliked_ingredients,
    COUNT(h.id) AS behavior_events
FROM users u
LEFT JOIN histories h ON h.user_id = u.id
GROUP BY u.id, u.allergies, u.special_diet, u.disliked_ingredients
ORDER BY behavior_events DESC
LIMIT 30;

SELECT
    p.barcode,
    p.product_name,
    p.manufacturer,
    p.food_type,
    n.recommendation_count,
    n.model_version
FROM products p
INNER JOIN product_neighbor_sets n ON n.source_barcode = p.barcode
WHERE p.barcode = :reviewed_reference_barcode;

-- One row is one reviewed task. expected_relevant_barcodes is a comma-separated
-- list of products that a reviewer judged safe and genuinely substitutable.
-- INSERT INTO product_recommendation_evaluation_cases
--     (case_id, user_id, reference_barcode, expected_relevant_barcodes, notes, active)
-- VALUES
--     ('vegan-snack-001', :reviewed_user_id, :reviewed_reference_barcode,
--      '8800000000001,8800000000002', 'Two-person review completed', TRUE);

SELECT
    case_id,
    user_id,
    reference_barcode,
    expected_relevant_barcodes,
    notes
FROM product_recommendation_evaluation_cases
WHERE active = TRUE
ORDER BY case_id;
