param([ValidateSet('Web', 'Api', 'Backend')][string]$Service = 'Web')
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
Push-Location $labRoot
try {
    if ($Service -eq 'Api') {
        & "$labRoot/.venv/Scripts/python.exe" -X utf8 -m evaluation.local_analysis_server --port 4240 --web-origin http://127.0.0.1:5175
    } elseif ($Service -eq 'Backend') {
        $previousOrigin = $env:APP_ORIGIN
        try {
            $env:APP_ORIGIN = 'http://127.0.0.1:5175'
            & "$labRoot/.venv/Scripts/python.exe" -X utf8 -m uvicorn proofops_api.main:app --host 127.0.0.1 --port 8000
        } finally {
            $env:APP_ORIGIN = $previousOrigin
        }
    } else {
        $oldApi = $env:LOCAL_ANALYSIS_API
        $oldMode = $env:VITE_LOCAL_ANALYSIS
        try {
            $env:LOCAL_ANALYSIS_API = 'http://127.0.0.1:4240'
            $env:VITE_LOCAL_ANALYSIS = 'true'
            Set-Location "$labRoot/apps/web"
            & node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5175 --strictPort
        } finally {
            $env:LOCAL_ANALYSIS_API = $oldApi
            $env:VITE_LOCAL_ANALYSIS = $oldMode
        }
    }
} finally { Pop-Location }
