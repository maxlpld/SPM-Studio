# AI assistant setup (Linux, Windows, macOS)

The assistant is optional: every scientific tool works without it. Open it with the **Assistant** button
in the header (or Ctrl+Alt+A). Since 0.1.0 every AI setting is in the assistant's own settings window (gear
button in the assistant panel; SPM Studio's Settings › General has one line that opens it): *AI Providers &
Accounts*, *Models & Routing*, *Permissions & Security*, *E-mail accounts*, *Calendar*, *Literature (Consensus &
Zotero)* and **SPM Studio assistant & Pi setup**, which opens the dialogs described below (the connection choice
and the guided Pi setup). Nothing is downloaded, installed or signed in without a confirmation dialog.
How the engine is built into SPM Studio: [`AGENT_HUB.md`](AGENT_HUB.md).

## The five starting paths

| Tab in the dialog | Use it when | Coding tools (create analysis tools, Develop tab) |
|---|---|---|
| **My Pi** | You already use the Pi coding agent | Yes — Pi runs exactly with *your* configuration (`~/.pi`, router, Judge, logins). SPM Studio changes nothing. |
| **Set up Pi** | You are new to coding agents | Yes — guided, automatic setup (below). |
| **Claude / Codex** | You pay for Claude Pro/Max/Team or ChatGPT | Yes — Claude Code (`claude -p`) or OpenAI Codex CLI (`codex exec`) with their own sign-in. |
| **Cloud API** | You only want to chat with one model | No — chat only. |
| **Later** | | Assistant off. |

On a first start the dialog pre-selects **My Pi** when a Pi is found on the computer, otherwise **Set up Pi**.

## Guided Pi setup ("Set up Pi" → Start guided setup…)

