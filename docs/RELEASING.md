# Releasing SPM Studio (maintainer guide)

Users install with one command and get updates from the **GitHub Releases** of the repository named in
`src/spm_studio/update_config.json → repository`. Releases are made by GitHub Actions when you push a
version tag; you never build or upload archives by hand.

The first upload of the repository is described step by step in [`../GITHUB_FIRST_UPLOAD.md`](../GITHUB_FIRST_UPLOAD.md).
This page is the reference.

## How it fits together

| Piece | File | Role |
|---|---|---|
| Version (single source) | `pyproject.toml` → `version` | Read by the app (`importlib.metadata`, falling back to `pyproject.toml`), the installers (release folder name), the release workflow and the update check. |
| Release notes | `CHANGELOG.md` → `## x.y.z — date` | Published as the GitHub Release text; shown in *Check for updates*. |
| Repository | `src/spm_studio/update_config.json` | Where installed copies look for updates. Set with `release_tools.py set-repo`. |
| Tests on every push | `.github/workflows/tests.yml` (+ `test-suite.yml`) | Syntax, packaging, versions, installer dry run, headless self-test, pytest. |
| Release | `.github/workflows/release.yml` | Tag → checks → tests on Linux/Windows/macOS → GitHub Release. |
| Helpers | `tools/release_tools.py` | `bump`, `set-repo`, `show-repo`, `check-repo`, `check-tag`, `check-changelog`, `notes`, `archive`. |
| Bootstrap | `get-spm-studio.sh`, `get-spm-studio.ps1` | Download a released version and run its own installer. |
| Updater | `src/spm_studio/core/updates.py`, `ui/update_dialog.py` | Check, show notes, download, run the installer in a terminal. |

**What a release contains.** `SPM-Studio-<version>.zip` (the repository's files, one archive for every
operating system, top folder `SPM-Studio-<version>/`) and `SHA256SUMS.txt`. These are **source** archives,
not compiled executables: each installer creates a private Python virtual environment on the user's
computer and installs the dependencies from PyPI. GitHub additionally offers its automatic
*Source code (zip/tar.gz)* downloads for every tag; the installers work with those too (they need no `.git`
folder).

**What a normal push does.** Runs the tests. Nothing is published and no installed copy sees it.

## Configure the repository (once, and after a rename or transfer)

```bash
python tools/release_tools.py set-repo OWNER/SPM-Studio
python tools/release_tools.py show-repo
git commit -am "Point SPM Studio at OWNER/SPM-Studio" && git push
```

`set-repo` rewrites the repository name in the README, install guides, get-scripts, these docs and
`update_config.json`. The release workflow refuses to publish while the project still points at the
placeholder or at a different repository (`check-repo`), because installed copies could then never find
their updates.

## Publish a version

```bash
python -m pytest -q                                   # 1. tests pass locally
python tools/release_tools.py bump 0.0.2              # 2. pyproject version, README badge, CHANGELOG stub
#    3. edit CHANGELOG.md: replace "Describe what is new for users." with the real notes
python tools/release_tools.py check-changelog         # 4. ok 0.0.2
git add -A && git commit -m "SPM Studio 0.0.2"
git tag v0.0.2
git push origin main v0.0.2                           # 5. publish
```

The **Publish release** workflow then:

1. checks the tag is exactly `v` + the `pyproject.toml` version (`check-tag`), the repository setting
   (`check-repo`) and that the CHANGELOG section exists and the README badge matches (`check-changelog`);
2. runs the full test suite and headless self-test on Ubuntu, Windows and macOS;
3. builds `SPM-Studio-0.0.2.zip` and `SHA256SUMS.txt`, and creates the release **SPM Studio 0.0.2** with
   the CHANGELOG section as its notes.

If any step fails, nothing is published.

Installed copies then show **“SPM Studio 0.0.2 is available”** (status bar, at most once a day, or at once
via *Settings › Check for updates…*), with the notes of every version newer than theirs. *Install update*,
`spm-studio --update` and the README command download the tag's archive and run its own installer, which
builds the new version next to the old one and switches only after its self-test passes.

### Rules

- Version format: `MAJOR.MINOR.PATCH` (`0.0.2`, `0.1.0`, `1.0.0`). Tags that are not versions are ignored by
  the update check.
