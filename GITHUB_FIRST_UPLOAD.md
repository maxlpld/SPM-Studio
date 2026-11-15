# Putting SPM Studio on GitHub — step by step

This guide takes you from the extracted `SPM-Studio` folder to a working **private** GitHub repository with
automatic releases, then shows how to share it, publish new versions and, later, make it public.

Everywhere below, replace **`YOUR_GITHUB_USER`** with your GitHub user name (for example `jdoe`). Commands
are for a terminal: **Terminal** on Ubuntu and macOS, **PowerShell** on Windows. Run every command **inside
the `SPM-Studio` folder** (the one that contains `pyproject.toml` and this file).

> **Important:** do not upload a `.zip` file to GitHub. GitHub stores a zip as one opaque file: nobody
> can browse the code, the README is not shown, and no workflow runs. Upload the **extracted folder**.

---

## Part A — First-time setup

### A1. Create the empty private repository

1. Sign in at <https://github.com> (create a free account if needed).
2. Top right **+** › **New repository**.
3. *Repository name*: **`SPM-Studio`**. *Description* (optional): *Quick SPM image analysis (STM/AFM/KPFM)
   with an optional AI assistant*.
4. Choose **Private**.
5. Leave **all** “Initialize this repository with” options **unticked** (no README, no .gitignore, no
   licence — this project already has them).
6. **Create repository**. Keep the page open; you will only need its address,
   `https://github.com/maxlpld/SPM-Studio`.

### A2. Point the project at your repository (once)

This writes your repository name into the README, the one-line installers and the in-app update check.
It does not touch any scientific code.

```bash
python3 tools/release_tools.py set-repo maxlpld/SPM-Studio      # Windows: py tools\release_tools.py set-repo maxlpld/SPM-Studio
python3 tools/release_tools.py show-repo                                # prints maxlpld/SPM-Studio
```

(The repository name can be different, e.g. `set-repo jdoe/spm-studio`; use the same name on GitHub.)

### A3. Upload the project — choose ONE option

#### Option 1 (recommended): Git + GitHub CLI, five commands

Reliable for hundreds of files, keeps the hidden `.github` folder and the correct line endings.

**Install once**

