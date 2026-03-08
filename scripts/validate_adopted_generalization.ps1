$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python "experiments/final/validate_adopted_generalization.py"
}
finally {
    Pop-Location
}