1. **Install** — checks Node.js. If there is no Node.js 22.19+ (Pi's requirement), the official Node.js
   LTS build is downloaded from nodejs.org, its SHA-256 checksum verified, and unpacked into SPM Studio's
   own folder (your system Node.js, if any, is not changed). Then Pi (`@earendil-works/pi-coding-agent`) is
   installed with npm into SPM Studio's folder, plus — ticked by default — the router `pi-shift-router` and
   `pi-subagents`. Windows: Pi needs Git Bash to run commands; the page offers *Install Git for Windows*
   (winget) when it is missing.
2. **Sign in** — *Sign in with ChatGPT Plus/Pro (Codex)* or *GitHub Copilot* opens a small terminal window
   running Pi; type the `/login …` command it shows, finish in your browser, type `/quit`. The page detects
   the sign-in by itself. Or paste an **API key** (OpenAI, Anthropic, Google Gemini, OpenRouter, DeepSeek,
   Mistral, xAI, Groq); *Get a key…* opens the provider's key page. Claude Pro/Max subscribers: use the
   **Claude / Codex** tab (official Claude Code app) or an Anthropic API key.
3. **Models** — Pi lists the models your accounts can use. With routing on, choose a **Fast** model (everyday
   questions, small scripts) and a **Smart** model (complex coding), each with an optional fallback, and a
   cost mode (Eco / Balanced / Performance).
4. **Judge** — *“Would you like a small local AI model to pre-classify your requests?”*
   - **Local Judge**: SPM Studio measures RAM and GPU memory (NVIDIA via `nvidia-smi`, AMD ROCm on Linux,
     Apple-Silicon unified memory estimated, Windows adapters), verifies the candidate models against the
     official Ollama registry (exact download sizes), and proposes **three profiles** — fastest, balanced
     (recommended), higher quality — saying for each whether it runs on GPU or CPU. If Ollama is missing it
     offers to install it (Windows: winget or the official installer; macOS: Ollama.dmg copied to
     Applications; Linux: the official script in a terminal, which asks for your password). Then
     *Download & test* pulls the model and runs a real Fast prompt and a real Smart prompt **through the same
     endpoint the router uses**, showing the decision, confidence and time.
   - **Cloud Judge**: your Fast model decides (no download, a few tokens per message).
   - **No automatic Judge**: one model, no routing.
5. **Test** — writes the configuration and sends a real message through Pi; the answer is shown.

### Where things are stored (same layout on every system)

`<data>` is `~/.local/share/spm-studio-ai` (Windows: `%USERPROFILE%\.local\share\spm-studio-ai`).

| Path | Content |
|---|---|
| `<data>/ai/node/current` | private Node.js (only if it had to be downloaded) |
| `<data>/ai/runtime` | private Pi (and Codex CLI if installed from the dialog) |
| `<data>/ai/pi-agent` | Pi's settings for SPM Studio (`PI_CODING_AGENT_DIR`): `auth.json` (sign-ins/keys, private to your user), `settings.json`, `models.json`, `pi-shift-router.json` |
| `~/.config/spm-studio-ai/ai/settings.json` | which backend SPM Studio uses — never a key |

`~/.pi` is never read or written by the guided setup. Keys are never written into the application folder,
logs, exports or the zip.

### The local Judge proxy

Small reasoning models served by Ollama "think" before answering, which makes a one-word routing decision
slow. While SPM Studio runs, it serves a tiny local endpoint (`127.0.0.1:11436`, another free port if busy)
that forwards the router's Judge requests to Ollama's native API with thinking disabled and JSON output.
It replaces the separate `pi-ollama-judge` user service used in a hand-made setup; nothing is installed as
a system service, and an existing Ollama configuration is not changed.

## Claude Code / OpenAI Codex

- **Install…** — Claude Code: Anthropic's official installer in a terminal window
  (`curl -fsSL https://claude.ai/install.sh | bash`, Windows `irm https://claude.ai/install.ps1 | iex`).
  Codex: `@openai/codex` from npm into SPM Studio's folder (private Node.js if needed).
- **Sign in…** — opens the agent in a terminal for its own sign-in (Claude Code `/login`; `codex login`).
- Each message runs one short agent process (`claude -p --output-format stream-json …` /
  `codex exec --json …`); the conversation continues through the agent's own session id. Chat-only mode uses
  Claude Code's `plan` permission mode / Codex `read-only` sandbox; with the tools button on, Claude Code may
  edit files (`acceptEdits`) and Codex runs with `workspace-write`, inside the SPM Studio scripts folder.

## Literature sources: Consensus and Zotero (Settings › Literature)

Both are optional, off until connected, and read-only. They are connected in the Settings page by SPM Studio
itself and then work with **every** backend — Pi, Claude Code, Codex and direct API chat — with or without
agent tools.

### How the assistant uses them

The assistant is told (in its instructions) that it can ask for a lookup by ending its message with a
request line such as

```
<spm-literature>{"source": "zotero", "action": "search", "query": "kelvin probe graphene"}</spm-literature>
```

SPM Studio runs the request in the app and sends the result back as the next message; the assistant then
answers. The chat shows “Looking up: …” / “Looked up: …” instead of the request and the raw data. Only the
read-only actions exist (`zotero`: `search`, `item`, `collections`, `fulltext`; `consensus`: `search`), at
most four requests per message and four rounds per question; results are size-capped and marked as data.
Agents that have a shell can also run `python -m spm_studio.ai.literature …`, and MCP clients can use the
stdio server `python -m spm_studio.ai.literature --mcp`; neither is required.

### Zotero

**Connect Zotero** sets the automatic mode. *Advanced* lists all of them:

| Choice | What is needed | Notes |
|---|---|---|
| **Automatic** (recommended) | Nothing | Asks the Zotero app when it answers, otherwise reads the database file. |
| **Zotero database file** | Nothing | Reads `zotero.sqlite` in the Zotero data folder, opened read-only and immutable (never locked or changed). Any Zotero version, running or not. Searches titles, creators, years, tags, abstracts and notes; full text comes from Zotero's own PDF index. The folder is found in the usual places and in Zotero's own preference; set it by hand only if it is elsewhere. |
| **Zotero app** | Zotero 7 or later running, with *Settings › Advanced › Allow other applications on this computer to communicate with Zotero* | `http://127.0.0.1:23119/api`. Also searches inside indexed PDFs. |
| **zotero.org account** | Numeric library ID and a private key with read-only library access | Requests go to `api.zotero.org`. |

### Consensus

**Sign in to Consensus** runs the standard OAuth sign-in documented by Consensus (authorisation code with
PKCE, dynamic client registration, scope `search`): the Consensus page opens in the browser, and the answer
comes back to a temporary address on this computer (`http://127.0.0.1:<port>/callback`). SPM Studio then calls
Consensus' MCP server `https://mcp.consensus.app/mcp` (tool `search`) with the resulting token. The password
is typed on consensus.app only. *Sign out* removes the sign-in from this computer; access can also be revoked
in the Consensus account. Organisations that hand out Consensus API keys can paste one under *Advanced*.

If your university provides Consensus, sign in with your university e-mail: the licence is attached to the
account. A Zotero library linked inside your Consensus account is used by Consensus itself.

### Where the secrets are

The zotero.org key and the Consensus sign-in are stored in the operating system's keyring. On a computer
without a keyring they are stored in `literature_secrets.json` in SPM Studio's settings folder, readable by
your account only (mode 600). They are never written to the ordinary settings file, the logs or a release.

## Guides the assistant reads before it builds something

Every folder the assistant may write to contains a `README.md`: the scripts folder, and `profiles`,
`export_presets`, `themes`, `colormaps`, `plot_styles` and `shortcuts` in the customization folder. Each one
states how the files of that folder must be built (required keys, allowed values, a complete example, the
checks to run). The assistant's instructions list these guides and tell it to read the one of a folder before
creating or changing anything there, and to give every script a `README.md` (shown by the *Read me* button
of the Analysis panel). The guides are installed and updated automatically; a guide you edited is kept.

## Safety rules (all backends)

- Analysis of saved data only — the assistant is instructed never to send commands to microscopes,
  Nanonis, heaters, vacuum or other hardware, and SPM Studio exposes no instrument-control tool to it.
- File/shell tools are off until you confirm once; the tools button switches them off at any time.
  Agents are **not** an OS sandbox: they act with your user account's rights in the working folder.
- New tools from the Develop tab are staged in a private folder, validated (manifest + syntax), and only
  then installed into Tools — without restarting SPM Studio.

## Resetting / removing the AI parts

- Re-run **Set up Pi › Change setup…** at any time.
- Remove the private Node.js and Pi program files (sign-ins kept): uninstaller with
  `--remove-ai-runtime` (Windows `-RemoveAiRuntime`).
- Forget SPM Studio's Pi sign-ins: delete `<data>/ai/pi-agent/auth.json`.
