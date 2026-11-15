# Contributing to SPM Studio

Thank you for helping. Bug reports, tests on real data, documentation fixes and new analysis tools are all
welcome.

## Get the source

```bash
git clone https://github.com/maxlpld/SPM-Studio.git
# private repository: sign in once with `gh auth login`, then
gh repo clone maxlpld/SPM-Studio
cd SPM-Studio
```

## Development environment

Python 3.11 or newer. On Ubuntu also install the Qt system libraries
(`sudo apt install python3-venv libxcb-cursor0 libgl1 libegl1 libxkbcommon-x11-0`).

```bash
python3 -m venv .venv
. .venv/bin/activate                    # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[all,dev]'
```

The editable install (`-e`) means changes to `src/spm_studio` take effect the next time you start the app.
This development copy is independent of an installed SPM Studio and uses the same user data folders.

## Run and test

```bash
python -m spm_studio                                          # start from source
QT_QPA_PLATFORM=offscreen python -m spm_studio --smoke-test   # headless self-test (prints SMOKE PASSED)
python -m pytest -q                                           # full suite
python -m pytest -q tests/test_processing.py                  # one file
```

Tests that need PySide6, CairoSVG or developer-only reference data skip themselves with a reason
(`pytest -rs` lists them). The installer tests run only as a normal user, never as root.

Please add or update tests with every change. **Do not change scientific algorithms merely to make a test
pass**; if a scientific result changes on purpose, explain why in the pull request and in `CHANGELOG.md`.

## Where things are

| Path | Contents |
|---|---|
| `src/spm_studio/core/` | readers (`io.py`, `sxm_native.py`), processing, export, registry, paths, updates |
| `src/spm_studio/ui/` | Qt main window, panels, dialogs |
| `src/spm_studio/ai/` | assistant: Pi RPC, CLI agents, direct API providers, setup wizards, plugin staging |
| `scripts/` | analysis tools copied to the user's scripts folder; contract in `docs/MODULE_API.md` |
| `customization/` | factory themes, colour maps, profiles, presets, shortcuts |
| `tests/` | pytest suite |
| `tools/release_tools.py` | release helpers (see `docs/RELEASING.md`) |

Writing a new analysis tool: start from `scripts/README_SCRIPT.md` and `docs/MODULE_API.md`; a tool is a
folder with `module.json` and `module.py`.

## Submitting changes

1. Create a branch: `git switch -c fix-gwy-units`.
2. Make focused commits with clear messages.
3. Run the smoke test and the test suite.
4. If users will notice the change, add a line under a new, unreleased heading at the top of `CHANGELOG.md`
   (the maintainer sets the version when releasing).
5. `git push -u origin fix-gwy-units` and open a **pull request** on GitHub. The *Tests* workflow runs on
   Linux, Windows and macOS for pull requests; please keep it green.

Collaborators of the repository can push branches directly; others fork the repository first.

## Ground rules

- Never commit measurement data you are not allowed to share, results, personal paths, API keys, tokens or
  AI conversation logs. `.gitignore` covers the usual cases; check `git status` before committing.
- Keep the installers working for a normal user without administrator rights, and from a downloaded
  archive without a `.git` folder.
- Keep the package name `spm_studio` and the user data locations stable: existing installations and user
  tools depend on them.

## Reporting bugs

Open an issue with: SPM Studio version (*Help › About*), operating system, steps to reproduce, what you
expected and what happened, and the crash log if there is one (`~/.cache/spm-studio-ai/crash.log` on Linux).
Security problems: see [`SECURITY.md`](SECURITY.md) instead.
