<#
.SYNOPSIS
Instala o OmniOne e remove atalhos antigos.

.DESCRIPTION
This script:
1. Removes old batch file shortcuts from Desktop
2. Copia o OmniOne para um local permanente
3. Creates a shortcut in Startup folder for auto-start
4. Creates a Desktop shortcut
5. Optionally starts the tray app immediately
#>

param(
    [switch]$AutoStart = $true,
    [switch]$StartNow = $true
)

$ErrorActionPreference = "Stop"

Write-Host "=== Instalador OmniOne ===" -ForegroundColor Cyan
Write-Host ""

# Paths
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$exeSource = Join-Path $scriptDir "dist\OmniOne Tray.exe"
$installDir = Join-Path $env:LOCALAPPDATA "OmniOneTray"
$exeTarget = Join-Path $installDir "OmniOne Tray.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$startup = [Environment]::GetFolderPath("Startup")

# 1. Verify source exists
if (-not (Test-Path $exeSource)) {
    Write-Error "Source executable not found at: $exeSource"
    Write-Host "Crie o executável primeiro: python -m PyInstaller omnione_tray.spec" -ForegroundColor Red
    exit 1
}

# 2. Create install directory
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    Write-Host "[OK] Created install directory: $installDir" -ForegroundColor Green
}

# 3. Close an older OmniOne instance so the executable can be updated safely.
$runningApps = Get-Process -Name "OmniOne Tray" -ErrorAction SilentlyContinue
if ($runningApps) {
    Write-Host "[OK] Encerrando a versão anterior do OmniOne..." -ForegroundColor Yellow
    $runningApps | Stop-Process -Force
    Start-Sleep -Seconds 1
}

# 4. Copy executable
Copy-Item -Path $exeSource -Destination $exeTarget -Force
Write-Host "[OK] Copied executable to: $exeTarget" -ForegroundColor Green

# 4. Remove old shortcuts from Desktop
$oldShortcuts = @(
    "Claude Code + OmniRoute.lnk",
    "Parar OmniRoute.lnk",
    "Status OmniRoute.lnk",
    "OmniRoute Tray.lnk"
)

foreach ($shortcut in $oldShortcuts) {
    $path = Join-Path $desktop $shortcut
    if (Test-Path $path) {
        Remove-Item -Path $path -Force
        Write-Host "[OK] Removed old shortcut: $shortcut" -ForegroundColor Yellow
    }
}

# 5. Create Desktop shortcut
$shortcutPath = Join-Path $desktop "OmniOne.lnk"
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $exeTarget
$sc.WorkingDirectory = $installDir
$sc.Description = "Controlador OmniOne - gerencia o servidor e abre o Claude Code"
$sc.IconLocation = "$exeTarget,0"
$sc.Save()
Write-Host "[OK] Created Desktop shortcut: $shortcutPath" -ForegroundColor Green

# 6. Create Startup shortcut (auto-start with Windows)
if ($AutoStart) {
    $startupShortcut = Join-Path $startup "OmniOne.lnk"
    $sc2 = $wsh.CreateShortcut($startupShortcut)
    $sc2.TargetPath = $exeTarget
    $sc2.WorkingDirectory = $installDir
    $sc2.Description = "Controlador OmniOne (inicialização automática)"
    $sc2.IconLocation = "$exeTarget,0"
    $sc2.Save()
    Write-Host "[OK] Created Startup shortcut for auto-start" -ForegroundColor Green
}

# 7. Start the app now
if ($StartNow) {
    Write-Host ""
    Write-Host "Iniciando OmniOne..." -ForegroundColor Cyan
    Start-Process -FilePath $exeTarget -WorkingDirectory $installDir
    Write-Host "[OK] OmniOne iniciado - verifique a bandeja do sistema" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Instalação concluída ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "O OmniOne foi instalado em:"
Write-Host "  $exeTarget"
Write-Host ""
Write-Host "Features:"
Write-Host "  - Single tray icon in taskbar (green=running, red=stopped)"
Write-Host "  - Iniciar, parar e reiniciar o servidor OmniOne"
Write-Host "  - Launch Claude Code in any workspace"
Write-Host "  - View logs and open dashboard"
Write-Host "  - Auto-starts with Windows"
Write-Host ""
Write-Host "Old batch file shortcuts have been removed from Desktop."
Write-Host ""
