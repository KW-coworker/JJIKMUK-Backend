<#
.SYNOPSIS
    Restores a full database dump into a NEW database on the target MySQL server.
.DESCRIPTION
    Refuses to import if the target database already exists. A failed import leaves
    the new database in place for inspection; it never drops an existing database.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $DefaultsFile,
    [Parameter(Mandatory = $true)] [string] $DumpFile,
    [Parameter(Mandatory = $true)] [string] $DatabaseName,
    [Parameter(Mandatory = $true)] [string] $ExpectedSha256,
    [string] $MySqlExecutable = 'mysql.exe'
)

$ErrorActionPreference = 'Stop'

if ($DatabaseName -notmatch '^[A-Za-z0-9_]+$') {
    throw 'DatabaseName may contain only letters, numbers, and underscores.'
}
if ($ExpectedSha256 -notmatch '^[A-Fa-f0-9]{64}$') {
    throw 'ExpectedSha256 must be the 64-character hash printed by the export script.'
}

$resolvedDefaults = (Resolve-Path -LiteralPath $DefaultsFile).ProviderPath
$resolvedDump = (Resolve-Path -LiteralPath $DumpFile).ProviderPath
if (-not (Test-Path -LiteralPath $resolvedDump -PathType Leaf) -or (Get-Item -LiteralPath $resolvedDump).Length -eq 0) {
    throw "Dump file is missing or empty: $resolvedDump"
}

$actualHash = (Get-FileHash -LiteralPath $resolvedDump -Algorithm SHA256).Hash
if ($actualHash -ne $ExpectedSha256.ToUpperInvariant()) {
    throw 'Dump SHA-256 does not match the expected value; refusing to restore.'
}

$mysqlCommand = Get-Command $MySqlExecutable -ErrorAction Stop
$mysqlPath = $mysqlCommand.Source
$commonArguments = @(
    "--defaults-extra-file=$resolvedDefaults",
    '--batch',
    '--skip-column-names',
    '--default-character-set=utf8mb4'
)

function Invoke-MySqlQuery([string] $Sql) {
    $result = & $mysqlPath @commonArguments "--execute=$Sql" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL command failed (exit $LASTEXITCODE): $result"
    }
    return $result
}

$server = (Invoke-MySqlQuery 'SELECT @@hostname, @@port, VERSION()').ToString().Trim()
$databaseExists = (Invoke-MySqlQuery "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$DatabaseName'").ToString().Trim()
if ($databaseExists -ne '0') {
    throw "Database '$DatabaseName' already exists on $server. Restore only into a new database."
}

Write-Host "Target server: $server"
Write-Host "New database: $DatabaseName"
Write-Host "Verified dump SHA-256: $actualHash"

# The database name is restricted above, so it is safe to quote as an identifier.
Invoke-MySqlQuery "CREATE DATABASE ``$DatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci" | Out-Null

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $mysqlPath
$startInfo.Arguments = '--defaults-extra-file="' + $resolvedDefaults + '" --default-character-set=utf8mb4 --binary-mode --database=' + $DatabaseName
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.CreateNoWindow = $true

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo
try {
    if (-not $process.Start()) {
        throw 'Could not start mysql.exe.'
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    try {
        $dumpStream = [System.IO.File]::OpenRead($resolvedDump)
        try {
            $dumpStream.CopyTo($process.StandardInput.BaseStream)
        } finally {
            $dumpStream.Dispose()
            $process.StandardInput.Close()
        }
    } catch {
        if (-not $process.HasExited) {
            $process.Kill()
        }
        throw
    }
    $process.WaitForExit()
    $null = $stdoutTask.Result
    $errorOutput = $stderrTask.Result
    if ($process.ExitCode -ne 0) {
        throw "mysql import failed (exit $($process.ExitCode)): $errorOutput"
    }
} finally {
    $process.Dispose()
}

Write-Host "Restore complete on $server. Run Verify-JjikmukDatabase.ps1 and compare its output with the source database."
