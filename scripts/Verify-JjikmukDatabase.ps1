<#
.SYNOPSIS
    Verifies the minimum tables and data needed for CSV-free backend startup.
.DESCRIPTION
    Run once against the source and once against the restored database. Compare
    counts and version markers; the source database is the authority.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $DefaultsFile,
    [string] $DatabaseName = 'jjikmuk',
    [string] $MySqlExecutable = 'mysql.exe',
    [long] $ExpectedProductCount = -1,
    [long] $ExpectedNeighborCount = -1
)

$ErrorActionPreference = 'Stop'

if ($DatabaseName -notmatch '^[A-Za-z0-9_]+$') {
    throw 'DatabaseName may contain only letters, numbers, and underscores.'
}

$resolvedDefaults = (Resolve-Path -LiteralPath $DefaultsFile).ProviderPath
$mysqlCommand = Get-Command $MySqlExecutable -ErrorAction Stop
$mysqlPath = $mysqlCommand.Source
$arguments = @(
    "--defaults-extra-file=$resolvedDefaults",
    '--batch',
    '--skip-column-names',
    '--default-character-set=utf8mb4',
    "--database=$DatabaseName"
)

function Invoke-MySqlQuery([string] $Sql) {
    $result = & $mysqlPath @arguments "--execute=$Sql" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL command failed (exit $LASTEXITCODE): $result"
    }
    return $result
}

$requiredTables = @(
    'products',
    'product_neighbor_sets',
    'system_configs',
    'users',
    'histories',
    'email_verifications',
    'flyway_schema_history',
    'product_data_import_runs',
    'product_food_category_memberships',
    'product_allergy_classification_memberships'
)
$tableNames = @(Invoke-MySqlQuery "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$DatabaseName' AND TABLE_NAME IN ('products','product_neighbor_sets','system_configs','users','histories','email_verifications','flyway_schema_history','product_data_import_runs','product_food_category_memberships','product_allergy_classification_memberships')")
$missingTables = @($requiredTables | Where-Object { $_ -notin $tableNames })
if ($missingTables.Count -gt 0) {
    throw "Required tables are missing: $($missingTables -join ', ')"
}

$productCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM products')
$neighborCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM product_neighbor_sets')
$userCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM users')
$historyCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM histories')
$verificationCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM email_verifications')
$foodCategoryMembershipCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM product_food_category_memberships')
$allergyMembershipCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM product_allergy_classification_memberships')
$foodCategoryOrphanCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM product_food_category_memberships membership LEFT JOIN products product ON product.barcode = membership.barcode WHERE product.barcode IS NULL')
$allergyOrphanCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM product_allergy_classification_memberships membership LEFT JOIN products product ON product.barcode = membership.barcode WHERE product.barcode IS NULL')
$failedMigrationCount = [long](Invoke-MySqlQuery 'SELECT COUNT(*) FROM flyway_schema_history WHERE success = 0')

Write-Host "Server: $(Invoke-MySqlQuery 'SELECT @@hostname, @@port, VERSION()')"
Write-Host "Database: $DatabaseName"
Write-Host "products: $productCount"
Write-Host "product_neighbor_sets: $neighborCount"
Write-Host "users: $userCount"
Write-Host "histories: $historyCount"
Write-Host "email_verifications: $verificationCount"
Write-Host "product_food_category_memberships: $foodCategoryMembershipCount"
Write-Host "product_allergy_classification_memberships: $allergyMembershipCount"
Write-Host 'Data version markers:'
@(Invoke-MySqlQuery "SELECT CONCAT(config_key, '=', config_value) FROM system_configs WHERE config_key LIKE 'PRODUCT_DB_%' OR config_key = 'PRODUCT_NEIGHBOR_DB_VERSION' ORDER BY config_key") | ForEach-Object { Write-Host "  $_" }
Write-Host 'Flyway migrations:'
@(Invoke-MySqlQuery "SELECT CONCAT(COALESCE(version, '<baseline>'), ' / ', description, ' / success=', success) FROM flyway_schema_history ORDER BY installed_rank") | ForEach-Object { Write-Host "  $_" }

if ($failedMigrationCount -ne 0) {
    throw "Found $failedMigrationCount failed Flyway migration(s)."
}
if ($productCount -eq 0 -or $neighborCount -eq 0) {
    throw 'Product or recommendation data is empty; a complete database restore is required.'
}
if ($foodCategoryMembershipCount -eq 0 -or $allergyMembershipCount -eq 0) {
    throw 'Product classification membership data is empty; run the V5.1 product import before exporting.'
}
if ($foodCategoryOrphanCount -ne 0 -or $allergyOrphanCount -ne 0) {
    throw "Classification membership orphans found: food=$foodCategoryOrphanCount, allergy=$allergyOrphanCount"
}
if ($ExpectedProductCount -ge 0 -and $productCount -ne $ExpectedProductCount) {
    throw "Product count mismatch: expected $ExpectedProductCount, actual $productCount"
}
if ($ExpectedNeighborCount -ge 0 -and $neighborCount -ne $ExpectedNeighborCount) {
    throw "Neighbor count mismatch: expected $ExpectedNeighborCount, actual $neighborCount"
}

Write-Host 'Basic restore checks passed. Compare version markers and Flyway rows with the source.'
