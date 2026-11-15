#!/usr/bin/env python3
"""Cross-platform entry point: runs the installer for this operating system.

    Linux   : bash install_spm_studio_clean.sh
    macOS   : bash install_spm_studio_macos.sh
    Windows : powershell -ExecutionPolicy Bypass -File install_spm_studio_windows.ps1
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

if __name__ == '__main__':
    args = sys.argv[1:]
    if sys.platform.startswith('win'):
        cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(HERE / 'install_spm_studio_windows.ps1'), *args]
    elif sys.platform == 'darwin':
        cmd = ['bash', str(HERE / 'install_spm_studio_macos.sh'), *args]
    else:
        cmd = ['bash', str(HERE / 'install_spm_studio_clean.sh'), *args]
    raise SystemExit(subprocess.call(cmd))
