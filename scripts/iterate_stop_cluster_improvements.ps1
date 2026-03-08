$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root "src"
    python "experiments/final/iterate_stop_cluster_improvements.py"
}
finally {
    Pop-Location
}
