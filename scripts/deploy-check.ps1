param(
    [switch]$SkipDbUpgrade,
    [switch]$SkipBotRequirement
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

if (-not $env:FLASK_CONFIG) {
    $env:FLASK_CONFIG = "config.ProdConfig"
}

Push-Location $root
try {
    if (-not $SkipDbUpgrade) {
        & $python -m flask --app wsgi db-upgrade
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    $args = @("-m", "flask", "--app", "wsgi", "deploy-preflight")
    if ($SkipBotRequirement) {
        $args += "--no-require-bot"
    }

    & $python @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
