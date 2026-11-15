# SPM Studio 0.0.1 — install on macOS 12+ (Apple Silicon and Intel)

Download: **`SPM-Studio-0.0.1.zip`** from the repository's *Releases* page (one archive for every operating system; for a private repository you must be signed in to GitHub)
(same application and AI assistant as the Ubuntu and Windows versions).

The zip contains only the application source: no virtual environment, no API keys, no login tokens, no AI
chat history, no personal scans/results, no Pi configuration. It was checked for secrets before release.

## Easiest: one command (installs or updates)

```bash
curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash
```

It downloads the newest release from GitHub and runs the installer below (Python 3.12 or 3.13 must be installed
first, see Requirements). Run it again at any time to update. Later updates: **Settings › Check for
updates…** in the app, or `~/.local/bin/spm-studio --update`.

**Private repository** (while the project is private, the command above cannot download anything): sign in
once with the GitHub CLI (`sudo apt install gh` / `brew install gh`, then `gh auth login`) and use

```bash
gh api -H 'Accept: application/vnd.github.raw' repos/maxlpld/SPM-Studio/contents/get-spm-studio.sh | bash
```

The script and later in-app updates then use that sign-in automatically. See `README.md › Private repository`.

The manual install from the downloaded archive works exactly as before:

## Requirements

- macOS 12 Monterey or newer, your normal user account (never `sudo`).
- **Python 3.12 or 3.13** — the `python3` that comes with the Xcode command-line tools is too old. Install the
  official one from https://www.python.org/downloads/macos/ (recommended), or with Homebrew
  `brew install python@3.12` (the installer offers this when Homebrew is present).
- ~1.5 GB free disk space, internet for the one-time dependency download.

## Install (Terminal, copy/paste)

```bash
cd ~/Downloads
unzip -q SPM-Studio-0.0.1.zip
cd SPM-Studio-0.0.1
bash install_spm_studio_macos.sh
open ~/Applications/"SPM Studio.app"
```

(If Safari already unzipped the download, use `cd ~/Downloads/SPM-Studio-0.0.1`
instead of the `unzip` line.) You can also double-click `install_spm_studio_macos.command` in Finder; if
macOS refuses, right-click it › *Open*, or use the Terminal commands above.

The installer copies the app to `~/Library/Application Support/SPMStudio/releases/0.0.1`, creates its own
Python environment there, installs the dependencies, runs the offscreen self-test (`SMOKE PASSED`) and only
then creates **`~/Applications/SPM Studio.app`** (Spotlight: “SPM Studio”) and the command
`~/.local/bin/spm-studio`. If it prints `SMOKE FAILED`, nothing was activated — read the printed error
before retrying.

Options: `--dry-run`, `--stage` / `--activate` (two steps), `--prune-old` (remove older releases after an upgrade).

## Connecting the AI assistant

The scientific application needs **no** Pi, Ollama, API key or Node.js. To use the assistant, click
**Assistant** in the header; the first time, a dialog offers:

- **Set up Pi** (pre-selected when no Pi is installed) — *Start guided setup…* does everything: private
  Node.js if needed (from nodejs.org, checksum-verified), Pi + smart routing + subagents, sign-in with ChatGPT
  Plus/Pro or GitHub Copilot in your browser (a Terminal window opens with the exact command to type) or
  paste an API key, model choice, then it asks **“Would you like a small local AI model to pre-classify
  your requests…?”** — if yes it checks your Mac (Apple-Silicon unified memory is used by the GPU),
  proposes three models, installs Ollama (Ollama.app copied to Applications), downloads the model and tests
  it. Ends with a real test message. A personal `~/.pi` is never touched.
- **My Pi** — reuse an existing Pi with its own configuration, unchanged.
- **Claude / Codex** — Claude Code (official installer) or OpenAI Codex CLI with their own sign-in.
- **Cloud API** — direct chat with OpenAI / Anthropic / Gemini / OpenRouter / local Ollama (key in the macOS Keychain).
- **Later** — assistant off.

The first time an agent opens it asks once whether it may work in `~/.local/share/spm-studio-ai/scripts`
(the Tools folder). Say yes to let it create/edit analysis tools there. Full guide: `docs/AI_ASSISTANT_SETUP.md`.

## Push-to-talk voice input

Hold the mic button or **F11** (on laptops: **fn + F11**, or disable the F11 *Show Desktop* shortcut in
System Settings › Keyboard › Keyboard Shortcuts). macOS asks once for microphone access. The ~40 MB offline
speech model is fetched once after you confirm; afterwards transcription is fully offline.

## Where your data lives

| What | Folder |
|---|---|
| Application (replaceable) | `~/Library/Application Support/SPMStudio`, `~/Applications/SPM Studio.app` |
| Tools, results, AI conversations, private Node.js/Pi | `~/.local/share/spm-studio-ai` |
| Settings, themes, profiles | `~/.config/spm-studio-ai` |
| Crash log | `~/.cache/spm-studio-ai/crash.log` |

## Uninstall / remove

```bash
cd ~/Downloads/SPM-Studio-0.0.1
bash uninstall_spm_studio_macos.sh                                  # dry run
bash uninstall_spm_studio_macos.sh --apply                          # type: REMOVE NEW SPM
bash uninstall_spm_studio_macos.sh --apply --remove-ai-runtime      # also SPM's private Node.js/Pi program files
```

Your data, AI sign-ins/keys, `~/.pi`, Ollama and its models are always kept.

## Troubleshooting

- **“Python 3.12 or 3.13 is required”**: install Python from python.org (or `brew install python@3.12`), rerun.
- **`SMOKE FAILED`**: nothing switched; `rm -rf ~/Library/Application\ Support/SPMStudio/releases/0.0.1`, retry.
- **“SPM Studio.app can't be opened”**: right-click › *Open* once (the app is created locally by the
  installer and is not notarised).
- **Downloads fail with a certificate error** (python.org Python): run
  `/Applications/Python\ 3.12/Install\ Certificates.command` once — SPM Studio itself uses `certifi`.
