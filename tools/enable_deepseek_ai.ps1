param(
    [string]$BaseUrl = "https://api.deepseek.com",
    [string]$Model = "deepseek-v4-flash"
)

$secureApiKey = Read-Host "Enter DeepSeek API Key (input is hidden)" -AsSecureString
$credential = [System.Management.Automation.PSCredential]::new(
    "bankflow",
    $secureApiKey
)

$env:BANKFLOW_AI_API_KEY = $credential.GetNetworkCredential().Password
$env:BANKFLOW_AI_BASE_URL = $BaseUrl
$env:BANKFLOW_AI_MODEL = $Model
$env:BANKFLOW_AI_ENABLED = "true"
$env:BANKFLOW_AI_DATA_AUTHORIZED = "true"
$env:BANKFLOW_AI_RETENTION_CONFIRMED = "true"
$env:BANKFLOW_AI_ALLOW_BUSINESS_NAMES = "true"
$env:BANKFLOW_AI_TIMEOUT_SECONDS = "60"
$env:BANKFLOW_AI_BATCH_SIZE = "50"

$credential = $null
$secureApiKey = $null

Write-Host "DeepSeek AI is enabled in this PowerShell window."
Write-Host "Model: $env:BANKFLOW_AI_MODEL"
Write-Host "Base URL: $env:BANKFLOW_AI_BASE_URL"
Write-Host "API Key: configured (value hidden)"
