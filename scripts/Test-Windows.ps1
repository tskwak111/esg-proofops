param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs = @('-q')
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project Python environment is missing.'
}
# Each invocation owns a new short path; never let pytest delete an existing path.
$testRoot = Join-Path $env:LOCALAPPDATA ('Temp/esg-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
if (Test-Path -LiteralPath $testRoot) {
    throw 'Temporary test directory already exists.'
}
if ($PytestArgs -match '^--basetemp(?:=|$)') {
    throw 'This wrapper owns --basetemp; invoke pytest directly for a custom path.'
}
$previousUtf8 = $env:PYTHONUTF8
try {
    $env:PYTHONUTF8 = '1'
    Push-Location $projectRoot
    try {
        & $python -X utf8 -m pytest --basetemp $testRoot @PytestArgs
        $testExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    $env:PYTHONUTF8 = $previousUtf8
}
exit $testExitCode