- Pre-releases: `bump 0.1.0rc1`, tag `v0.1.0rc1`. The workflow marks it as a GitHub *pre-release*; it is
  offered only to users who set `"include_prereleases": true` in `update_config.json`.
- Never move or reuse a published tag. Publish a new version instead.
- `CHANGELOG.md` must contain only released (or about to be released) versions; history of the internal
  builds is in [`DEVELOPMENT_HISTORY.md`](DEVELOPMENT_HISTORY.md).

## Recovering from a failed release

| What happened | What to do |
|---|---|
| *Tag … does not match pyproject version* | Delete the tag, fix the version, tag again (see below). |
| *still points at the placeholder* / *points at X, but this is Y* | `set-repo OWNER/NAME`, commit, push, re-tag (below). |
| *CHANGELOG.md has no … section* / *README.md shows version …* | Write the notes or run `bump <version>`, commit, push, re-tag. |
| Tests failed | Fix the code, commit, push, re-tag. |
| Tests passed but *Publish* failed (network, GitHub outage) | Actions › *Publish release* › failed run › **Re-run failed jobs**, or **Run workflow** with the tag. An existing release is updated, not duplicated. |
| You published a broken version | Publish a fixed version (e.g. 0.0.3) as soon as possible. Optionally mark the broken release as *pre-release* on GitHub (it is then no longer offered) or delete it. Users who already installed it keep their previous version next to it and can switch back by re-running its installer `--activate`. |

**Re-tag** after fixing (only for a tag whose release was *not* published):

```bash
git tag -d v0.0.2                    # local
git push origin :refs/tags/v0.0.2    # on GitHub
# fix, commit, push, then:
git tag v0.0.2 && git push origin v0.0.2
```

If a release object was created but you want to start over:
`gh release delete v0.0.2 --cleanup-tag --yes`, then tag again.

Manual fallback without Actions (e.g. Actions disabled): run the tests locally, then

```bash
python tools/release_tools.py archive dist
(cd dist && sha256sum *.zip > SHA256SUMS.txt)          # macOS: shasum -a 256 *.zip > SHA256SUMS.txt
python tools/release_tools.py notes 0.0.2 > release_notes.md
gh release create v0.0.2 dist/*.zip dist/SHA256SUMS.txt --title "SPM Studio 0.0.2" --notes-file release_notes.md
```

## Private repositories

- **Actions:** private repositories have a monthly allowance of free minutes (2,000 on GitHub Free), and
  Windows/macOS jobs count 2×/10×. Every push therefore tests Linux only; Windows and macOS are tested on
  pull requests, manual runs and every release (one release ≈ 100 allowance minutes). Set the repository
  variable `FULL_TEST_MATRIX` to `true` (*Settings › Secrets and variables › Actions › Variables*) to test
  every OS on every push. After the repository becomes public, every push tests all OSes for free.
- **Installation and updates** need a GitHub sign-in on each user's computer. The scripts and the updater
  look for, in this order: `SPM_STUDIO_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, then the GitHub CLI
  (`gh auth token`). With a credential they use the authenticated API endpoints (`/releases`, `/tags`,
  `/contents/CHANGELOG.md`, `/zipball/<tag>`); the credential is sent only to `api.github.com` and is
  dropped when GitHub redirects the download to its signed storage URL. Nothing is stored by SPM Studio.
- **No credential is ever built into SPM Studio.** A token embedded in the application would let anyone
  holding a copy read the repository.
- The `GITHUB_TOKEN` of the workflow only exists inside GitHub Actions; it is not available to users.

## Switching the repository from private to public

1. Review files and the whole Git history for sensitive content (commands in
   [`GITHUB_FIRST_UPLOAD.md` › D1](../GITHUB_FIRST_UPLOAD.md#d1-check-for-sensitive-information-first)).
2. *Settings › General › Danger Zone › Change visibility › Public*.
3. Check the plain one-line commands from the README on a machine without a GitHub sign-in, and
   `SPM_STUDIO_USE_GH_CLI=0 spm-studio --check-update`.
4. Nothing changes for installed copies: without a credential they simply use anonymous access, and with
   one they keep working too.

## Forks and other repositories

`SPM_STUDIO_UPDATE_REPO=owner/name` overrides the repository for the in-app update check, and
`SPM_REPO=owner/name` for the get-scripts — useful for testing a fork without editing files.
