#!/usr/bin/env bash
# Remove the SPM Studio APPLICATION installed by install_spm_studio_macos.sh. Dry run by default.
# Kept always: scans, results, scripts, settings, conversations and AI sign-ins/keys
# (~/.config/spm-studio-ai and ~/.local/share/spm-studio-ai), Ollama and its models, ~/.pi.
#   bash uninstall_spm_studio_macos.sh                       # dry run
#   bash uninstall_spm_studio_macos.sh --apply               # asks you to type REMOVE NEW SPM
#   bash uninstall_spm_studio_macos.sh --apply --remove-ai-runtime
#        also deletes the re-downloadable private Node.js and Pi program files (sign-ins kept)
set -Eeuo pipefail
BASE="$HOME/Library/Application Support/SPMStudio"
BUNDLE="$HOME/Applications/SPM Studio.app"
LAUNCHER="$HOME/.local/bin/spm-studio"
AI="${XDG_DATA_HOME:-$HOME/.local/share}/spm-studio-ai/ai"
APPLY=0; RUNTIME=0
for arg in "$@"; do case "$arg" in --apply) APPLY=1;; --dry-run) ;; --remove-ai-runtime) RUNTIME=1;;
  *) echo "Unknown option $arg" >&2; exit 2;; esac; done
[[ "${EUID:-$(id -u)}" -ne 0 ]] || { echo 'Do not run as root'; exit 2; }
READY=0
for r in "$BASE"/releases/*/READY; do [[ -f "$r" ]] && READY=1; done
[[ ! -e "$BASE" || "$READY" == 1 ]] || { echo "Unrecognized $BASE (no installer marker): refusing"; exit 2; }
TARGETS=()
[[ "$READY" == 1 ]] && TARGETS+=("$BASE")
if [[ -d "$BUNDLE" ]] && grep -q 'SPMStudioManagedRelease' "$BUNDLE/Contents/Info.plist" 2>/dev/null; then TARGETS+=("$BUNDLE"); fi
if [[ -f "$LAUNCHER" ]] && grep -q 'spm-studio-macos' "$LAUNCHER"; then TARGETS+=("$LAUNCHER"); fi
if [[ "$RUNTIME" == 1 ]]; then for d in "$AI/node" "$AI/runtime"; do [[ -d "$d" ]] && TARGETS+=("$d"); done; fi
echo 'SPM Studio application components to remove:'
if (( ${#TARGETS[@]} == 0 )); then echo '  (nothing installed)'; else printf '  %s\n' "${TARGETS[@]}"; fi
echo 'Always kept: scans, results, scripts, settings, conversations, AI sign-ins/keys, ~/.pi, Ollama and its models.'
if [[ "$APPLY" != 1 ]]; then echo 'Dry run only. Add --apply to remove.'; exit 0; fi
if (( ${#TARGETS[@]} == 0 )); then exit 0; fi       # bash 3.2: never expand an empty array under set -u
read -r -p 'Type REMOVE NEW SPM to continue: ' ACK
[[ "$ACK" == 'REMOVE NEW SPM' ]] || { echo 'Cancelled'; exit 2; }
for p in "${TARGETS[@]}"; do
  [[ -L "$p" ]] && { echo "Refusing symlink: $p"; continue; }
  rm -rf -- "$p"; echo "Removed $p"
done
echo 'Done. User data preserved.'
