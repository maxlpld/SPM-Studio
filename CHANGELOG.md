# Changelog

All notable changes to SPM Studio. Each `## x.y.z` section is what users see in
*Settings › Check for updates…* and what the release workflow publishes as the GitHub Release notes,
so write it for users. Add new versions **at the top**.

The internal builds that preceded the GitHub project (0.7.0 – 0.8.3) are documented in
[`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md).

## 0.0.4 — 2026-11-16

- **Improved first-time Pi assistant setup:** the Models step now proposes Fast/Smart defaults from models listed by connected providers, prefers subscription authentication, and filters out old GPT-4 models that are incompatible with ChatGPT OAuth. Users can override all choices, keep custom choices on refresh, or restore recommendations.
- **Updated ChatGPT subscription sign-in** to match Pi's current OpenAI login flow. The setup still checks actual model access with a live test, since model listings alone do not guarantee access.
- **Prevented unfinished AI setup:** the Finish button is now disabled until Pi answers a real test successfully, making unsupported model errors clear rather than silently accepting a broken setup.
- **Fixed Git installation during Windows Pi setup:** the wizard explicitly selects the `winget` source to bypass a broken Microsoft Store source (certificate error `0x8a15005e`), with manual installation instructions if necessary.
- SPM processing, scientific analysis modules, and existing user data are unchanged. The update is installed beside previous versions.

## 0.0.3 — 2026-11-16

- **Fixed Windows installation from PowerShell.** Python detection now keeps its interpreter-information hashtable separate from the private virtual environment's `python.exe` path. This resolves the `System.Collections.Hashtable is not recognized` failure when installing with Python 3.12 or 3.13, including Anaconda Python.
- Improved cross-platform Qt GUI test shutdown cleanup on Linux, Windows and macOS, preventing native shutdown crashes after otherwise successful tests.
- Kept SPM analysis tools, the optional AI assistant and user data unchanged. An existing incomplete `0.0.2` installation does not block the new `0.0.3` installation because releases are staged in separate directories.

## 0.0.2 — 2026-11-15

- Fixed installation on macOS by selecting Vosk 0.3.44 (its macOS Universal2 wheel) while retaining Vosk 0.3.45 on other platforms.
- Prefer Python 3.12 on macOS and reject untested Python 3.14+ interpreters, preventing accidental use of Python 3.15.
- Removed obsolete private-repository instructions from the public README.
- Improved Linux GUI test stability and crash diagnostics with Xvfb, Qt XCB, and Python faulthandler. All tests remain enabled.
- Improved release CI diagnostics: allow every platform job to finish even when another platform fails, and upgrade GitHub Actions to Node 24-compatible versions.
- Updated Python package metadata to avoid deprecated license-table warnings.

## 0.0.1 — 2026-11-15

First release of SPM Studio from its GitHub repository. The application is functionally the same as the
last internal build (0.8.3): the same scientific tools and the same optional AI assistant, now from one
shared source tree for Ubuntu/Linux, Windows and macOS.

### Install and update from GitHub

- One-command install or update per OS (`get-spm-studio.sh` for Linux and macOS, `get-spm-studio.ps1` for
  Windows). Each command downloads a released version and runs that version's own installer.
- **Private repositories are supported**: the installers and the in-app *Check for updates* use your GitHub
  sign-in from the GitHub CLI (`gh auth login`) or a read-only token in `SPM_STUDIO_GITHUB_TOKEN`. No
  credential is stored in SPM Studio or in the repository.
- *Settings › Check for updates…* shows the installed and the newest version and what is new; *Install update*
  builds the new version next to the current one and switches only after its self-test passes. User data,
  settings, tools and AI accounts are never touched.
- `spm-studio --check-update` and `spm-studio --update` on every OS.

### For maintainers

- Pushing a `vX.Y.Z` tag runs the tests, then publishes a GitHub Release with these notes, one
  cross-platform source archive and `SHA256SUMS.txt`. The workflow checks that the tag matches
  `pyproject.toml` and that the update repository is configured for this GitHub repository.
- `python tools/release_tools.py set-repo OWNER/SPM-Studio` points the README, installers and update check
  at your repository. See `GITHUB_FIRST_UPLOAD.md` and `docs/RELEASING.md`.

### Note for users of the internal 0.8.x builds

Version numbers restart at 0.0.1, so an internal 0.8.x installation does not offer 0.0.1 as an update.
Run the install command from the README once; it installs 0.0.1 next to the old build, and later
versions then arrive through *Check for updates* as usual.
