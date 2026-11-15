# Remove the SPM Studio APPLICATION installed by install_spm_studio_windows.ps1.
# Default is a dry run. Your scans, results, scripts, settings, conversations and AI accounts
# (in %USERPROFILE%\.config\spm-studio-ai and %USERPROFILE%\.local\share\spm-studio-ai) are kept.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File uninstall_spm_studio_windows.ps1            # dry run
#   ... -File uninstall_spm_studio_windows.ps1 -Apply                 # asks you to type REMOVE NEW SPM
#   ... -Apply -RemoveAiRuntime   also delete the re-downloadable private Node.js and Pi program files
#                                  (your AI sign-ins/keys in ...\ai\pi-agent are still kept)
param([switch]$Apply, [switch]$RemoveAiRuntime)
$ErrorActionPreference = 'Stop'
function Fail([string]$Message) { Write-Host $Message -ForegroundColor Red; exit 2 }
$Base = Join-Path $env:LOCALAPPDATA 'SPMStudio'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'SPM Studio.lnk'
$DesktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'SPM Studio.lnk'
$DataRoot = if ($env:XDG_DATA_HOME) { $env:XDG_DATA_HOME } else { Join-Path $env:USERPROFILE '.local\share' }
$AiRoot = Join-Path $DataRoot 'spm-studio-ai\ai'

$targets = @()
$ready = @(Get-ChildItem (Join-Path $Base 'releases') -Directory -ErrorAction SilentlyContinue |
           Where-Object { Test-Path (Join-Path $_.FullName 'READY') })
if ((Test-Path $Base) -and $ready.Count -eq 0) { Fail "Unrecognized folder $Base (no installer marker): refusing." }
if ($ready.Count -gt 0) { $targets += $Base }
foreach ($lnk in $StartMenu, $DesktopLnk) {
    if (Test-Path $lnk) {
        $target = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk).TargetPath
        if ($target -like "$Base*") { $targets += $lnk }
    }
}
if ($RemoveAiRuntime) {
    foreach ($sub in 'node', 'runtime') { $p = Join-Path $AiRoot $sub; if (Test-Path $p) { $targets += $p } }
}
Write-Host 'SPM Studio application components to remove:'
if ($targets.Count -eq 0) { Write-Host '  (nothing installed)' } else { $targets | ForEach-Object { Write-Host "  $_" } }
Write-Host 'Always kept: scans, results, scripts, settings, conversations, AI sign-ins/keys, Ollama and its models.'
if (-not $Apply) { Write-Host 'Dry run only. Add -Apply to remove.'; exit 0 }
$ack = Read-Host 'Type REMOVE NEW SPM to continue'
if ($ack -ne 'REMOVE NEW SPM') { Write-Host 'Cancelled'; exit 2 }
foreach ($p in $targets) {
    if ((Get-Item -LiteralPath $p).Attributes -band [IO.FileAttributes]::ReparsePoint) { Write-Host "Refusing link: $p"; continue }
    Remove-Item -Recurse -Force -LiteralPath $p
    Write-Host "Removed $p"
}
Write-Host 'Done. User data preserved.'
