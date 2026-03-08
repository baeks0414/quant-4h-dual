$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python "experiments/final/verify_dynamic_v2.py"
}
finally {
    Pop-Location
}
