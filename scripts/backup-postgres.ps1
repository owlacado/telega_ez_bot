param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$ComposeFile = "compose.yaml",
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$destination = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
if (-not (Test-Path -LiteralPath $destination -PathType Container)) {
    throw "Backup output path is not a directory."
}
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$name = "technician-hub-$stamp-$suffix.dump"
$temporary = "/tmp/$name"
$target = Join-Path $destination $name
$partial = "$target.partial"
$manifestPath = "$target.json"
$manifestPartial = "$manifestPath.partial"
$container = $null
$published = $false

foreach ($path in @($target, $partial, $manifestPath, $manifestPartial)) {
    if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite an existing backup artifact." }
}

Push-Location $root
try {
    $container = (docker compose -f $ComposeFile ps -q db).Trim()
    if (-not $container) { throw "PostgreSQL container is not running." }
    docker compose -f $ComposeFile exec -T db sh -c 'pg_dump --format=custom --no-owner --no-privileges --file="$1" -U "$POSTGRES_USER" "$POSTGRES_DB"' sh $temporary
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed." }
    docker cp "${container}:$temporary" $partial
    if ($LASTEXITCODE -ne 0) { throw "Unable to copy the completed dump." }
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        file = $name
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        sha256 = $digest
        release_commit = if ($env:RELEASE_COMMIT) { $env:RELEASE_COMMIT } else { "unrecorded" }
    }
    $manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPartial -Encoding utf8
    Move-Item -LiteralPath $partial -Destination $target
    Move-Item -LiteralPath $manifestPartial -Destination $manifestPath
    $published = $true
    Write-Output "Backup created: $target"
    Write-Output "Manifest created: $manifestPath"
    Write-Output "Store the database dump and provider encryption keys separately."
    $cutoff = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)
    $ownedName = '^technician-hub-\d{8}T\d{6}Z-[0-9a-f]{8}\.dump(?:\.json)?$'
    $expired = @(
        Get-ChildItem -LiteralPath $destination -File |
            Where-Object { $_.Name -match $ownedName -and $_.LastWriteTimeUtc -lt $cutoff }
    )
    foreach ($artifact in $expired) {
        if ([IO.Path]::GetFullPath($artifact.DirectoryName) -ne $destination) {
            throw "Refusing to remove an artifact outside the backup directory."
        }
        Remove-Item -LiteralPath $artifact.FullName -Force
    }
    Write-Output "Retention: removed $($expired.Count) script-owned artifact(s) older than $RetentionDays days."
}
finally {
    if ($container) {
        docker compose -f $ComposeFile exec -T db rm -f $temporary 2>$null | Out-Null
    }
    if (-not $published) {
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $manifestPartial -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}
