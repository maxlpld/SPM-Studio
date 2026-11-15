#!/usr/bin/env bash
set -Eeuo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DATA/spm-studio-ai-app"
LAUNCHER="$HOME/.local/bin/spm-studio"
DESKTOP="$DATA/applications/org.spmstudio.SPMStudio.desktop"
ICON="$DATA/icons/hicolor/512x512/apps/org.spmstudio.SPMStudio.png"
[[ "${EUID}" -ne 0 ]] || { echo 'Do not run as root';exit 2; }
MODE=--dry-run;RUNTIME=0
for arg in "$@";do case "$arg" in --dry-run|--apply) MODE="$arg";; --remove-ai-runtime) RUNTIME=1;;
  *) echo 'Use --dry-run or --apply [--remove-ai-runtime]';exit 2;; esac;done
AI="${XDG_DATA_HOME:-$HOME/.local/share}/spm-studio-ai/ai"
READY_FOUND=0
for r in "$APP"/releases/*/READY;do [[ -f "$r" ]] && READY_FOUND=1;done
[[ ! -e "$APP" || "$READY_FOUND" == 1 ]] || { echo 'Unrecognized new app directory: refusing';exit 2; }
TARGETS=()
[[ "$READY_FOUND" == 1 ]] && TARGETS+=("$APP")
if [[ -f "$LAUNCHER" ]] && grep -q 'spm-studio-ai-app/releases' "$LAUNCHER";then TARGETS+=("$LAUNCHER");fi
if [[ -f "$DESKTOP" ]] && grep -q 'Scientific image and data analysis with optional AI assistant' "$DESKTOP";then TARGETS+=("$DESKTOP");fi
if [[ -f "$ICON" && "$READY_FOUND" == 1 ]];then TARGETS+=("$ICON");fi
# Optional: re-downloadable private Node.js / Pi program files (AI sign-ins in ai/pi-agent are kept)
if [[ "$RUNTIME" == 1 ]];then for d in "$AI/node" "$AI/runtime";do [[ -d "$d" ]] && TARGETS+=("$d");done;fi
printf 'New SPM Studio application components only:\n'
printf '  %s\n' "${TARGETS[@]}"
echo 'Always preserved: all research scans, scripts, settings, session history, AI sign-ins/keys, ~/.pi, Ollama and its models.'
if [[ "$MODE" == --dry-run ]];then exit 0;fi
((${#TARGETS[@]})) || exit 0
read -r -p 'Type REMOVE NEW SPM to continue: ' ACK
[[ "$ACK" == 'REMOVE NEW SPM' ]] || { echo 'Cancelled';exit 2; }
for p in "${TARGETS[@]}";do
  [[ -L "$p" ]] && { echo "Refusing symlink: $p";continue; }
  if [[ -d "$p" ]];then rm -rf -- "$p";else rm -f -- "$p";fi
done
printf 'Removed verified installed package components; user data preserved.\n'
