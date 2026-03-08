$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python "experiments/analysis/adopted_dual_breakdown.py"
}
finally {
    Pop-Location
}
