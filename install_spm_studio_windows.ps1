# SPM Studio - isolated, two-stage, per-user installer for Windows 10/11.
# Same design as the Ubuntu installer: build the new release in its own folder with its
# own Python environment, run the offscreen self-test, and only then switch the Start-menu
# and desktop shortcuts to it. Never deletes scans, results, scripts, settings or AI accounts.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_spm_studio_windows.ps1            # stage + activate
#   ... -File install_spm_studio_windows.ps1 -Mode DryRun | Stage | Activate | PruneOld
#   ... -NoDesktopShortcut    (Start menu entry only)
param(
    [ValidateSet('Install', 'Stage', 'Activate', 'DryRun', 'PruneOld')]
    [string]$Mode = 'Install',
    [switch]$NoDesktopShortcut
)
$ErrorActionPreference = 'Stop'
function Fail([string]$Message) { Write-Host $Message -ForegroundColor Red; exit 2 }
Set-StrictMode -Version 2

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Toml = Join-Path $Root 'pyproject.toml'
if (-not (Test-Path $Toml) -or -not (Test-Path (Join-Path $Root 'src\spm_studio\ai\chat_ui.py'))) {
    Fail 'Run this script from the extracted SPM_Studio folder.'
}
$Version = (Select-String -Path $Toml -Pattern '^version = "(.+)"' | Select-Object -First 1).Matches[0].Groups[1].Value
if (-not $Version) { Fail 'Cannot read the version from pyproject.toml' }

# Not under OneDrive/roaming: LOCALAPPDATA stays on this PC.
$Base     = Join-Path $env:LOCALAPPDATA 'SPMStudio'
$Releases = Join-Path $Base 'releases'
$Release  = Join-Path $Releases $Version
$App      = Join-Path $Release 'app'
$Venv     = Join-Path $Release 'venv'
$Py       = Join-Path $Venv 'Scripts\python.exe'
$PyW      = Join-Path $Venv 'Scripts\pythonw.exe'
$BinDir   = Join-Path $Base 'bin'
$Launcher = Join-Path $BinDir 'spm-studio.cmd'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'SPM Studio.lnk'
$DesktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'SPM Studio.lnk'

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
if (Test-Admin) {
    Write-Host 'Please run this installer from a normal (not "Run as Administrator") window.' -ForegroundColor Yellow
    Write-Host 'SPM Studio installs for your user account only and never needs administrator rights.'
    exit 2
}

function Get-PythonVersion([string]$Exe, [string[]]$PreArgs) {
    try {
        $out = & $Exe @PreArgs -c "import sys;print('%d.%d' % sys.version_info[:2]);print(sys.executable)" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $lines = @($out)
        $v = [version]$lines[0]
        if ($v -ge [version]'3.11') { return @{ Version = $lines[0]; Path = $lines[1] } }
    } catch { }
    return $null
}

function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($tag in '-3.13', '-3.12', '-3.11', '-3') { $candidates += ,@('py', @($tag)) }
    }
    foreach ($name in 'python', 'python3') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # Skip the Microsoft Store "python.exe" stub, which opens the Store instead of running.
        if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { $candidates += ,@($cmd.Source, @()) }
    }
    foreach ($v in '313', '312', '311') {
        $p = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
        if (Test-Path $p) { $candidates += ,@($p, @()) }
    }
    foreach ($c in $candidates) {
        $info = Get-PythonVersion $c[0] $c[1]
        if ($info) { return $info }
    }
    return $null
}

