$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "..\.venvs\cd-bankflow-webview2-spike\Scripts\pythonw.exe"
$app = Join-Path $root "gui_webview2_app.py"
$loader = Join-Path $root "tools\load_deepseek_ai.ps1"

if (Test-Path -LiteralPath $loader) {
    & $loader
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Missing Python environment:" -ForegroundColor Yellow
    Write-Host $python
    exit 1
}

Set-Location $root
& $python $app @args
exit $LASTEXITCODE
