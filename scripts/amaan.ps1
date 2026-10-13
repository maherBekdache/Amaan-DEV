<#
.SYNOPSIS
  Start/stop the Amaan stack on Windows (Docker Desktop + WSL2).

.EXAMPLE
  .\scripts\amaan.ps1 up            # URL.vet + Amaan, then open http://localhost:8000
  .\scripts\amaan.ps1 up -UrlvetUi  # also start URL.vet's own web UI on :3000
  .\scripts\amaan.ps1 up -WhatsApp  # also start the optional WhatsApp bridge
  .\scripts\amaan.ps1 status
  .\scripts\amaan.ps1 down
  .\scripts\amaan.ps1 update-urlvet # move URL.vet to the pinned ref again
  .\scripts\amaan.ps1 dev           # hot-reload dev: backend :8000 + frontend :5173 (URL.vet from Docker)
  .\scripts\amaan.ps1 dev -Mock     # same, with a FAKE URL.vet (no Docker needed; never for the demo)
  .\scripts\amaan.ps1 test          # backend tests + frontend type check
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("setup", "up", "down", "status", "logs", "update-urlvet", "dev", "test")]
  [string]$Command = "up",
  [switch]$UrlvetUi,
  [switch]$WhatsApp,
  [switch]$Mock
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$UrlvetDir = Join-Path $Root "third_party\urlvet"
$UrlvetRepo = "https://github.com/urlvet/urlvet.git"
# Pinned so the demo does not change under us. Bump deliberately.
$UrlvetRef = if ($env:URLVET_REF) { $env:URLVET_REF } else { "a6b54c29b73a053b916805173fba352e9be0204c" }
$Network = "amaan-urlvet"
$Utf8 = New-Object System.Text.UTF8Encoding $false

# Windows PowerShell 5.1 turns anything a native program (docker, git) writes
# to stderr into a fatal error when $ErrorActionPreference is "Stop", even if
# the program succeeded. So native commands run with "Continue" and we judge
# them by their exit code only.
function Invoke-Checked([string]$exe, [string[]]$arguments) {
  $ErrorActionPreference = "Continue"
  & $exe @arguments
  if ($LASTEXITCODE -ne 0) { throw "$exe $($arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

# Runs a native command silently; returns $true if it succeeded.
function Test-Native([string]$exe, [string[]]$arguments) {
  $ErrorActionPreference = "Continue"
  & $exe @arguments *> $null
  return ($LASTEXITCODE -eq 0)
}

function New-Secret {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Assert-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker is not installed. Install Docker Desktop (WSL2 backend)." }
  if (-not (Test-Native docker @("info"))) { throw "Docker Desktop is not running. Start it, wait for 'Engine running', and try again." }
}

function Get-UrlvetCompose {
  @("compose", "-p", "urlvet",
    "-f", (Join-Path $UrlvetDir "docker\prod\docker-compose.prod.yml"),
    "-f", (Join-Path $Root "infra\urlvet\docker-compose.amaan.yml"))
}

function Invoke-Setup {
  Assert-Docker
  if (-not (Test-Path $UrlvetDir)) {
    Write-Host "==> Cloning URL.vet (AGPL-3.0, kept unmodified in third_party/)" -ForegroundColor Cyan
    Invoke-Checked git @("clone", "--quiet", $UrlvetRepo, $UrlvetDir)
    Invoke-Checked git @("-C", $UrlvetDir, "-c", "advice.detachedHead=false", "checkout", "--quiet", $UrlvetRef)
  }
  $serverEnv = Join-Path $UrlvetDir "server\.env"
  $composeEnv = Join-Path $UrlvetDir "docker\prod\.env"
  if (-not (Test-Path $serverEnv) -or -not (Test-Path $composeEnv)) {
    Write-Host "==> Writing URL.vet configuration with fresh secrets" -ForegroundColor Cyan
    $cache = New-Secret
    $tpl = Get-Content (Join-Path $Root "infra\urlvet\server.env.template") -Raw
    $tpl = $tpl.Replace("__CACHE_PASSWORD__", $cache).Replace("__JWT_SECRET__", (New-Secret)).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($serverEnv, $tpl, $Utf8)
    [IO.File]::WriteAllText($composeEnv, "CACHE_PASSWORD=$cache`n", $Utf8)
  }
  # Shared secret between Amaan and the WhatsApp bridge (read by docker compose from .env).
  $rootEnv = Join-Path $Root ".env"
  if (-not (Test-Path $rootEnv) -or -not (Select-String -Path $rootEnv -Pattern "^AMAAN_BRIDGE_TOKEN=" -Quiet)) {
    [IO.File]::AppendAllText($rootEnv, "AMAAN_BRIDGE_TOKEN=$(New-Secret)`n", $Utf8)
  }
  if (-not (Test-Native docker @("network", "inspect", $Network))) {
    Invoke-Checked docker @("network", "create", $Network) | Out-Null
  }
}

function Wait-Healthy([string]$url, [int]$seconds) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $url | Out-Null; return $true } catch { Start-Sleep 2 }
  }
  return $false
}

