$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeScript = Join-Path $root 'build-dashboard-data.js'

if (-not (Test-Path -LiteralPath $nodeScript)) {
    throw "Build script not found at $nodeScript"
}

& node $nodeScript

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
