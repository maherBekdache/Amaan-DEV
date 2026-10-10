<#
.SYNOPSIS
  Start/stop the Amaan stack on Windows (Docker Desktop + WSL2).

.EXAMPLE
  .\scripts\amaan.ps1 up            # URL.vet + Amaan, then open http://localhost:8000
  .\scripts\amaan.ps1 up -UrlvetUi  # also start URL.vet's own web UI on :3000
  .\scripts\amaan.ps1 status
  .\scripts\amaan.ps1 down
  .\scripts\amaan.ps1 update-urlvet # move URL.vet to the pinned ref again
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("setup", "up", "down", "status", "logs", "update-urlvet")]
  [string]$Command = "up",
  [switch]$UrlvetUi
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$UrlvetDir = Join-Path $Root "third_party\urlvet"
$UrlvetRepo = "https://github.com/urlvet/urlvet.git"
# Pinned so the demo does not change under us. Bump deliberately.
$UrlvetRef = if ($env:URLVET_REF) { $env:URLVET_REF } else { "a6b54c29b73a053b916805173fba352e9be0204c" }
$Network = "amaan-urlvet"
$Utf8 = New-Object System.Text.UTF8Encoding $false

function Invoke-Checked([string]$exe, [string[]]$arguments) {
  & $exe @arguments
  if ($LASTEXITCODE -ne 0) { throw "$exe $($arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

function New-Secret {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Assert-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker is not installed. Install Docker Desktop (WSL2 backend)." }
  docker info *> $null
  if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running. Start it and try again." }
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
  docker network inspect $Network *> $null
  if ($LASTEXITCODE -ne 0) { Invoke-Checked docker @("network", "create", $Network) | Out-Null }
}

function Wait-Healthy([string]$url, [int]$seconds) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $url | Out-Null; return $true } catch { Start-Sleep 2 }
  }
  return $false
}

switch ($Command) {
  "setup" { Invoke-Setup; Write-Host "Setup done." -ForegroundColor Green }

  "up" {
    Invoke-Setup
    $services = @("backend", "chrome", "valkey")
    if ($UrlvetUi) { $services += "web" }
    Write-Host "==> Building and starting URL.vet ($($services -join ', '))" -ForegroundColor Cyan
    Invoke-Checked docker ((Get-UrlvetCompose) + @("up", "-d", "--build") + $services)
    Write-Host "==> Building and starting Amaan" -ForegroundColor Cyan
    Push-Location $Root
    try { Invoke-Checked docker @("compose", "up", "-d", "--build") } finally { Pop-Location }
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
    try { docker compose down } finally { Pop-Location }
    if (Test-Path $UrlvetDir) { docker @((Get-UrlvetCompose) + @("down")) }
  }

  "status" {
    Push-Location $Root
    try { docker compose ps } finally { Pop-Location }
    if (Test-Path $UrlvetDir) { docker @((Get-UrlvetCompose) + @("ps")) }
    try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:8000/health").Content } catch { Write-Warning "Amaan is not answering on :8000" }
  }

  "logs" {
    Push-Location $Root
    try { docker compose logs -f --tail 100 } finally { Pop-Location }
  }

  "update-urlvet" {
    Invoke-Checked git @("-C", $UrlvetDir, "fetch", "--quiet", "origin")
    Invoke-Checked git @("-C", $UrlvetDir, "-c", "advice.detachedHead=false", "checkout", "--quiet", $UrlvetRef)
    Write-Host "URL.vet is at $UrlvetRef. Run '.\scripts\amaan.ps1 up' to rebuild." -ForegroundColor Green
  }
}
