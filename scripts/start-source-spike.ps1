$ErrorActionPreference = 'Stop'
$etlRoot = Split-Path -Parent $PSScriptRoot
$etlRuntime = Join-Path $etlRoot '.spike-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $etlRuntime)) {
    throw 'Install the isolated spike environment first. See docs/source-spike-usage.md. No DB password is accepted by this script.'
}
Push-Location -LiteralPath $etlRoot
try { & $etlRuntime -m backend.spike.server }
finally { Pop-Location }
