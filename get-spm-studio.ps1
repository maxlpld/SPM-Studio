# Install or update SPM Studio on Windows from GitHub, in one command (normal PowerShell window,
# NOT "Run as administrator").
#
# Public repository:
#   irm https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.ps1 | iex
#
# Private repository (invited collaborators; sign in once with the GitHub CLI: gh auth login):
#   gh api -H "Accept: application/vnd.github.raw" repos/maxlpld/SPM-Studio/contents/get-spm-studio.ps1 | Out-String | iex
#
# It downloads the newest released version (or $env:SPM_VERSION = '0.0.1'), then runs that version's own
# install_spm_studio_windows.ps1, which builds the new release next to the current one, self-tests it,
# and only then switches the Start-menu/desktop shortcuts. Running it again later updates SPM Studio.
# Your scans, results, tools, settings and AI accounts are kept.
# Options: $env:SPM_VERSION, $env:SPM_INSTALL_ARGS (e.g. '-NoDesktopShortcut'), $env:SPM_REPO (owner/name)
# Private repositories: the GitHub sign-in is taken from $env:SPM_STUDIO_GITHUB_TOKEN, $env:GH_TOKEN,
# $env:GITHUB_TOKEN or `gh auth token` ($env:SPM_STUDIO_USE_GH_CLI = '0' disables the latter). It is kept
# in memory only and sent only to api.github.com.
& {
    $ErrorActionPreference = 'Stop'     # scoped to this block: the user's session is not changed
    $Repo = if ($env:SPM_REPO) { $env:SPM_REPO } else { 'maxlpld/SPM-Studio' }
    if ($Repo -like 'YOUR_GITHUB_USER/*') {
        Write-Host 'This copy of get-spm-studio.ps1 is not configured yet: set $env:SPM_REPO = "owner/SPM-Studio".' -ForegroundColor Red
        return
    }
    $Api = "https://api.github.com/repos/$Repo"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $headers = @{ 'User-Agent' = 'SPM-Studio-installer'; 'Accept' = 'application/vnd.github+json' }

    # Optional GitHub sign-in for private repositories (memory only).
    $token = @($env:SPM_STUDIO_GITHUB_TOKEN, $env:GH_TOKEN, $env:GITHUB_TOKEN) | Where-Object { $_ } | Select-Object -First 1
    if (-not $token -and @('0', 'false', 'no', 'off') -notcontains "$env:SPM_STUDIO_USE_GH_CLI".ToLower() -and (Get-Command gh -ErrorAction SilentlyContinue)) {
        try { $token = (& gh auth token --hostname github.com 2>$null | Out-String).Trim() } catch { $token = $null }
        if ($LASTEXITCODE -ne 0) { $token = $null }
    }
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    Remove-Variable token -ErrorAction SilentlyContinue

    $tag = $null
    if ($env:SPM_VERSION) {
        $tag = 'v' + $env:SPM_VERSION.TrimStart('v')
    } else {
        try { $tag = (Invoke-RestMethod -Uri "$Api/releases/latest" -Headers $headers).tag_name } catch { $tag = $null }
        if (-not $tag) {
            try {
                $tags = Invoke-RestMethod -Uri "$Api/tags?per_page=100" -Headers $headers |
                        ForEach-Object { $_.name } | Where-Object { $_ -match '^v?\d+\.\d+(\.\d+)?$' }
                $tag = $tags | Sort-Object { [version]($_.TrimStart('v')) } -Descending | Select-Object -First 1
            } catch { $tag = $null }
        }
    }
    if (-not $tag) {
        if ($headers.ContainsKey('Authorization')) {
            Write-Host "No released version found at https://github.com/$Repo, or your GitHub account has no access to it." -ForegroundColor Red
        } else {
            Write-Host "No released version found at https://github.com/$Repo." -ForegroundColor Red
            Write-Host "If the repository is private: install the GitHub CLI (winget install GitHub.cli), run 'gh auth login' once, then run this command again." -ForegroundColor Yellow
        }
        return
    }
    $version = $tag.TrimStart('v')
    $existing = Test-Path (Join-Path $env:LOCALAPPDATA 'SPMStudio\current.txt')
    if ($existing) { Write-Host "Updating SPM Studio to $version from github.com/$Repo" -ForegroundColor Cyan }
    else { Write-Host "Installing SPM Studio $version from github.com/$Repo" -ForegroundColor Cyan }

    $work = Join-Path ([IO.Path]::GetTempPath()) ('spm-get-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $zip = Join-Path $work 'spm.zip'
        $old = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'    # much faster download on PS 5.1
        if ($headers.ContainsKey('Authorization')) {
            # Private: authenticated API archive. GitHub answers with a redirect to a signed URL on another
            # host; follow it manually so the credential is never sent there.
            $req = [Net.HttpWebRequest]::Create("$Api/zipball/$tag")
            $req.AllowAutoRedirect = $false
            $req.UserAgent = 'SPM-Studio-installer'
            $req.Headers['Authorization'] = $headers['Authorization']
            $resp = $req.GetResponse()
            $location = $resp.Headers['Location']; $resp.Close()
            if (-not $location) { throw 'GitHub did not return a download location' }
            Invoke-WebRequest -Uri $location -OutFile $zip -Headers @{ 'User-Agent' = 'SPM-Studio-installer' } -UseBasicParsing
        } else {
            Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/tags/$tag.zip" -OutFile $zip -Headers @{ 'User-Agent' = 'SPM-Studio-installer' } -UseBasicParsing
        }
        $ProgressPreference = $old
        $headers.Remove('Authorization')
        Expand-Archive -Path $zip -DestinationPath (Join-Path $work 'src')
        $toml = Get-ChildItem -Path (Join-Path $work 'src') -Recurse -Depth 2 -Filter 'pyproject.toml' | Select-Object -First 1
        if (-not $toml) { Write-Host 'The downloaded archive does not contain SPM Studio' -ForegroundColor Red; return }
        $src = $toml.DirectoryName
        $installer = Join-Path $src 'install_spm_studio_windows.ps1'
        if (-not (Test-Path $installer)) { Write-Host 'Installer missing in the download' -ForegroundColor Red; return }
        $extra = @()
        if ($env:SPM_INSTALL_ARGS) { $extra = $env:SPM_INSTALL_ARGS -split '\s+' | Where-Object { $_ } }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer @extra
        if ($LASTEXITCODE -ne 0) { Write-Host "The installer stopped (code $LASTEXITCODE). Read the messages above." -ForegroundColor Red }
    } finally {
        Remove-Item -Recurse -Force -LiteralPath $work -ErrorAction SilentlyContinue
    }
}
