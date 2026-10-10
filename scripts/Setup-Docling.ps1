$ErrorActionPreference = 'Continue'
$labRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $labRoot
try {
    $env:PYTHONUTF8 = '1'
    $doclingPython = Join-Path $labRoot '.local/docling-env/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $doclingPython)) {
        uv venv .local/docling-env --python 3.12 --allow-existing
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create Docling environment' }
    }
    uv pip install --python $doclingPython -r config/docling-cpu-requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install pinned Docling runtime' }
    uv pip freeze --python $doclingPython | Set-Content -Encoding utf8 .local/docling-runtime-freeze.txt
} finally {
    Pop-Location
}
