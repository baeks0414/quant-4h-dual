$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python "experiments/final/verify_state_gated_dual_combo.py"
}
finally {
    Pop-Location
}
