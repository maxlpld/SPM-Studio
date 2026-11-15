# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead:

- use GitHub's private reporting: repository › **Security** › **Report a vulnerability**
  (if the maintainer has enabled *Private vulnerability reporting* under *Settings › Code security*), or
- contact the maintainer privately (their GitHub profile is linked on the repository page,
  `https://github.com/maxlpld/SPM-Studio`).

Include the SPM Studio version, operating system, the steps to reproduce and the impact you expect. You
will get an acknowledgement as soon as possible; please allow time for a fix before disclosing details.

Only the newest release receives security fixes.

## What SPM Studio does and does not do

- It is offline analysis software. It does not control instruments and opens no network ports, except
  the assistant's optional local Judge proxy, which listens on `localhost` only.
- Network use: the optional update check (`api.github.com`), dependency installation by the installers
  (PyPI), and — only if you set them up — AI providers, the Pi agent, Node.js/npm and Ollama downloads,
  and the one-time, confirmed download of the offline speech model.
- No credential is shipped with SPM Studio or stored in this repository.

## GitHub credentials for a private repository

Installing from and updating from a **private** repository needs a GitHub sign-in on each computer.

- **Recommended:** the GitHub CLI (`gh auth login`). It stores its token in the operating system's
  credential store (it falls back to a plain-text file only when no store is available; `gh auth status`
  shows where). SPM Studio asks it for the token (`gh auth token`) when it needs it and never saves it.
- **Alternative:** a personal access token in the environment variable `SPM_STUDIO_GITHUB_TOKEN`.
  - The repository **owner** (or a member of an organization that owns it) should create a
    **fine-grained** token limited to this one repository with *Contents: Read-only*.
  - **Collaborators on a personal account's repository** cannot use fine-grained tokens for it (a GitHub
    limitation); they would need a classic token with the `repo` scope, which can read **all** of their
    private repositories — another reason to prefer `gh auth login`.
  - Set an expiry date, keep it in your shell profile or a password manager, never in a file inside this
    repository, a URL, a chat, a screenshot or a QR code. Revoke it at github.com › Settings › Developer
    settings when you no longer need it.
- The credential is sent only to `api.github.com`. GitHub answers archive downloads with a redirect to a
  signed storage URL; SPM Studio and the get-scripts drop the credential for that redirect. The shell script
  passes it to `curl` through a temporary file readable only by you, so it does not appear in process lists.
- `SPM_STUDIO_USE_GH_CLI=0` stops SPM Studio and the get-scripts from asking the GitHub CLI.

## One-line installation commands

`curl … | bash` and `irm … | iex` execute a script downloaded from the repository. They are convenient,
but you trust the repository and GitHub's HTTPS connection. To review first, download the script, read it,
then run it (`bash get-spm-studio.sh`, or `powershell -ExecutionPolicy Bypass -File get-spm-studio.ps1`).
The scripts never need administrator rights; on Ubuntu they ask before running `sudo apt` for missing system
libraries. Release archives come with `SHA256SUMS.txt` (a checksum detects a damaged download; it is not a
signature).

## AI assistant, coding agents and plugins — limitations

These features are optional and off until you set them up. Please read before enabling them:

- **Coding tools are not a sandbox.** When you authorise a development task, the agent (Pi, Claude Code or
  Codex) can read and write files and run commands with **your** user rights. SPM Studio limits the working
  folder and asks for task-specific authorisation, but neither the agent's tools nor Python plugins run in
  an operating-system sandbox.
- **Generated or imported tools are code.** A staged plugin is checked for a valid manifest and Python
  syntax, never for safety or scientific correctness. Install only tools you have read or trust; an
  installed tool runs inside SPM Studio with your rights.
- **Data sent to AI providers.** Cloud models receive what you type and what the agent reads. Do not
  send unpublished or confidential data to a provider unless you are allowed to. A local model through
  Ollama keeps prompts on your computer.
- **API keys** are taken from environment variables or stored in the operating system's keyring; without
  a keyring, keys you type are kept in memory for the current session only. Pi's own sign-ins live in Pi's
  configuration folder, outside this repository.
- **Third-party software** (Node.js, Pi, router/sub-agent packages, Claude Code, Codex CLI, Ollama and
  models) is downloaded from its publishers when you choose it; its security is the publishers'
  responsibility. The guided Pi setup verifies the Node.js download against its published SHA-256.

See also [`VERIFY_AND_TEST.md`](VERIFY_AND_TEST.md) and [`docs/AI_ASSISTANT_SETUP.md`](docs/AI_ASSISTANT_SETUP.md).
