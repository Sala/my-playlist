# My Playlist — dependency check + local server start
# Usage:  .\start.ps1
# Or:     powershell -ExecutionPolicy Bypass -File .\start.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$HostAddr = "127.0.0.1"
$Port = 8765
$Failed = @()

function Write-Ok($msg) { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Bad($msg) { Write-Host "  !!  $msg" -ForegroundColor Red }
function Write-Hint($msg) { Write-Host "      $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "MY PLAYLIST — checking dependencies..." -ForegroundColor Cyan
Write-Host ""

# --- Python ---
$python = $null
foreach ($name in @("python", "py")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            if ($name -eq "py") {
                $ver = & py -3 --version 2>&1
                if ($LASTEXITCODE -eq 0) { $python = "py -3"; break }
            } else {
                $ver = & python --version 2>&1
                if ($LASTEXITCODE -eq 0) { $python = "python"; break }
            }
        } catch { }
    }
}

if (-not $python) {
    Write-Bad "Python not found"
    Write-Hint "Install Python 3.11+ from https://www.python.org/downloads/"
    Write-Hint "During setup, enable 'Add python.exe to PATH'"
    $Failed += "python"
} else {
    $verOut = if ($python -eq "py -3") { & py -3 --version 2>&1 } else { & python --version 2>&1 }
    Write-Ok "Python ($verOut)"
}

# --- ffmpeg ---
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    $wingetFfmpeg = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ffmpeg.exe"
    if (Test-Path $wingetFfmpeg) {
        $env:Path = "$(Split-Path $wingetFfmpeg);$env:Path"
        $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    }
}
if (-not $ffmpeg) {
    Write-Bad "ffmpeg not found on PATH"
    Write-Hint "Windows:  winget install --id Gyan.FFmpeg -e"
    Write-Hint "Then open a new terminal (or reboot) so PATH updates"
    Write-Hint "macOS:    brew install ffmpeg"
    Write-Hint "Ubuntu:   sudo apt install ffmpeg"
    $Failed += "ffmpeg"
} else {
    $ffVer = (& ffmpeg -version 2>&1 | Select-Object -First 1)
    Write-Ok "ffmpeg ($ffVer)"
}

if ($Failed -contains "python") {
    Write-Host ""
    Write-Host "Fix the issues above, then run .\start.ps1 again." -ForegroundColor Red
    exit 1
}

# --- venv ---
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$venvPip = Join-Path $Root ".venv\Scripts\pip.exe"
$venvUvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "  ..  Creating virtualenv .venv ..." -ForegroundColor Yellow
    if ($python -eq "py -3") {
        & py -3 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if (-not (Test-Path $venvPython)) {
        Write-Bad "Failed to create .venv"
        Write-Hint "Try manually: python -m venv .venv"
        exit 1
    }
    Write-Ok "Created .venv"
} else {
    Write-Ok "Virtualenv .venv"
}

# --- pip packages ---
$req = Join-Path $Root "requirements.txt"
$needInstall = $false
if (-not (Test-Path $venvUvicorn)) {
    $needInstall = $true
} else {
    $check = & $venvPython -c "import fastapi, uvicorn, yt_dlp, pydantic, mutagen" 2>&1
    if ($LASTEXITCODE -ne 0) { $needInstall = $true }
}

if ($needInstall) {
    Write-Host "  ..  Installing Python packages from requirements.txt ..." -ForegroundColor Yellow
    & $venvPython -m pip install --upgrade pip | Out-Null
    & $venvPython -m pip install -r $req
    if ($LASTEXITCODE -ne 0) {
        Write-Bad "pip install failed"
        Write-Hint "Run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
        exit 1
    }
    Write-Ok "Python packages installed"
} else {
    Write-Ok "Python packages (fastapi, uvicorn, yt-dlp, mutagen, ...)"
}

if ($Failed -contains "ffmpeg") {
    Write-Host ""
    Write-Host "ffmpeg is required for MP3 conversion. Install it, then re-run .\start.ps1" -ForegroundColor Red
    exit 1
}

# --- free port if stale process ---
try {
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object -First 1
    if ($conn) {
        Write-Host "  ..  Port $Port in use (PID $($conn.OwningProcess)) — stopping it" -ForegroundColor Yellow
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
} catch { }

Write-Host ""
Write-Host "Starting server at http://${HostAddr}:${Port}" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

# Open browser shortly after start
Start-Job -ScriptBlock {
    param($url)
    Start-Sleep -Seconds 2
    Start-Process $url
} -ArgumentList "http://${HostAddr}:${Port}" | Out-Null

& $venvUvicorn "app.main:app" --host $HostAddr --port $Port