function Initialize-DevEnv {
  $backend = Join-Path $Root "backend"
  $py = Join-Path $backend ".venv\Scripts\python.exe"
  if (-not (Test-Path $py)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python launcher 'py' not found. Install Python 3.11 from python.org." }
    Write-Host "==> Creating backend\.venv (Python 3.11)" -ForegroundColor Cyan
    Invoke-Checked py @("-3.11", "-m", "venv", (Join-Path $backend ".venv"))
  }
  if (-not (Test-Native $py @("-m", "pip", "--version"))) { Invoke-Checked $py @("-m", "ensurepip", "--upgrade") }
  Write-Host "==> Installing backend dependencies" -ForegroundColor Cyan
  Push-Location $backend
  try { Invoke-Checked $py @("-m", "pip", "install", "--quiet", "-e", ".[dev]") } finally { Pop-Location }
  $frontend = Join-Path $Root "frontend"
  if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js not found. Install Node 20+ from nodejs.org." }
    Write-Host "==> Installing frontend dependencies" -ForegroundColor Cyan
    Push-Location $frontend
    try { Invoke-Checked npm @("install", "--no-fund", "--no-audit") } finally { Pop-Location }
  }
  return $py
}

function Start-Window([string]$title, [string]$dir, [string]$cmd) {
  Start-Process powershell -WorkingDirectory $dir -ArgumentList @("-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle='$title'; $cmd")
}

switch ($Command) {
  "setup" { Invoke-Setup; Write-Host "Setup done." -ForegroundColor Green }

  "up" {
    Invoke-Setup
    $services = @("backend", "chrome", "valkey")
    if ($UrlvetUi) { $services += "web" }
    Write-Host "==> Building and starting URL.vet ($($services -join ', '))" -ForegroundColor Cyan
    Invoke-Checked docker ((Get-UrlvetCompose) + @("up", "-d", "--build") + $services)
    Push-Location $Root
    $profileArgs = if ($WhatsApp) { @("--profile", "whatsapp") } else { @() }
    Write-Host "==> Building and starting Amaan$(if ($WhatsApp) { ' + WhatsApp bridge' })" -ForegroundColor Cyan
    try { Invoke-Checked docker (@("compose") + $profileArgs + @("up", "-d", "--build")) } finally { Pop-Location }
    if (Wait-Healthy "http://localhost:8000/health" 90) {
      Write-Host "`nAmaan is running:  http://localhost:8000" -ForegroundColor Green
      Write-Host "URL.vet API:       http://localhost:8080/swagger/index.html"
      if ($UrlvetUi) { Write-Host "URL.vet UI:        http://localhost:3000" }
      Start-Process "http://localhost:8000"
    } else {
      Write-Warning "Amaan did not answer yet. Check: .\scripts\amaan.ps1 logs"
    }
  }

  "down" {
    Push-Location $Root
    try { Invoke-Checked docker @("compose", "--profile", "whatsapp", "down") } finally { Pop-Location }
    if (Test-Path $UrlvetDir) { Invoke-Checked docker ((Get-UrlvetCompose) + @("down")) }
  }

  "status" {
    Push-Location $Root
    try { Invoke-Checked docker @("compose", "ps") } finally { Pop-Location }
    if (Test-Path $UrlvetDir) { Invoke-Checked docker ((Get-UrlvetCompose) + @("ps")) }
    try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:8000/health").Content } catch { Write-Warning "Amaan is not answering on :8000" }
  }

  "logs" {
    Push-Location $Root
    try { Invoke-Checked docker @("compose", "logs", "-f", "--tail", "100") } finally { Pop-Location }
  }

  "update-urlvet" {
    Invoke-Checked git @("-C", $UrlvetDir, "fetch", "--quiet", "origin")
    Invoke-Checked git @("-C", $UrlvetDir, "-c", "advice.detachedHead=false", "checkout", "--quiet", $UrlvetRef)
    Write-Host "URL.vet is at $UrlvetRef. Run '.\scripts\amaan.ps1 up' to rebuild." -ForegroundColor Green
  }

  "dev" {
    $py = Initialize-DevEnv
    $backend = Join-Path $Root "backend"
    # Free :8000 if the Docker version of Amaan is running (URL.vet keeps running).
    if (Get-Command docker -ErrorAction SilentlyContinue) {
      Push-Location $Root; try { Test-Native docker @("compose", "stop", "amaan") | Out-Null } finally { Pop-Location }
    }
    if ($Mock) {
      Write-Warning "Starting the MOCK URL.vet on :8080. Its verdicts are FAKE. Never use it for the demo."
      Start-Window "MOCK URL.vet :8080" $backend "& '$py' -m uvicorn devtools.mock_urlvet:app --host 127.0.0.1 --port 8080"
    }
    Start-Window "Amaan backend :8000" $backend "& '$py' -m uvicorn amaan.main:app --reload --host 127.0.0.1 --port 8000"
    Start-Window "Amaan frontend :5173" (Join-Path $Root "frontend") "npm run dev"
    Start-Sleep 4
    Start-Process "http://localhost:5173"
    Write-Host "Dev servers started in separate windows. Close those windows to stop them." -ForegroundColor Green
  }

  "test" {
    $py = Initialize-DevEnv
    Push-Location (Join-Path $Root "backend")
    try { Invoke-Checked $py @("-m", "pytest", "-q") } finally { Pop-Location }
    Push-Location (Join-Path $Root "frontend")
    try { Invoke-Checked npm @("run", "typecheck") } finally { Pop-Location }
    Write-Host "All checks passed." -ForegroundColor Green
  }
}
