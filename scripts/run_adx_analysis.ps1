$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python "experiments/analysis/adx_tier_analysis.py"
}
finally {
    Pop-Location
}
