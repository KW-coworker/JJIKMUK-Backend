<#
.SYNOPSIS
    Exports the complete application database without adding CSV files to Git.
.EXAMPLE
    .\Export-JjikmukDatabase.ps1 -DefaultsFile C:\secure\source.cnf -OutputFile D:\backups\jjikmuk.sql -MySqlDumpExecutable 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $DefaultsFile,
    [Parameter(Mandatory = $true)] [string] $OutputFile,
    [string] $DatabaseName = 'jjikmuk',
    [string] $MySqlDumpExecutable = 'mysqldump.exe'
)

$ErrorActionPreference = 'Stop'

if ($DatabaseName -notmatch '^[A-Za-z0-9_]+$') {
    throw 'DatabaseName may contain only letters, numbers, and underscores.'
}

$resolvedDefaults = (Resolve-Path -LiteralPath $DefaultsFile).ProviderPath
$destination = [System.IO.Path]::GetFullPath($OutputFile)
$destinationDirectory = [System.IO.Path]::GetDirectoryName($destination)
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$repositoryPrefix = $repositoryRoot.TrimEnd([char]'\', [char]'/') + [System.IO.Path]::DirectorySeparatorChar

if ($destination.StartsWith($repositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Keep database dumps outside the Git repository.'
}
if (-not (Test-Path -LiteralPath $destinationDirectory -PathType Container)) {
    throw "Output directory does not exist: $destinationDirectory"
}
if (Test-Path -LiteralPath $destination) {
    throw "Output file already exists; refusing to overwrite it: $destination"
}

$partial = "$destination.partial"
if (Test-Path -LiteralPath $partial) {
    throw "Partial dump already exists; inspect it before retrying: $partial"
}

$dumpCommand = Get-Command $MySqlDumpExecutable -ErrorAction Stop
$arguments = @(
    "--defaults-extra-file=$resolvedDefaults",
    '--single-transaction',
    '--quick',
    '--routines',
    '--events',
    '--triggers',
    '--hex-blob',
    '--set-gtid-purged=OFF',
    '--no-tablespaces',
    '--skip-add-drop-table',
    '--default-character-set=utf8mb4',
    "--result-file=$partial",
    $DatabaseName
)

Write-Host "Exporting database '$DatabaseName' to $destination"
& $dumpCommand.Source @arguments
if ($LASTEXITCODE -ne 0) {
    throw "mysqldump failed with exit code $LASTEXITCODE. Inspect the partial file: $partial"
}
if (-not (Test-Path -LiteralPath $partial -PathType Leaf) -or (Get-Item -LiteralPath $partial).Length -eq 0) {
    throw "mysqldump did not produce a non-empty file: $partial"
}

Move-Item -LiteralPath $partial -Destination $destination
$hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
Write-Host "Export complete. SHA-256: $hash"
Write-Host 'Store the dump securely. It contains user records and is not part of Git.'
