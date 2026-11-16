#!/usr/bin/env bash
# SPM Studio - isolated, two-stage, per-user installer for macOS 12+ (Apple Silicon and Intel).
# Same design as the Ubuntu installer: build the new release in its own folder with its own
# Python environment, run the offscreen self-test, and only then create/replace the
# "SPM Studio" app in ~/Applications. Never deletes scans, results, scripts, settings or AI accounts.
# Written for the bash 3.2 that ships with macOS (no GNU timeout, no bash 4 features).
#
#   bash install_spm_studio_macos.sh            # stage + activate
#   bash install_spm_studio_macos.sh --dry-run | --stage | --activate | --prune-old
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -n1)"
[[ -n "$VERSION" ]] || { echo 'Cannot read the version from pyproject.toml' >&2; exit 2; }
BASE="$HOME/Library/Application Support/SPMStudio"
RELEASES="$BASE/releases"
RELEASE="$RELEASES/$VERSION"
APP="$RELEASE/app"
PY="$RELEASE/venv/bin/python"
BUNDLE="$HOME/Applications/SPM Studio.app"
LAUNCHER="$HOME/.local/bin/spm-studio"
MODE="${1:---install}"

if [[ "$(uname -s)" != Darwin ]]; then echo 'This installer is for macOS. On Linux use install_spm_studio_clean.sh' >&2; exit 2; fi
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then echo 'Run as your normal user, not with sudo.' >&2; exit 2; fi
case "$MODE" in --install|--stage|--activate|--dry-run|--prune-old) ;;
  *) echo 'Use --dry-run, --stage, --activate, --install or --prune-old' >&2; exit 2;; esac
[[ -f "$ROOT/pyproject.toml" && -f "$ROOT/src/spm_studio/ai/chat_ui.py" ]] || { echo 'Run from the extracted SPM_Studio folder.' >&2; exit 2; }

python_ok() {   # prints a Python >=3.12 interpreter with venv and ensurepip
  "$1" - <<'PY' 2>/dev/null
import sys, venv, ensurepip
if sys.version_info[:2] >= (3, 12):
    print(sys.executable)
PY
}

find_python() {
  local c found
  for c in "${SPM_PYTHON:-}" python3.12 python3.13 python3.14 python3.15 \
           /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
           /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 \
           /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14 \
           /opt/homebrew/bin/python3.15 /usr/local/bin/python3.15 \
           /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.15/bin/python3 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    [[ -n "$c" ]] || continue
    if command -v "$c" >/dev/null 2>&1; then
      found="$(python_ok "$(command -v "$c")" || true)"
      if [[ -n "$found" ]]; then echo "$found"; return 0; fi
    fi
  done
  return 1
}

brew_path() {
  command -v brew 2>/dev/null || { [[ -x /opt/homebrew/bin/brew ]] && echo /opt/homebrew/bin/brew; } || \
    { [[ -x /usr/local/bin/brew ]] && echo /usr/local/bin/brew; } || true
}

run_with_timeout() {   # run_with_timeout SECONDS cmd...  (macOS has no GNU timeout)
  local secs="$1"; shift
  "$@" & local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if (( waited >= secs )); then kill "$pid" 2>/dev/null || true; sleep 1; kill -9 "$pid" 2>/dev/null || true
      echo "Timed out after ${secs} s" >&2; return 124; fi
    sleep 1; waited=$((waited + 1))
  done
  wait "$pid"
}

smoke() {
  [[ -x "$PY" ]] || { echo 'Staged interpreter missing' >&2; exit 2; }
  "$PY" -c "import spm_studio, spm_studio.ai.pi_setup, spm_studio.ai.judge_proxy; from pathlib import Path; print('Standalone SPM Studio source:', Path(spm_studio.__file__).resolve())"
  local tmp out rc
  tmp="$(mktemp -d)"
  out="$tmp/smoke.txt"
  set +e
  ( export QT_QPA_PLATFORM=offscreen XDG_DATA_HOME="$tmp/data" XDG_CONFIG_HOME="$tmp/config" XDG_CACHE_HOME="$tmp/cache"
    run_with_timeout 180 "$PY" -m spm_studio --smoke-test >"$out" 2>&1 )
  rc=$?
  set -e
  cat "$out"
  if [[ $rc -ne 0 ]] || ! grep -q 'SMOKE PASSED' "$out"; then
    rm -rf -- "$tmp"
    echo 'SMOKE FAILED - nothing was activated. Your current SPM Studio (if any) is unchanged.' >&2
    exit 2
  fi
  rm -rf -- "$tmp"
}

stage() {
  local base_py brew_bin answer free
  base_py="$(find_python || true)"
  if [[ -z "$base_py" ]]; then
    brew_bin="$(brew_path)"
    if [[ -n "$brew_bin" ]]; then
      read -r -p 'Python 3.12+ not found. Install python@3.12 with Homebrew now? [Y/n] ' answer
      if [[ -z "$answer" || "$answer" == [Yy]* ]]; then "$brew_bin" install python@3.12; base_py="$(find_python || true)"; fi
    fi
  fi
  if [[ -z "$base_py" ]]; then
    echo 'Python 3.12 or newer with venv is required. Python 3.12 is recommended for maximum third-party package compatibility.' >&2
    echo 'Install it from https://www.python.org/downloads/macos/ (or: brew install python@3.12), then run this again.' >&2
    open 'https://www.python.org/downloads/macos/' 2>/dev/null || true
    exit 2
  fi
  echo "Python: $("$base_py" -c 'import sys;print(sys.version.split()[0])') ($base_py)"
  free="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
  if (( free < 1500000 )); then echo 'At least 1.5 GB of free disk space is needed.' >&2; exit 2; fi
  if [[ -f "$RELEASE/READY" && -x "$PY" ]]; then echo "Existing staged release: $RELEASE"; smoke; return; fi
  if [[ -e "$RELEASE" ]]; then echo "Partial release at $RELEASE. Delete that folder and run again (nothing else is affected)." >&2; exit 2; fi
  mkdir -p "$RELEASE"
  echo 'Copying application files...'
  cp -R "$ROOT" "$APP"
  find "$APP" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
  echo 'Creating the private Python environment...'
  "$base_py" -m venv "$RELEASE/venv"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -e "$APP[all]"
  smoke
  printf '%s\n' "$VERSION" > "$RELEASE/READY"
  echo "Release staged and tested: $RELEASE"
}

