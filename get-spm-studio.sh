#!/usr/bin/env bash
# Install or update SPM Studio on Linux or macOS from GitHub, in one command.
#
# Public repository:
#   curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash
#
# Private repository (invited collaborators; sign in once with the GitHub CLI: gh auth login):
#   gh api -H 'Accept: application/vnd.github.raw' repos/maxlpld/SPM-Studio/contents/get-spm-studio.sh | bash
#
# It downloads the newest released version (or SPM_VERSION=x.y.z), then runs that version's own
# installer (install_spm_studio_clean.sh on Linux, install_spm_studio_macos.sh on macOS), which builds
# the new release next to the current one, self-tests it, and only then switches the launcher.
# Running it again later updates SPM Studio. Your scans, results, tools, settings and AI accounts are kept.
#
# Options (environment variables):  SPM_VERSION=0.0.1   SPM_INSTALL_ARGS=--stage   SPM_REPO=owner/name
#                                    SPM_SKIP_SYSTEM_PACKAGES=1 (no apt check)
# Private repositories: the GitHub sign-in is taken from SPM_STUDIO_GITHUB_TOKEN, GH_TOKEN, GITHUB_TOKEN
# or `gh auth token` (SPM_STUDIO_USE_GH_CLI=0 disables the latter). It is sent only to api.github.com,
# through a temporary file readable only by you (never on the command line), and deleted afterwards.
set -Eeuo pipefail
REPO="${SPM_REPO:-maxlpld/SPM-Studio}"
API="https://api.github.com/repos/$REPO"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 2; }
have_tty() { { : </dev/tty; } 2>/dev/null; }
ask() {   # ask "question" -> 0 for yes; reads the keyboard even when piped from curl; no keyboard = no
  local a
  have_tty || return 1
  read -r -p "$1 [Y/n] " a </dev/tty || return 1
  [[ -z "$a" || "$a" == [Yy]* ]]
}

[[ "${EUID:-$(id -u)}" -ne 0 ]] || die 'Run as your normal user, not with sudo.'
[[ "$REPO" != YOUR_GITHUB_USER/* ]] || die 'This copy of get-spm-studio.sh is not configured yet: set SPM_REPO=owner/SPM-Studio, or run tools/release_tools.py set-repo before publishing.'
case "$(uname -s)" in
  Darwin) OS=macOS; INSTALLER=install_spm_studio_macos.sh;;
  Linux)  OS=Linux; INSTALLER=install_spm_studio_clean.sh;;
  *) die 'This script is for Linux and macOS. On Windows use get-spm-studio.ps1 (see the README).';;
esac
command -v curl >/dev/null || die 'curl is required'
if ! command -v unzip >/dev/null; then
  if [[ "$OS" == Linux ]] && command -v apt-get >/dev/null && ask 'unzip is missing. Install it with sudo apt?'; then
    sudo apt-get install -y unzip
  fi
  command -v unzip >/dev/null || die 'unzip is required'
fi

# Ubuntu/Debian: the Qt libraries SPM Studio needs (asked once, only if something is missing).
if [[ "$OS" == Linux && -z "${SPM_SKIP_SYSTEM_PACKAGES:-}" ]] && command -v dpkg >/dev/null && command -v apt-get >/dev/null; then
  missing=()
  for p in python3 python3-venv python3-pip libxcb-cursor0 libgl1 libegl1 libxkbcommon-x11-0; do
    dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if (( ${#missing[@]} )); then
    say "Missing system packages: ${missing[*]}"
    if ask 'Install them now with sudo apt (asks for your password)?'; then
      sudo apt-get update && sudo apt-get install -y "${missing[@]}"
    else
      echo "Install later with: sudo apt install ${missing[*]}"
    fi
  fi
fi

WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

# Optional GitHub sign-in (private repositories). Written to a 0600 file so it never appears in `ps`.
TOKEN="${SPM_STUDIO_GITHUB_TOKEN:-${GH_TOKEN:-${GITHUB_TOKEN:-}}}"
case "${SPM_STUDIO_USE_GH_CLI:-1}" in 0|false|no|off) ;; *)
  if [[ -z "$TOKEN" ]] && command -v gh >/dev/null 2>&1; then
    TOKEN="$(gh auth token --hostname github.com 2>/dev/null || true)"
  fi;;
esac
AUTH=()
if [[ -n "$TOKEN" ]]; then
  (umask 077; printf 'Authorization: Bearer %s\n' "$TOKEN" > "$WORK/auth.header")
  AUTH=(-H "@$WORK/auth.header")
fi
unset TOKEN
api() { curl -fsSL -H 'Accept: application/vnd.github+json' ${AUTH[@]+"${AUTH[@]}"} "$API/$1"; }

# JSON read with sed only: works before Python is installed (macOS) and with bash 3.2.
latest_tag() {
  local tag
  tag="$(api releases/latest 2>/dev/null | tr "," "\n" \
         | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  if [[ -z "$tag" ]]; then   # no GitHub Release yet: newest x.y.z version tag
    tag="$(api 'tags?per_page=100' 2>/dev/null | tr "," "\n" \
           | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\(v\{0,1\}[0-9][0-9]*\.[0-9][0-9]*\(\.[0-9][0-9]*\)\{0,1\}\)".*/\1/p' \
           | awk '{v=$0; sub(/^v/,"",v); split(v,a,"."); printf "%d %d %d %s\n", a[1], a[2], a[3], $0}' \
           | sort -k1,1n -k2,2n -k3,3n | tail -n1 | awk '{print $4}')"
  fi
  printf '%s' "$tag"
}

if [[ -n "${SPM_VERSION:-}" ]]; then TAG="v${SPM_VERSION#v}"; else TAG="$(latest_tag)"; fi
if [[ -z "$TAG" ]]; then
  if (( ${#AUTH[@]} )); then
    die "No released version found at https://github.com/$REPO, or your GitHub account has no access to it."
  fi
  die "No released version found at https://github.com/$REPO. If the repository is private: install the GitHub CLI, run 'gh auth login' once, then run this command again (see the README, Private repository)."
fi
VERSION="${TAG#v}"

if command -v spm-studio >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/spm-studio" ]]; then
  say "Updating SPM Studio to $VERSION ($OS) from github.com/$REPO"
else
  say "Installing SPM Studio $VERSION ($OS) from github.com/$REPO"
fi

if (( ${#AUTH[@]} )); then   # private: authenticated API archive (GitHub redirects to a signed URL; curl drops the header there)
  URL="$API/zipball/$TAG"
else
  URL="https://github.com/$REPO/archive/refs/tags/$TAG.zip"
fi
curl -fL --progress-bar ${AUTH[@]+"${AUTH[@]}"} "$URL" -o "$WORK/spm.zip" || die "Download of $TAG failed"
rm -f -- "$WORK/auth.header"
unzip -q "$WORK/spm.zip" -d "$WORK/src"
TOML="$(find "$WORK/src" -maxdepth 3 -name pyproject.toml -print -quit)"
[[ -n "$TOML" ]] || die 'The downloaded archive does not contain SPM Studio'
SRC="$(dirname "$TOML")"
[[ -f "$SRC/$INSTALLER" && -d "$SRC/src/spm_studio" ]] || die 'The downloaded archive does not contain SPM Studio'

cd "$SRC"
if have_tty; then
  bash "./$INSTALLER" ${SPM_INSTALL_ARGS:-} </dev/tty
else
  bash "./$INSTALLER" ${SPM_INSTALL_ARGS:-}
fi
