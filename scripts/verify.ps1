$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Check {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Check failed: $Command $Arguments" }
}
Check docker @('compose', 'config', '--quiet')
Check docker @('compose', '--profile', 'test', 'up', '-d', '--wait', 'test-db')
Check '.\.venv\Scripts\python.exe' @('scripts/validate_migrations.py')
Check '.\.venv\Scripts\python.exe' @('scripts/check_contracts.py')
Check '.\.venv\Scripts\python.exe' @('-m', 'pytest', 'apps/api/tests', '-q')
Check '.\.venv\Scripts\ruff.exe' @('check', 'apps/api', 'scripts')
Check '.\.venv\Scripts\ruff.exe' @('format', '--check', 'apps/api', 'scripts')
Check 'npm.cmd' @('test')
Check 'npm.cmd' @('run', 'lint')
Check 'npm.cmd' @('run', 'format:check')
Check 'npm.cmd' @('run', 'build')
Check 'npm.cmd' @('run', 'typecheck')
Check 'npx.cmd' @('playwright', 'install', 'chromium')
Check 'npm.cmd' @('run', 'test:e2e')
Check 'git' @('diff', '--check')
Write-Host 'All Stage 0 checks passed.'