write_bundle() {
  local tmpb="$HOME/Applications/.SPM Studio.app.new"
  rm -rf -- "$tmpb"
  mkdir -p "$tmpb/Contents/MacOS" "$tmpb/Contents/Resources"
  cp "$APP/assets/spm-studio.icns" "$tmpb/Contents/Resources/spm-studio.icns"
  cat > "$tmpb/Contents/MacOS/spm-studio" <<EOF
#!/bin/bash
# Managed by the SPM Studio installer (release $VERSION)
exec "$PY" -m spm_studio "\$@"
EOF
  chmod 755 "$tmpb/Contents/MacOS/spm-studio"
  cat > "$tmpb/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>SPM Studio</string>
  <key>CFBundleDisplayName</key><string>SPM Studio</string>
  <key>CFBundleIdentifier</key><string>org.spmstudio.SPMStudio</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>spm-studio</string>
  <key>CFBundleIconFile</key><string>spm-studio</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Push-to-talk dictation for the AI assistant. Audio is transcribed on this Mac and never sent anywhere.</string>
  <key>SPMStudioManagedRelease</key><string>$RELEASE</string>
</dict>
</plist>
EOF
  rm -rf -- "$BUNDLE"
  mv "$tmpb" "$BUNDLE"
  touch "$BUNDLE"
}

activate() {
  [[ -f "$RELEASE/READY" ]] || { echo 'Stage and test first with --stage.' >&2; exit 2; }
  smoke
  mkdir -p "$HOME/Applications" "$(dirname "$LAUNCHER")"
  if [[ -e "$BUNDLE" ]] && ! grep -q 'SPMStudioManagedRelease' "$BUNDLE/Contents/Info.plist" 2>/dev/null; then
    echo "$BUNDLE exists and was not created by this installer; refusing to replace it." >&2; exit 2
  fi
  ln -sfn "releases/$VERSION" "$BASE/current"
  write_bundle
  cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Managed by the SPM Studio installer (spm-studio-macos)
exec "$PY" -m spm_studio "\$@"
EOF
  chmod 755 "$LAUNCHER"
  echo
  echo "SPM Studio $VERSION installed successfully."
  echo "Launch: Finder > Applications (your home folder) > SPM Studio, Spotlight 'SPM Studio', or: open \"$BUNDLE\""
  echo "From a terminal: $LAUNCHER"
  echo "Installed release: $RELEASE"
  echo 'AI: click "Assistant" in the header. "Set up Pi" installs and configures everything for you.'
  echo 'Older releases are kept until you run: bash install_spm_studio_macos.sh --prune-old'
}

dry_run() {
  printf 'Version: %s\nSource: %s\nNew isolated release: %s\nApp: %s\nCommand launcher: %s\n' \
    "$VERSION" "$ROOT" "$RELEASE" "$BUNDLE" "$LAUNCHER"
  local py; py="$(find_python || true)"
  echo "Python found: ${py:-none (python.org or Homebrew python@3.12 needed)}"
  local old
  for old in "$RELEASES"/*/; do
    [[ -d "$old" && "${old%/}" != "$RELEASE" && -f "$old/READY" ]] && echo "Previous release kept (remove later with --prune-old): ${old%/}"
  done
  echo 'Nothing is installed or removed in dry-run mode.'
}

prune_old() {
  local current old t ack
  current="$(cd "$BASE/current" 2>/dev/null && pwd -P || true)"
  [[ -n "$current" && -f "$current/READY" ]] || { echo 'No active release found; refusing to prune.' >&2; exit 2; }
  local targets=()
  for old in "$RELEASES"/*/; do
    old="${old%/}"
    if [[ -d "$old" && ! -L "$old" && -f "$old/READY" && "$(cd "$old" && pwd -P)" != "$current" ]]; then targets+=("$old"); fi
  done
  if (( ${#targets[@]} == 0 )); then echo 'No previous release to remove.'; exit 0; fi
  echo "Active release (kept): $current"
  for t in "${targets[@]}"; do echo "  remove: $t ($(du -sh "$t" 2>/dev/null | cut -f1))"; done
  echo 'Your scans, results, scripts, settings, AI accounts and Ollama models are NOT touched.'
  read -r -p 'Type REMOVE OLD RELEASES to continue: ' ack
  [[ "$ack" == 'REMOVE OLD RELEASES' ]] || { echo 'Cancelled'; exit 2; }
  for t in "${targets[@]}"; do rm -rf -- "$t"; echo "Removed $t"; done
}

case "$MODE" in
  --dry-run) dry_run;;
  --stage) stage;;
  --activate) activate;;
  --install) stage; activate;;
  --prune-old) prune_old;;
esac
