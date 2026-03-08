$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python "experiments/final/validate_state_gated_dual_overfit.py"
}
finally {
    Pop-Location
}
