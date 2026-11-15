#!/bin/bash
# Double-clickable wrapper (Finder). If macOS refuses to open it, right-click > Open, or run in Terminal:
#   bash install_spm_studio_macos.sh
cd "$(dirname "$0")" || exit 2
bash ./install_spm_studio_macos.sh "$@"
rc=$?
echo
read -r -p 'Press Enter to close this window. ' _
exit $rc
