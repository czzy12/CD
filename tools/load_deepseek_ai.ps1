$ErrorActionPreference = "Stop"
$configPath = Join-Path $env:LOCALAPPDATA "BankFlowReview\ai_runtime.json"

if (-not (Test-Path -LiteralPath $configPath)) {
    Write-Host "No saved AI config found. Run tools\save_deepseek_ai_config.ps1 first." -ForegroundColor Yellow
    exit 1
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$secure = ConvertTo-SecureString -String $config.api_key_encrypted
$credential = [System.Management.Automation.PSCredential]::new(
    "bankflow",
    $secure
)

$env:BANKFLOW_AI_API_KEY = $credential.GetNetworkCredential().Password
$env:BANKFLOW_AI_BASE_URL = [string]$config.base_url
$env:BANKFLOW_AI_MODEL = [string]$config.model
$env:BANKFLOW_AI_ENABLED = "true"
$env:BANKFLOW_AI_DATA_AUTHORIZED = "true"
$env:BANKFLOW_AI_RETENTION_CONFIRMED = "true"
$env:BANKFLOW_AI_ALLOW_BUSINESS_NAMES = "true"
$env:BANKFLOW_AI_TIMEOUT_SECONDS = [string]$config.timeout_seconds
$env:BANKFLOW_AI_BATCH_SIZE = [string]$config.batch_size

$secure = $null
$credential = $null

Write-Host "Loaded AI runtime config from $configPath"
Write-Host "Model: $env:BANKFLOW_AI_MODEL"
Write-Host "Base URL: $env:BANKFLOW_AI_BASE_URL"
Write-Host "API Key: configured (value hidden)"