| System | Install Git and the GitHub CLI |
|---|---|
| Ubuntu | `sudo apt install git gh` |
| macOS | `xcode-select --install` (Git), then `brew install gh` (needs [Homebrew](https://brew.sh)) |
| Windows | `winget install Git.Git` and `winget install GitHub.cli` — then close and reopen PowerShell |

**Sign in once** (opens your browser; the `workflow` permission is needed to upload the
`.github/workflows` files):

```bash
gh auth login --hostname github.com --git-protocol https --web --scopes workflow
```

Answer **Yes** if it asks to authenticate Git with your GitHub credentials.

**Tell Git who you are** (once per computer; shown in the history — you may use GitHub's private
`ID+username@users.noreply.github.com` address from github.com › Settings › Emails):

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.org"
```

**Upload**:

```bash
git init -b main
git add .
git commit -m "SPM Studio 0.0.1"
git remote add origin https://github.com/maxlpld/SPM-Studio.git
git push -u origin main
```

Shortcut: instead of A1 and the last two lines, `gh repo create SPM-Studio --private --source . --push`
creates the repository and uploads in one step.

#### Option 2: GitHub Desktop (no terminal)

1. Install [GitHub Desktop](https://desktop.github.com/) and sign in with your GitHub account.
2. *File › Add local repository…* › choose the `SPM-Studio` folder. It says it is not a Git repository:
   click **create a repository**, keep the name, *Git ignore: None*, *License: None* (the project has its
   own files), **Create repository**.
3. Click **Publish repository**, keep **Keep this code private** ticked, **Publish**.
   (If you already created the empty repository in A1, delete it first or choose a different name here,
   because Desktop creates the repository itself.)

Do step A2 **before** step 2, or commit the changed files afterwards (*Changes* tab › *Commit to main* ›
*Push origin*).

#### Option 3: the GitHub website (possible, but fiddly)

GitHub's upload page accepts at most **100 files per upload** (25 MiB each), and this project has about
440 files, so you would upload in several batches. It also does **not** apply `.gitattributes`, and file
pickers often hide the `.github` folder and the `.gitignore` / `.gitattributes` files. If you still prefer it:

1. In the empty repository click **uploading an existing file**.
2. Drag **folders** (not their contents) from the `SPM-Studio` folder into the page, a few at a time —
   for example first `src`, then `scripts`, then `tests`, `docs`, `customization`, `assets`, `tools`, then the
   single files of the top folder. Wait until each batch is listed, then **Commit changes**.
3. Show hidden files first so you can drag `.github`, `.gitignore` and `.gitattributes`
   (macOS Finder: <kbd>Cmd</kbd>+<kbd>Shift</kbd>+<kbd>.</kbd>; Windows Explorer: *View › Show › Hidden items*;
   Ubuntu Files: <kbd>Ctrl</kbd>+<kbd>H</kbd>).
4. Compare with the list in A4. Missing `.github/workflows` means no automatic tests or releases.

### A4. Check that the files are individually visible

Open `https://github.com/maxlpld/SPM-Studio`. You should see:

- the README below the file list, with the **SPM Studio logo** at the top;
- folders `.github`, `assets`, `customization`, `docs`, `scripts`, `src`, `tests`, `tools`;
- files such as `pyproject.toml`, `CHANGELOG.md`, `get-spm-studio.sh`, `install_spm_studio_clean.sh`;
- `src/spm_studio/core/updates.py` opens as readable Python code.

### A5. GitHub Actions (automatic tests and releases)

1. Repository › **Settings › Actions › General**. Under *Actions permissions* choose
   **Allow all actions and reusable workflows** (the default) and **Save** if you changed it.
   *Workflow permissions* can stay at **Read repository contents** — the release workflow asks for the one
   extra permission it needs (creating releases) by itself.
2. Open the **Actions** tab. Your push started **Tests**; a green tick means it passed.
   A red cross: click it, then the failed step, to read the message.
3. Private repositories have a monthly allowance of free Actions minutes (2,000 on the Free plan), and
   Windows/macOS minutes count 2×/10×. That is why every push tests **Linux only**; Windows and macOS are
   tested for pull requests, every release, and whenever you click **Actions › Tests › Run workflow**.
   You can see your usage at github.com › Settings › Billing. Public repositories do not use the allowance.

### A6. Create the first release, v0.0.1

```bash
git tag v0.0.1
git push origin v0.0.1
```

(GitHub Desktop: *History* tab › right-click the latest commit › **Create Tag…** › `v0.0.1` › then
**Push origin**.)

The **Publish release** workflow then checks the version, runs the tests on Linux, Windows and macOS
(about 15–25 minutes) and creates the release. Check it at
`https://github.com/maxlpld/SPM-Studio/releases`: release **SPM Studio 0.0.1** with the notes from
`CHANGELOG.md`, `SPM-Studio-0.0.1.zip` and `SHA256SUMS.txt`.

If it failed, read the red step in the Actions tab and see *Recovering from a failed release* in
[`docs/RELEASING.md`](docs/RELEASING.md). The most common cause is that A2 was skipped
(*“still points at the placeholder”*).

### A7. Install it yourself

Follow the *Private repository* section of the README on your own computer (you are already signed in
with `gh` if you used Option 1):

```bash
gh api -H 'Accept: application/vnd.github.raw' repos/maxlpld/SPM-Studio/contents/get-spm-studio.sh | bash
```

---

## Part B — Share with colleagues

### B1. Invite collaborators

Repository › **Settings › Collaborators** › **Add people** › enter their GitHub user name or e-mail.
They receive an e-mail and must **accept the invitation** (or open <https://github.com/notifications>).

> In a repository owned by a personal account, every collaborator gets **write** access (they could push
> changes). If you want colleagues to have **read-only** access, create a free GitHub *organization*,
> transfer the repository to it (*Settings › General › Transfer*), and invite them with the **Read** role.
> Then run `python3 tools/release_tools.py set-repo NEW_OWNER/SPM-Studio`, commit, push and release again.

### B2. What colleagues need for a private repository

While the repository is private, GitHub only serves its files to signed-in people who have access.
That is why the plain `curl … | bash` / `irm … | iex` commands do not work yet, and why SPM Studio
needs a GitHub sign-in to check for updates. Nobody should ever put a token into a URL, a shared document
or a file in the repository.

Each colleague does this **once**:

1. Accept the invitation (B1).
2. Install the GitHub CLI (`sudo apt install gh` · `brew install gh` · `winget install GitHub.cli`).
3. Run `gh auth login` and sign in through the browser.

### B3. How colleagues install

They follow the README section **Private repository (invited collaborators)** — essentially:

```bash
# Linux / macOS
gh api -H 'Accept: application/vnd.github.raw' repos/maxlpld/SPM-Studio/contents/get-spm-studio.sh | bash
```

```powershell
# Windows
gh api -H "Accept: application/vnd.github.raw" repos/maxlpld/SPM-Studio/contents/get-spm-studio.ps1 | Out-String | iex
```

Updates then arrive through *Settings › Check for updates…* in the app, using the same sign-in.
Colleagues who prefer no command line can download `SPM-Studio-<version>.zip` from the **Releases** page
while signed in, and run the installer in it (see the install guides).

### B4. What a QR code can and cannot do (private repository)

- **Can:** open the repository page or its README on a phone or laptop — e.g. a QR code for
  `https://github.com/maxlpld/SPM-Studio#installation`. GitHub then asks the person to sign in, and
  shows the page only if they accepted the invitation.
- **Cannot:** grant access, sign anyone in, or install SPM Studio. Scanning a code does not run anything.
- **Never** put a token or password into a QR code: anyone who photographs it gets your access.

---

## Part C — Publishing future versions

A normal `git push` only stores your changes and runs the tests; **it does not publish anything to users**.
Users are offered a new version only when you push a **version tag**.

1. **Change the code** in this folder with your usual editor.
2. **Test locally** (once: create the developer environment as in [`CONTRIBUTING.md`](CONTRIBUTING.md)):

   ```bash
   . .venv/bin/activate                          # Windows: .venv\Scripts\activate
   QT_QPA_PLATFORM=offscreen python -m spm_studio --smoke-test
   python -m pytest -q
   python -m spm_studio                          # try it by hand
   ```

3. **Commit and push** (as often as you like):

   ```bash
   git add -A
   git commit -m "Describe the change"
   git push
   ```

4. **When you want to release**, set the new version (updates `pyproject.toml`, the README badge and adds
   a `CHANGELOG.md` section):

   ```bash
   python tools/release_tools.py bump 0.0.2
   ```

   Open `CHANGELOG.md` and replace the line *“Describe what is new for users.”* with the real notes —
   this is exactly what users see in *Check for updates*. Then:

   ```bash
   git add -A
   git commit -m "SPM Studio 0.0.2"
   git push
   ```

5. **Publish** with the tag:

   ```bash
   git tag v0.0.2
   git push origin v0.0.2
   ```

6. **Verify the release:** Actions tab › *Publish release* is green; the Releases page shows 0.0.2 with its
   notes, `SPM-Studio-0.0.2.zip` and `SHA256SUMS.txt`.
7. **Verify the updater:** on a computer with the previous version, *Settings › Check for updates…* (or
   `spm-studio --check-update`) shows *0.0.2 available* with your notes; *Install update* installs it.

Version numbers: `0.0.2` for fixes, `0.1.0` for new features, `1.0.0` when you consider it stable.
Tags must be `v` + exactly the version in `pyproject.toml`; the workflow refuses anything else.

---

## Part D — Making the repository public

### D1. Check for sensitive information first

Making a repository public publishes **every file in every commit of its history**, not only the current
files. Before switching:

1. Look through the files you added since this first upload for scans, results, unpublished data,
   personal paths, e-mail addresses, passwords, API keys or tokens.
2. Search the whole history from the repository folder:

   ```bash
   git log --all -p | grep -nEi 'api[_-]?key|secret|passw|token|BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9]{20}|ghp_|github_pat_' | head -50
   git log --all --name-only --format='' | sort -u | grep -Ei '\.(sxm|gwy|npy|npz|env|pem|key)$|auth\.json'
   ```

   Both should print nothing (or only lines you recognise as harmless, such as documentation that
   *mentions* the word token). Optional dedicated scanners: [gitleaks](https://github.com/gitleaks/gitleaks),
   [trufflehog](https://github.com/trufflesecurity/trufflehog).
3. If something sensitive was ever committed, deleting the file is **not** enough — it remains in the
   history. Revoke the secret first (change the password / delete the key), then follow GitHub's guide
   *Removing sensitive data from a repository*, or create a fresh repository from the cleaned folder.
4. Check *Settings › Collaborators* and the Releases: release archives become public too.

### D2. Change the visibility

Repository › **Settings › General** › at the bottom **Danger Zone › Change repository visibility** ›
**Change to public**, and confirm. Then open *Settings › Code security* (called *Security* or
*Advanced Security* in some accounts) and make sure the free **secret scanning** and **push protection**
are enabled; they warn you if a credential is ever pushed later.

### D3. Verify the public installation commands

On a computer **without** a GitHub sign-in (or with `SPM_STUDIO_USE_GH_CLI=0`), run the commands from the
README's *Installation* section:

```bash
curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.ps1 | iex
```

You may then remove the “repository is private” note at the top of the README's Installation section.

### D4. Verify unauthenticated updates

```bash
SPM_STUDIO_USE_GH_CLI=0 SPM_STUDIO_GITHUB_TOKEN= GH_TOKEN= GITHUB_TOKEN= spm-studio --check-update
```

It must print `Installed: … Latest: …` without an error. Installed copies switch to anonymous access
automatically; nothing has to be changed on users' computers.

### D5. Share the public link with a QR code

Point the QR code at the README's installation section, not at a command:

```text
https://github.com/maxlpld/SPM-Studio#installation
```

Create it with any QR generator, or locally:

```bash
sudo apt install qrencode            # macOS: brew install qrencode
qrencode -o spm-studio-qr.png -s 10 "https://github.com/maxlpld/SPM-Studio#installation"
```

People scan it, open the page and copy the command for their system. (A QR code that contains the command
itself would only show text; it cannot run anything — which is also why it is safe to share.)
