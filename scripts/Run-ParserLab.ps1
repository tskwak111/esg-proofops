param(
    [ValidateSet('preflight', 'docling', 'docling-crosscheck', 'odl', 'odl-2.0', 'hybrid', 'azure', 'azure-preflight', 'test')]
    [string]$Action = 'preflight',
    [string]$Pages = '2,99,100,101,105,200,201,209',
    [string]$KeyFile = '.env.upstage.local',
    [string]$Ledger = '.local/upstage/budget.sqlite3',
    [string]$SshTarget = $env:DOCLING_SSH_TARGET
)
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $labRoot
try {
    $env:PYTHONUTF8 = '1'
    if (!$SshTarget -and (Test-Path -LiteralPath '.local/docling-parser.json')) {
        $SshTarget = (Get-Content -LiteralPath '.local/docling-parser.json' -Raw -Encoding utf8 | ConvertFrom-Json).docling_ssh_target
    }
    if ($SshTarget -and $SshTarget -notmatch '^[a-z_][a-z0-9_-]*@[A-Za-z0-9][A-Za-z0-9.-]*$') {
        throw 'Invalid SSH target'
    }
    if ($Action -eq 'test') {
        uv run --no-sync python -X utf8 -m pytest tests/unit/test_docling_parser.py tests/unit/test_odl_pilot.py tests/unit/test_odl_table_audit.py tests/unit/test_opendataloader_lists.py tests/integration/test_local_parser_runner.py tests/unit/test_portable_operation_lock.py tests/unit/test_source_preview_portable.py -q --junitxml=.local/parser-lab-tests.xml
    } elseif ($Action -eq 'preflight') {
        if ($SshTarget) {
            $gpuAccount = ($SshTarget -split '@')[0]
            ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 $SshTarget "env LD_LIBRARY_PATH=/home/$gpuAccount/parser-bench/nvlib nvidia-smi -L"
        } else {
            & .local/docling-env/Scripts/python.exe -X utf8 -c "from importlib.metadata import version; print('Docling:', version('docling')); assert version('docling') == '2.137.0'; from docling.datamodel.pipeline_options import PdfPipelineOptions; print('Direct CPU runtime ready; OCR will be disabled by the worker')"
        }
    } else {
        $labPdf = @(Get-ChildItem -Path (Join-Path $labRoot '*/NAVER_2024_KOR.pdf') -File)
        if ($labPdf.Count -ne 1) { throw 'Expected exactly one NAVER_2024_KOR.pdf in a child folder' }
        if ($Action -in @('docling', 'docling-crosscheck')) {
            $experimentPath = Join-Path $labRoot ('.local/docling-pilot/' + $Action + '-' + [guid]::NewGuid().ToString('N'))
            $candidatePython = Join-Path $labRoot '.local/docling-env/Scripts/python.exe'
            $labArguments = @('run', '--no-sync', 'python', '-X', 'utf8', '-m', 'evaluation.docling_pilot', '--pdf', $labPdf[0].FullName, '--pages', $Pages, '--python', $candidatePython, '--output', $experimentPath)
            if ($SshTarget) { $labArguments += @('--ssh-target', $SshTarget) }
            if ($Action -eq 'docling-crosscheck') {
                $labArguments += @('--invoke-upstage', '--env-file', $KeyFile, '--ledger', $Ledger)
            }
        } elseif ($Action -in @('azure', 'azure-preflight')) {
            $labArguments = @('run', '--no-sync', 'python', '-X', 'utf8', '-m', 'evaluation.azure_pilot', '--pdf', $labPdf[0].FullName, '--pages', $Pages)
            if ($Action -eq 'azure') { $labArguments += '--invoke' }
        } else {
            $experimentPath = Join-Path $labRoot ('.local/odl-pilot/' + $Action + '-' + [guid]::NewGuid().ToString('N'))
            $candidatePython = Join-Path $labRoot '.local/odl-2.0-env/Scripts/python.exe'
            if ($Action -in @('odl-2.0', 'hybrid') -and !(Test-Path -LiteralPath $candidatePython)) {
                throw 'Install the isolated ODL 2.0 environment first; see README.'
            }
            if ($Action -eq 'hybrid') {
                if (!$PSBoundParameters.ContainsKey('Pages')) { $Pages = '105' }
                $labArguments = @('run', '--no-sync', 'python', '-X', 'utf8', '-m', 'evaluation.odl_hybrid_pilot', '--pdf', $labPdf[0].FullName, '--python', $candidatePython, '--pages', $Pages, '--output', $experimentPath)
            } else {
                $labArguments = @('run', '--no-sync', 'python', '-X', 'utf8', '-m', 'evaluation.odl_pilot', '--pdf', $labPdf[0].FullName, '--pages', $Pages, '--output', $experimentPath)
                if ($Action -eq 'odl-2.0') { $labArguments += @('--candidate-python', $candidatePython) }
                else { $labArguments += '--table-auxiliary' }
            }
        }
        & uv @labArguments
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
