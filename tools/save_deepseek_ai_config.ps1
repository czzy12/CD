param(
    [string]$BaseUrl = "https://api.deepseek.com",
    [string]$Model = "deepseek-v4-flash"
)

$ErrorActionPreference = "Stop"
$configDir = Join-Path $env:LOCALAPPDATA "BankFlowReview"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
$configPath = Join-Path $configDir "ai_runtime.json"

$secureApiKey = Read-Host "Enter DeepSeek API Key (input is hidden)" -AsSecureString
$encrypted = ConvertFrom-SecureString -SecureString $secureApiKey
$secureApiKey = $null

$config = @{
    base_url = $BaseUrl
    model = $Model
    enabled = $true
    data_authorized = $true
    retention_confirmed = $true
    allow_business_names = $true
    timeout_seconds = 60
    batch_size = 50
    api_key_encrypted = $encrypted
} | ConvertTo-Json

[System.IO.File]::WriteAllText($configPath, $config, [System.Text.Encoding]::UTF8)
Write-Host "Saved AI runtime config: $configPath"
Write-Host "API key is encrypted with the current Windows user account (DPAPI)."
Write-Host "To load it into a new PowerShell session, run: tools\load_deepseek_ai.ps1"
