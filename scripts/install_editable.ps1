$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root
try {
    python -m pip install -e .
}
finally {
    Pop-Location
}
