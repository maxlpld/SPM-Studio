# SPM Studio 0.0.1 — install on Ubuntu / Linux

Download: **`SPM-Studio-0.0.1.zip`** from the repository's *Releases* page (one archive for every operating system; for a private repository you must be signed in to GitHub)

The zip contains only the application source: no virtual environment, no API keys, no login tokens, no AI
chat history, no personal scans/results, no `~/.pi` configuration. It was checked for secrets before release.

## Easiest: one command (installs or updates)

```bash
curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash
```

It downloads the newest release from GitHub, offers to install the missing Qt packages with `sudo apt`,
and runs the installer below. Run it again at any time to update. Later updates: **Settings › Check for
updates…** in the app, or `spm-studio --update`.

**Private repository** (while the project is private, the command above cannot download anything): sign in
once with the GitHub CLI (`sudo apt install gh` / `brew install gh`, then `gh auth login`) and use

```bash
gh api -H 'Accept: application/vnd.github.raw' repos/maxlpld/SPM-Studio/contents/get-spm-studio.sh | bash
```

The script and later in-app updates then use that sign-in automatically. See `README.md › Private repository`.

The manual install from the downloaded archive works exactly as before:

## Requirements

- Ubuntu 24.04 / 26.04 (or similar), **Python 3.12 or 3.13** with `venv` + `pip`, run as your normal user (never `sudo`).
- ~1.5 GiB free disk space, internet for the one-time dependency download.
- Qt system libraries:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip libxcb-cursor0 libgl1 libegl1 libxkbcommon-x11-0
```

## Install (fresh machine)

```bash
cd ~/Downloads
unzip -q SPM-Studio-0.0.1.zip
cd SPM-Studio-0.0.1
bash install_spm_studio_clean.sh          # builds its own venv, runs the self-test, then activates
~/.local/bin/spm-studio
```

SPM Studio also appears in the application menu. If the installer prints `SMOKE FAILED`, nothing was
activated — read the printed error before retrying.

## Upgrade from 0.8.1 (or 0.7.x) on a PC that already has SPM Studio

```bash
cd ~/Downloads
rm -rf SPM-Studio-0.0.1
unzip -q SPM-Studio-0.0.1.zip
cd SPM-Studio-0.0.1
bash install_spm_studio_clean.sh --stage       # builds 0.0.1 next to the current version + self-test
bash install_spm_studio_clean.sh --activate    # switches the launcher/menu entry to 0.0.1
~/.local/bin/spm-studio
bash install_spm_studio_clean.sh --prune-old   # later, once happy: removes older releases (type REMOVE OLD RELEASES)
```

Scans, results, scripts, settings, conversations, your `~/.pi`, Ollama models and keys are shared and kept.
An assistant already connected to your own Pi stays on **My Pi** — nothing in `~/.pi` is modified.

Check the version in use:

```bash
readlink -f ~/.local/share/spm-studio-ai-app/current        # must end in releases/0.0.1
```

## Connecting the AI assistant

The scientific application needs **no** Pi, Ollama, API key or Node.js. To use the assistant, click
**Assistant** in the header; the first time, a dialog offers:

- **Set up Pi** (pre-selected when no Pi is installed) — *Start guided setup…* does everything:
  private Node.js if needed (checksum-verified), Pi + smart routing + subagents, sign-in with ChatGPT
  Plus/Pro or GitHub Copilot in your browser (or paste an API key), model choice, then asks
  **“Would you like a small local AI model to pre-classify your requests…?”** — if yes it checks your
  RAM/GPU, proposes three models, installs Ollama (official script; it asks for your password in a terminal),
  downloads the model and tests it. Ends with a real test message. Your own `~/.pi` is never touched.
- **My Pi** — reuse your existing Pi with its router/Judge/logins exactly as configured.
- **Claude / Codex** — Claude Code or OpenAI Codex CLI with their own subscription sign-in (Install… / Sign in…).
- **Cloud API** — direct chat with OpenAI / Anthropic / Gemini / OpenRouter / local Ollama (key in the OS keyring).
- **Later** — assistant off.

The first time an agent opens, it asks once whether it may work in `~/.local/share/spm-studio-ai/scripts`
(the Tools folder). Say yes to let it create/edit analysis tools there. Full guide: `docs/AI_ASSISTANT_SETUP.md`.

## Push-to-talk voice input

Hold the mic button or **F11**. The small (~40 MB) offline speech model is fetched once after you confirm;
afterwards transcription is fully offline. No audio is ever sent anywhere.

## Uninstall / remove

```bash
cd SPM-Studio-0.0.1
bash uninstall_new_spm_studio.sh --dry-run
bash uninstall_new_spm_studio.sh --apply                      # type: REMOVE NEW SPM
bash uninstall_new_spm_studio.sh --apply --remove-ai-runtime  # also SPM's private Node.js/Pi program files
```

Your data, AI sign-ins/keys, `~/.pi` and Ollama are always kept. Old Research Studio leftovers:
`bash uninstall_old_research_studio.sh --dry-run` (then `--apply`).

## Troubleshooting

- `SMOKE FAILED`: nothing switched; remove `~/.local/share/spm-studio-ai-app/releases/0.0.1` and retry.
- Qt "xcb" error: `sudo apt install libxcb-cursor0`.
- Sign-in window does not open: run the command shown in the setup page in any terminal.
- Crash log: `~/.cache/spm-studio-ai/crash.log`.
