$ErrorActionPreference = "Stop"

$envPath = Join-Path (Get-Location) ".env"
$apiBase = "http://localhost:8000"
$backendHost = $null
$backendPort = $null
$reload = $false

if (Test-Path -LiteralPath $envPath) {
    Get-Content -LiteralPath $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $name, $value = $line.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        [Environment]::SetEnvironmentVariable($name, $value, "Process")

        if ($name -eq "AI_ANKI_API_BASE") {
            $apiBase = $value
        }
        if ($name -eq "BACKEND_HOST") {
            $backendHost = $value
        }
        if ($name -eq "BACKEND_PORT") {
            $backendPort = [int]$value
        }
        if ($name -eq "BACKEND_RELOAD") {
            $reload = $value -in @("1", "true", "True", "yes", "Yes")
        }
    }
}

$uri = [Uri]$apiBase
$hostName = if ($backendHost) { $backendHost } elseif ($uri.Host) { $uri.Host } else { "127.0.0.1" }
if ($hostName -eq "localhost") {
    $hostName = "127.0.0.1"
}
$port = if ($backendPort) { $backendPort } elseif ($uri.Port -gt 0) { $uri.Port } else { 8000 }
$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

Write-Host "Starting FastAPI on ${hostName}:${port}"
$args = @("app.main:app", "--host", $hostName, "--port", $port)
if ($reload) {
    $args += "--reload"
}
& $python -m uvicorn @args