function Install-PythonWithWinget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    $answer = Read-Host 'Python 3.11+ was not found. Install Python 3.12 for your user with winget now? [Y/n]'
    if ($answer -and $answer -notmatch '^[Yy]') { return $false }
    & winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Smoke {
    if (-not (Test-Path $Py)) { Fail 'Staged interpreter missing' }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('spm-smoke-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $saved = @{}
    $vars = @{ QT_QPA_PLATFORM = 'offscreen'; XDG_DATA_HOME = "$tmp\data"; XDG_CONFIG_HOME = "$tmp\config";
               XDG_CACHE_HOME = "$tmp\cache"; PYTHONIOENCODING = 'utf-8' }
    foreach ($k in $vars.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $vars[$k]) }
    try {
        & $Py -c "import spm_studio, spm_studio.ai.pi_setup, spm_studio.ai.judge_proxy; from pathlib import Path; print('Standalone SPM Studio source:', Path(spm_studio.__file__).resolve())"
        if ($LASTEXITCODE -ne 0) { Fail 'Import check failed' }
        $outFile = Join-Path $tmp 'out.txt'; $errFile = Join-Path $tmp 'err.txt'
        $p = Start-Process -FilePath $Py -ArgumentList '-m', 'spm_studio', '--smoke-test' -NoNewWindow -PassThru `
             -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $null = $p.Handle   # PowerShell 5.1: keep the handle so ExitCode is available afterwards
        if (-not $p.WaitForExit(180000)) { $p.Kill(); Fail 'Smoke test timed out after 180 s' }
        $out = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
        $err = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
        if ($out) { Write-Host $out }
        if (-not $out -or $out -notmatch 'SMOKE PASSED' -or $p.ExitCode -ne 0) {
            if ($err) { Write-Host $err -ForegroundColor Red }
            Write-Host 'SMOKE FAILED - nothing was activated. Your current SPM Studio (if any) is unchanged.' -ForegroundColor Red
            exit 2
        }
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
        Remove-Item -Recurse -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
    }
}

function Invoke-Stage {
    $py = Find-Python
    if (-not $py) {
        if (Install-PythonWithWinget) { $py = Find-Python }
    }
    if (-not $py) {
        Write-Host 'Python 3.11 or newer is required.' -ForegroundColor Yellow
        Write-Host 'Install it from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH"),'
        Write-Host 'or run:  winget install -e --id Python.Python.3.12 --scope user'
        Write-Host 'then run this installer again.'
        exit 2
    }
    Write-Host "Python: $($py.Version) ($($py.Path))"
    $drive = (Get-Item $env:LOCALAPPDATA).PSDrive
    if ($drive.Free -lt 1.5GB) { Fail 'At least 1.5 GB of free disk space is needed.' }
    if ((Test-Path (Join-Path $Release 'READY')) -and (Test-Path $Py)) {
        Write-Host "Existing staged release: $Release"; Invoke-Smoke; return
    }
    if (Test-Path $Release) {
        Fail "A partial release exists at $Release. Delete that folder and run again (nothing else is affected)." 
    }
    New-Item -ItemType Directory -Force -Path $Release | Out-Null
    Write-Host 'Copying application files...'
    Copy-Item -Recurse -Path $Root -Destination $App
    Get-ChildItem -Path $App -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    Write-Host 'Creating the private Python environment...'
    & $py.Path -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'python -m venv failed' }
    & $Py -m pip install --upgrade pip
    & $Py -m pip install -e "$App[all]"
    if ($LASTEXITCODE -ne 0) { Fail 'pip install failed (see messages above); nothing was activated.' }
    Invoke-Smoke
    Set-Content -Path (Join-Path $Release 'READY') -Value $Version -Encoding ASCII
    Write-Host "Release staged and tested: $Release" -ForegroundColor Green
}

function New-Shortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $PyW
    $lnk.Arguments = '-m spm_studio'
    $lnk.WorkingDirectory = $env:USERPROFILE
    $lnk.IconLocation = (Join-Path $App 'assets\spm-studio.ico') + ',0'
    $lnk.Description = 'SPM Studio - scientific image and data analysis with optional AI assistant'
    $lnk.Save()
}

function Invoke-Activate {
    if (-not (Test-Path (Join-Path $Release 'READY'))) { Fail 'Stage and test first with -Mode Stage.' }
    Invoke-Smoke
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    Set-Content -Path (Join-Path $Base 'current.txt') -Value $Version -Encoding ASCII
    $cmd = "@echo off`r`nrem Managed by the SPM Studio installer`r`n`"$Py`" -m spm_studio %*`r`n"
    [IO.File]::WriteAllText($Launcher, $cmd, [Text.Encoding]::ASCII)
    New-Shortcut $StartMenu
    if (-not $NoDesktopShortcut) { New-Shortcut $DesktopLnk }
    Write-Host ''
    Write-Host "SPM Studio $Version installed successfully." -ForegroundColor Green
    $where = 'Launch: Start menu > SPM Studio'
    if (-not $NoDesktopShortcut) { $where += ' (or the desktop icon)' }
    Write-Host $where
    Write-Host "From a terminal: `"$Launcher`""
    Write-Host "Installed release: $Release"
    Write-Host 'AI: click "Assistant" in the header. "Set up Pi" installs and configures everything for you.'
    Write-Host 'Older releases are kept until you run:  install_spm_studio_windows.bat -Mode PruneOld'
}

function Invoke-DryRun {
    Write-Host "Version:            $Version"
    Write-Host "Source:             $Root"
    Write-Host "New isolated release: $Release"
    Write-Host "Start menu entry:   $StartMenu"
    if (-not $NoDesktopShortcut) { Write-Host "Desktop shortcut:   $DesktopLnk" }
    Write-Host "Command launcher:   $Launcher"
    $py = Find-Python
    if ($py) { Write-Host "Python found:       $($py.Version) ($($py.Path))" }
    else { Write-Host 'Python found:       none (the installer can install Python 3.12 with winget)' }
    if (Test-Path $Releases) {
        Get-ChildItem $Releases -Directory | Where-Object { $_.FullName -ne $Release -and (Test-Path (Join-Path $_.FullName 'READY')) } |
            ForEach-Object { Write-Host "Previous release kept (remove later with -Mode PruneOld): $($_.FullName)" }
    }
    Write-Host 'Nothing is installed or removed in dry-run mode.'
}

function Invoke-PruneOld {
    $currentFile = Join-Path $Base 'current.txt'
    if (-not (Test-Path $currentFile)) { Fail 'No active release found; refusing to prune.' }
    $current = (Get-Content $currentFile -Raw).Trim()
    $targets = @(Get-ChildItem $Releases -Directory | Where-Object { $_.Name -ne $current -and (Test-Path (Join-Path $_.FullName 'READY')) })
    if ($targets.Count -eq 0) { Write-Host 'No previous release to remove.'; return }
    Write-Host "Active release (kept): $current"
    $targets | ForEach-Object { Write-Host "  remove: $($_.FullName)" }
    Write-Host 'Your scans, results, scripts, settings, AI accounts and Ollama models are NOT touched.'
    $ack = Read-Host 'Type REMOVE OLD RELEASES to continue'
    if ($ack -ne 'REMOVE OLD RELEASES') { Write-Host 'Cancelled'; exit 2 }
    $targets | ForEach-Object { Remove-Item -Recurse -Force -LiteralPath $_.FullName; Write-Host "Removed $($_.FullName)" }
}

switch ($Mode) {
    'DryRun'   { Invoke-DryRun }
    'Stage'    { Invoke-Stage }
    'Activate' { Invoke-Activate }
    'Install'  { Invoke-Stage; Invoke-Activate }
    'PruneOld' { Invoke-PruneOld }
}
