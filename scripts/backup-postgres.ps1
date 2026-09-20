param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$ComposeFile = "compose.yaml"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$destination = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$name = "technician-hub-$stamp.dump"
$temporary = "/tmp/$name"

Push-Location $root
try {
    $container = (docker compose -f $ComposeFile ps -q db).Trim()
    if (-not $container) { throw "PostgreSQL container is not running." }
    docker compose -f $ComposeFile exec -T db sh -c 'pg_dump --format=custom --no-owner --no-privileges --file="$1" -U "$POSTGRES_USER" "$POSTGRES_DB"' sh $temporary
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed." }
    $target = Join-Path $destination $name
    docker cp "${container}:$temporary" $target
    if ($LASTEXITCODE -ne 0) { throw "Unable to copy the completed dump." }
    docker compose -f $ComposeFile exec -T db rm -f $temporary
    if ($LASTEXITCODE -ne 0) { throw "Unable to remove the temporary container dump." }
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        file = $name
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        sha256 = $digest
        release_commit = if ($env:RELEASE_COMMIT) { $env:RELEASE_COMMIT } else { "unrecorded" }
    }
    $manifestPath = "$target.json"
    $manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8
    Write-Output "Backup created: $target"
    Write-Output "Manifest created: $manifestPath"
    Write-Output "Store the database dump and provider encryption keys separately."
}
finally {
    Pop-Location
}
