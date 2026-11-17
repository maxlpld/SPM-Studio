# SPM Studio 0.0.1 — install on Windows 10 / 11

Download: **`SPM-Studio-0.0.1.zip`** from the repository's *Releases* page (one archive for every operating system; for a private repository you must be signed in to GitHub)
(same application and AI assistant as the Ubuntu and macOS versions).

The zip contains only the application source: no virtual environment, no API keys, no login tokens, no AI
chat history, no personal scans/results, no Pi configuration. It was checked for secrets before release.

## Easiest: one command (installs or updates)

Open **PowerShell** (Start menu › type *PowerShell* › Enter — not as administrator) and paste:

```powershell
irm https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.ps1 | iex
```

It downloads the newest release from GitHub and runs the installer below. Run it again at any time to
update. Later updates: **Settings › Check for updates…** in the app, or
`& "$env:LOCALAPPDATA\SPMStudio\bin\spm-studio.cmd" --update`.

**Private repository** (while the project is private, the command above cannot download anything): install
the GitHub CLI once (`winget install GitHub.cli`), open a new PowerShell, run `gh auth login`, then use

```powershell
gh api -H "Accept: application/vnd.github.raw" repos/maxlpld/SPM-Studio/contents/get-spm-studio.ps1 | Out-String | iex
```

The script and later in-app updates then use that sign-in automatically. See `README.md › Private repository`.

The manual install from the downloaded archive works exactly as before:

## Requirements

- Windows 10 (21H2+) or 11, 64-bit, a normal user account (**no administrator rights needed** — do not
  use *Run as administrator*).
- **Python 3.12 or newer** from python.org or winget. If none is found, the installer offers to install Python 3.12
  for your user with `winget` (built into Windows 11 / recent Windows 10).
- ~1.5 GB free disk space, internet for the one-time dependency download.

## Install

**With the mouse:** right-click the zip › *Extract All…* (e.g. into `Downloads`), open the
`SPM-Studio-0.0.1` folder, double-click **`install_spm_studio_windows.bat`**. If Windows shows *“Windows protected
your PC”* or an *Open File – Security Warning*, choose *More info › Run anyway* / *Run* (the file is a
plain script you can read in Notepad).

**Or in PowerShell (copy/paste):**

```powershell
cd $HOME\Downloads
Expand-Archive .\SPM-Studio-0.0.1.zip -DestinationPath .
cd .\SPM-Studio-0.0.1
.\install_spm_studio_windows.bat
```

The installer copies the app to `%LOCALAPPDATA%\SPMStudio\releases\0.0.1`, creates its own Python
environment there, installs the dependencies, runs the offscreen self-test (`SMOKE PASSED`) and only then
creates **Start menu › SPM Studio** and a desktop shortcut. If it prints `SMOKE FAILED`, nothing was
activated — read the printed error before retrying.

Options (append to the `.bat` line): `-Mode DryRun` (show what would be done), `-Mode Stage` / `-Mode Activate`
(two steps), `-NoDesktopShortcut`, `-Mode PruneOld` (remove older releases after an upgrade).

## Launch

Start menu › **SPM Studio** (or the desktop icon). From a terminal:

```powershell
& "$env:LOCALAPPDATA\SPMStudio\bin\spm-studio.cmd"
```

## Connecting the AI assistant

The scientific application needs **no** Pi, Ollama, API key or Node.js. To use the assistant, click
**Assistant** in the header; the first time, a dialog offers:

- **Set up Pi** (pre-selected when no Pi is installed) — *Start guided setup…* does everything:
  private Node.js if needed (from nodejs.org, checksum-verified), Pi + smart routing + subagents, and
  *Install Git for Windows* if Git Bash is missing (Pi uses it to run commands). Then sign in with
  ChatGPT Plus/Pro or GitHub Copilot in your browser (a small window opens with the exact command to type),
  or paste an API key; choose models; then it asks **“Would you like a small local AI model to pre-classify
  your requests…?”** — if yes it checks your RAM/GPU, proposes three models, installs Ollama (winget or the
  official installer), downloads the model and tests it. Ends with a real test message.
- **My Pi** — reuse an existing Pi (`pi.cmd`) with its own configuration, unchanged.
- **Claude / Codex** — Claude Code (official installer) or OpenAI Codex CLI with their own sign-in.
- **Cloud API** — direct chat with OpenAI / Anthropic / Gemini / OpenRouter / local Ollama (key stored in
  Windows Credential Manager).
- **Later** — assistant off.

The first time an agent opens it asks once whether it may work in
`%USERPROFILE%\.local\share\spm-studio-ai\scripts` (the Tools folder). Say yes to let it create/edit analysis
tools there. Full guide: `docs\AI_ASSISTANT_SETUP.md`.

## LaTeX editor and presentation editor (optional, 0.0.8)

Switch them on in *Settings › Documents*. The LaTeX editor compiles with **MiKTeX**
(https://miktex.org/download — allow it to install missing packages on the fly) or TeX Live. Overleaf sync
needs **Git for Windows** (https://git-scm.com/download/win). LaTeX boxes of the presentation editor use
the same TeX installation. Details: [`docs/DOCUMENTS.md`](docs/DOCUMENTS.md).

## Push-to-talk voice input

Hold the mic button or **F11**. The small (~40 MB) offline speech model is fetched once after you confirm;
afterwards transcription is fully offline. If Windows blocks the microphone: *Settings › Privacy & security ›
Microphone › Let desktop apps access your microphone*.

## Where your data lives

| What | Folder |
|---|---|
| Application (replaceable) | `%LOCALAPPDATA%\SPMStudio` |
| Tools, results, AI conversations, private Node.js/Pi | `%USERPROFILE%\.local\share\spm-studio-ai` |
| Settings, themes, profiles | `%USERPROFILE%\.config\spm-studio-ai` |
| Crash log | `%USERPROFILE%\.cache\spm-studio-ai\crash.log` |

## Uninstall / remove

```powershell
cd $HOME\Downloads\SPM-Studio-0.0.1
.\uninstall_spm_studio_windows.bat                         # dry run: lists what would be removed
.\uninstall_spm_studio_windows.bat -Apply                  # type: REMOVE NEW SPM
.\uninstall_spm_studio_windows.bat -Apply -RemoveAiRuntime # also SPM's private Node.js/Pi program files
```

Your data, AI sign-ins/keys, Ollama and its models are always kept.

## Troubleshooting

- **“Python 3.12 or newer is required”**: install Python from https://www.python.org/downloads/windows/
  (tick *Add python.exe to PATH*) or `winget install -e --id Python.Python.3.12 --scope user`, then rerun.
- **Typing `python` opens the Microsoft Store**: that is the Store stub; the installer ignores it — install
  a real Python as above.
- **`SMOKE FAILED`**: nothing switched; delete `%LOCALAPPDATA%\SPMStudio\releases\0.0.1` and retry.
- **Assistant says Pi cannot run commands**: install Git for Windows (button in the setup) and reconnect.
