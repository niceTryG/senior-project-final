param(
    [ValidateSet("dev", "prod")]
    [string]$Mode = "dev",
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonCandidates = @(
    (Join-Path $root "venv\\Scripts\\python.exe"),
    (Join-Path $root ".venv\\Scripts\\python.exe")
)
$python = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    $python = "python"
}

if ($Mode -eq "prod") {
    $env:FLASK_CONFIG = "config.ProdConfig"
} else {
    $env:FLASK_CONFIG = "config.DevConfig"
}
$env:PORT = "$Port"

Push-Location $root
try {
    & $python ".\\run.py"
}
finally {
    Pop-Location
}
