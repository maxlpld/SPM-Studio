# Changelog

All notable changes to SPM Studio. Each `## x.y.z` section is what users see in
*Settings › Check for updates…* and what the release workflow publishes as the GitHub Release notes,
so write it for users. Add new versions **at the top**.

The internal builds that preceded the GitHub project (0.7.0 – 0.8.3) are documented in
[`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md).

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
