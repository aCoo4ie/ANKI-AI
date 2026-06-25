$ErrorActionPreference = "Stop"

$envPath = Join-Path (Get-Location) ".env"
$apiBase = "http://127.0.0.1:8008"

if (Test-Path -LiteralPath $envPath) {
    Get-Content -LiteralPath $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $name, $value = $line.Split("=", 2)
        if ($name.Trim() -eq "AI_ANKI_API_BASE") {
            $apiBase = $value.Trim().Trim('"').Trim("'")
        }
    }
}

Write-Host "HTML frontend is served by FastAPI."
Write-Host "Start backend with: .\scripts\start_backend.ps1"
Write-Host "Then open: $apiBase"
