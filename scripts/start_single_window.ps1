$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

function Set-DefaultEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    if (-not [Environment]::GetEnvironmentVariable($Name, "Process")) {
        Set-Item -Path "Env:$Name" -Value $Value
    }
}

function Set-RandomDefaultEnv {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not [Environment]::GetEnvironmentVariable($Name, "Process")) {
        $bytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $rng.GetBytes($bytes)
        } finally {
            $rng.Dispose()
        }
        Set-Item -Path "Env:$Name" -Value ([Convert]::ToBase64String($bytes))
    }
}

function Test-PortBusy {
    param([Parameter(Mandatory = $true)][int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)]$Processes
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        foreach ($process in $Processes) {
            if ($process -and $process.HasExited) {
                throw "$Name startup failed because process $($process.Id) exited with code $($process.ExitCode)."
            }
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 700
        }
    } while ((Get-Date) -lt $deadline)
    throw "$Name did not become ready on $Url within $TimeoutSeconds seconds."
}

function Stop-ChildProcesses {
    param([object[]]$Processes)
    foreach ($process in $Processes) {
        if ($process -and -not $process.HasExited) {
            try {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            } catch {
            }
        }
    }
}

Set-DefaultEnv "PYTHONUTF8" "1"
Set-DefaultEnv "PROJECT_ROOT" $ProjectRoot
Set-DefaultEnv "DB_BACKEND" "sqlite"
Set-DefaultEnv "MYSQL_HOST" "127.0.0.1"
Set-DefaultEnv "MYSQL_PORT" "3306"
Set-DefaultEnv "MYSQL_DATABASE" "gas_monitor"
Set-DefaultEnv "MYSQL_USER" "root"
Set-DefaultEnv "MYSQL_PASSWORD" ""
Set-DefaultEnv "APP_CREDENTIAL_SECRET" "gas-monitor-default-secret"
Set-RandomDefaultEnv "APP_SECRET_KEY"
Set-DefaultEnv "FLASK_HOST" "127.0.0.1"
Set-DefaultEnv "FLASK_PORT" "5000"
Set-DefaultEnv "FRONTEND_HOST" "127.0.0.1"
Set-DefaultEnv "FRONTEND_PORT" "5173"
Set-DefaultEnv "FRONTEND_URL" "http://127.0.0.1:5173"
Set-DefaultEnv "FRONTEND_ORIGINS" "http://127.0.0.1:5173,http://localhost:5173"
Set-DefaultEnv "ASYNC_DETECTION_ENABLED" "1"
Set-DefaultEnv "DRIFT_MONITOR_ENABLED" "1"
Set-DefaultEnv "SIMULATION_DEVICE_COUNT" "50"
Set-DefaultEnv "MQTT_HOST" "127.0.0.1"
Set-DefaultEnv "MQTT_PORT" "1883"
Set-DefaultEnv "MQTT_REGISTER_TOPIC" "gas-meter/register"
Set-DefaultEnv "MQTT_UPLOAD_TOPIC" "gas-meter/+/upload"

$frontendPort = [int]$env:FRONTEND_PORT
$backendPort = [int]$env:FLASK_PORT
$frontendUrl = "http://$($env:FRONTEND_HOST):$frontendPort"
$backendUrl = "http://$($env:FLASK_HOST):$backendPort"

if (-not (Test-Path (Join-Path $ProjectRoot "frontend\index.html"))) {
    throw "Frontend entry not found: $(Join-Path $ProjectRoot 'frontend\index.html')"
}

Write-Host "Checking Python dependencies..."
& python -c "import flask, sqlalchemy, torch, pandas, sklearn, joblib, paho.mqtt.client"
if ($LASTEXITCODE -ne 0) {
    throw "Missing Python dependencies. Run: pip install -r requirements.txt"
}

Write-Host "Checking occupied ports..."
if (Test-PortBusy $frontendPort) {
    throw "Frontend port $frontendPort is already in use. Stop the old frontend service first so this launcher can own shutdown."
}
if (Test-PortBusy $backendPort) {
    throw "Backend port $backendPort is already in use. Stop the old backend service first so this launcher can own shutdown."
}

$children = @()
try {
    Write-Host ""
    Write-Host "Starting Smart Gas Monitoring System in this window..."
    Write-Host "API      = $backendUrl"
    Write-Host "Frontend = $frontendUrl"
    Write-Host "Database = $($env:DB_BACKEND) ($($env:MYSQL_HOST):$($env:MYSQL_PORT)/$($env:MYSQL_DATABASE))"
    Write-Host ""

    $frontend = Start-Process `
        -FilePath "python" `
        -ArgumentList @("-m", "http.server", "$frontendPort", "--bind", $env:FRONTEND_HOST) `
        -WorkingDirectory (Join-Path $ProjectRoot "frontend") `
        -NoNewWindow `
        -PassThru
    $children += $frontend
    Write-Host "Frontend process started: PID $($frontend.Id)"

    $backend = Start-Process `
        -FilePath "python" `
        -ArgumentList @("-m", "flask", "--app", "src.app", "run", "--host", $env:FLASK_HOST, "--port", "$backendPort") `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -PassThru
    $children += $backend
    Write-Host "Backend process started : PID $($backend.Id)"

    Write-Host ""
    Write-Host "Waiting for services..."
    Wait-HttpReady "Frontend" $frontendUrl 45 $children
    Wait-HttpReady "Backend" $backendUrl 60 $children

    Write-Host ""
    Write-Host "System is ready."
    Write-Host "Frontend: $frontendUrl"
    Write-Host "Backend : $backendUrl"
    Write-Host "Default admin: solisW / 777803wzw@"
    Write-Host ""
    Write-Host "Open the frontend URL in your browser. Press Ctrl+C in this window to stop frontend and backend together."

    while ($true) {
        foreach ($process in $children) {
            if ($process.HasExited) {
                throw "Process $($process.Id) exited with code $($process.ExitCode). Stopping the system."
            }
        }
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host ""
    Write-Host "Stopping frontend and backend..."
    Stop-ChildProcesses $children
    Write-Host "Stopped."
}
