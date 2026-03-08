$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python -m quant.cli.backtest --outdir results/final/result_cli_regime_only
}
finally {
    Pop-Location
}
