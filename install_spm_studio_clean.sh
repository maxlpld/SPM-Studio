#!/usr/bin/env bash
# Isolated, two-stage, normal-user Ubuntu installer. Never deletes old data.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -n1)"
[[ -n "$VERSION" ]] || { echo 'Cannot read the version from pyproject.toml' >&2;exit 2; }
RELEASE="$DATA/spm-studio-ai-app/releases/$VERSION"
HOME_APP="$DATA/spm-studio-ai-app"
PY="$RELEASE/venv/bin/python"
APP="$RELEASE/app"
LAUNCHER="$HOME/.local/bin/spm-studio"
DESKTOP="$DATA/applications/org.spmstudio.SPMStudio.desktop"
ICON="$DATA/icons/hicolor/512x512/apps/org.spmstudio.SPMStudio.png"
MODE="${1:---install}"
if [[ "${EUID}" -eq 0 ]];then echo 'Run as your normal user, not sudo.' >&2;exit 2;fi
if [[ "${MODE}" != --install && "${MODE}" != --stage && "${MODE}" != --activate && "${MODE}" != --dry-run && "${MODE}" != --prune-old ]]; then
  echo 'Use --dry-run, --stage, --activate, --install or --prune-old' >&2;exit 2
fi
[[ -f "$ROOT/pyproject.toml" && -f "$ROOT/src/spm_studio/ai/chat_ui.py" ]] || { echo 'Run from the extracted release.' >&2;exit 2; }
if [[ "$MODE" == --dry-run ]];then
  printf 'Version: %s\nSource: %s\nNew isolated package: %s\nLauncher: %s\nDesktop: %s\n' "$VERSION" "$ROOT" "$RELEASE" "$LAUNCHER" "$DESKTOP"
  for old in "$HOME_APP"/releases/*/;do
    [[ -d "$old" && "${old%/}" != "$RELEASE" && -f "$old/READY" ]] && printf 'Previous release kept (remove later with --prune-old): %s\n' "${old%/}"
  done
  printf 'No old files will be removed. For old-app inventory: bash uninstall_old_research_studio.sh --dry-run\n'
  exit 0
fi
# Select a tested interpreter, not necessarily the distro's default python3
# (Ubuntu releases can ship Python 3.14+ before SPM Studio supports its wheels).
find_python() {
  local candidate
  for candidate in "${SPM_PYTHON:-}" python3.12 python3.13 python3.14 python3.15 python3; do
    [[ -n "$candidate" ]] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys, venv, ensurepip; raise SystemExit(sys.version_info[:2] < (3,12))' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}
preflight() {
  command -v unzip >/dev/null || { echo 'unzip missing: sudo apt install unzip' >&2;exit 2; }
  BASE_PY="$(find_python || true)"
  if [[ -z "$BASE_PY" ]]; then
    echo 'SPM Studio requires Python 3.12 or newer with venv and ensurepip (Python 3.11 is not supported).' >&2
    echo 'Install Python 3.12+ and its venv module, or set SPM_PYTHON to a compatible executable.' >&2
    exit 2
  fi
  "$BASE_PY" -c 'import sys; print("Python:", sys.version.split()[0], "(" + sys.executable + ")")'
  free="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
  if ((free<1000000));then echo 'At least 1 GiB free disk space recommended for Qt/scientific dependencies' >&2;exit 2;fi
}
stage() {
  preflight
  if [[ -f "$RELEASE/READY" && -x "$PY" ]];then
    echo "Existing staged release: $RELEASE"
    smoke;return
  fi
  if [[ -e "$RELEASE" ]];then echo "Partial release at $RELEASE. Back it up / remove manually; refusing to overwrite." >&2;exit 2;fi
  mkdir -p "$HOME_APP/releases"
  mkdir -p "$RELEASE"
  # Do not move the venv after pip editable install: it contains absolute paths.
  cp -a "$ROOT" "$APP"
  "$BASE_PY" -m venv "$RELEASE/venv"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -e "$APP[all]"
  smoke
  printf '%s\n' "$VERSION" > "$RELEASE/READY"
  echo "Release staged and tested: $RELEASE"
}
smoke() {
  [[ -x "$PY" ]] || { echo 'Staged interpreter missing' >&2;exit 2; }
  "$PY" - <<'PY'
import spm_studio,spm_studio.ai.config,spm_studio.ai.providers,spm_studio.ai.pi_setup,spm_studio.ai.judge_proxy
from spm_studio.core.registry import discover_modules
from spm_studio.core.processing import apply
from spm_studio.shared.store import ResearchStore
from pathlib import Path
print('Standalone SPM Studio source:',Path(spm_studio.__file__).resolve())
PY
  # Use disposable user directories so the test never edits the user's datasets/settings.
  local smokehome
  smokehome="$(mktemp -d)"
  QT_QPA_PLATFORM=offscreen XDG_DATA_HOME="$smokehome/data" XDG_CONFIG_HOME="$smokehome/config" XDG_CACHE_HOME="$smokehome/cache" \
     timeout 180 "$PY" -m spm_studio --smoke-test
  rm -rf -- "$smokehome"
}
activate() {
  [[ -f "$RELEASE/READY" ]] || { echo 'Stage and test first with --stage.' >&2;exit 2; }
  smoke
  mkdir -p "$(dirname "$LAUNCHER")" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
  ln -sfn "releases/$VERSION" "$HOME_APP/current"
  # Only overwrite the app's own named launchers; never modify research datasets.
  cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Managed by SPM Studio AI-integrated installer; new isolated release
exec "$PY" -m spm_studio "\$@"
EOF
  chmod 755 "$LAUNCHER"
  cp -f "$ROOT/assets/spm-studio.png" "$ICON"
  cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=SPM Studio
Comment=Scientific image and data analysis with optional AI assistant
Exec=$LAUNCHER
Icon=org.spmstudio.SPMStudio
Terminal=false
Categories=Science;Education;Graphics;
StartupNotify=true
EOF
  chmod 644 "$DESKTOP"
  command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP")" || true
  echo "SPM Studio $VERSION installed successfully."
  echo "Launch: $LAUNCHER"
  echo "Installed release: $RELEASE"
  echo 'AI: click "Assistant" in the header. "Set up Pi" installs and configures everything for you;'
  echo '    your existing Pi, Claude Code, Codex or a direct API key work too.'
  echo 'Older releases are kept until you run: bash install_spm_studio_clean.sh --prune-old'
}
prune_old() {
  # Remove ONLY previous SPM Studio releases created by this installer (READY marker),
  # never the active one, never user data (~/.config/spm-studio-ai, ~/.local/share/spm-studio-ai).
  local current; current="$(readlink -f "$HOME_APP/current" 2>/dev/null || true)"
  [[ -n "$current" && -f "$current/READY" ]] || { echo 'No active release found; refusing to prune.' >&2;exit 2; }
  local targets=()
  for old in "$HOME_APP"/releases/*/;do
    old="${old%/}"
    [[ -d "$old" && ! -L "$old" && -f "$old/READY" && "$(readlink -f "$old")" != "$current" ]] && targets+=("$old")
  done
  if ((${#targets[@]}==0));then echo 'No previous release to remove.';exit 0;fi
  printf 'Active release (kept): %s\nPrevious releases to remove:\n' "$current"
  for t in "${targets[@]}";do printf '  %s  (%s)\n' "$t" "$(du -sh "$t" 2>/dev/null | cut -f1)";done
  echo 'Your scans, results, scripts, settings, ~/.pi, Ollama and API keys are NOT touched.'
  read -r -p 'Type REMOVE OLD RELEASES to continue: ' ACK
  [[ "$ACK" == 'REMOVE OLD RELEASES' ]] || { echo 'Cancelled';exit 2; }
  for t in "${targets[@]}";do rm -rf -- "$t";echo "Removed $t";done
}
case "$MODE" in
 --stage) stage;;
 --activate) activate;;
 --install) stage;activate;;
 --prune-old) prune_old;;
esac
