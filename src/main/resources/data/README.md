# Product data

The active dataset is `Product.csv`. The previous small dataset is retained as
`Old.csv` for reference only.

The backend reads the file as a streaming, external import asset and deliberately
excludes CSV files from the built JAR. For a deployed server, set
`PRODUCT_DATA_RESOURCE` to a Spring resource location such as
`file:/opt/jjikmuk/data/Product.csv`.

The default dataset contract is:

- version: `V4.0-PRODUCTCSV-RECOMMENDATION-METADATA`
- logical data records: `1,348,436`
- required application columns: the former 24 product columns plus the 12
  `is_*` dietary-classification columns
- runtime recommendation metadata: `food_type`, allergy/nutrition/diet origin
  and confidence are derived while importing from the existing provenance columns

The recommendation dataset is stored separately as `ProductNeighbors.csv`.
It contains one source barcode and 100 `barcode|similarityScore` candidate cells
per row. The backend imports it into `product_neighbor_sets`; final allergy,
special-diet, disliked-ingredient and history-based decisions are made at API
request time. In deployed environments set
`RECOMMENDATION_DATA_RESOURCE=file:/opt/jjikmuk/data/ProductNeighbors.csv`.
