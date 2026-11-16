"""Windows installer regression: PowerShell variables are case-insensitive.

The released v0.0.2 installer used $py for Find-Python's hashtable while
also using $Py for the venv's Python path. In Invoke-Stage those names collided:
& $Py -m pip failed with 'System.Collections.Hashtable is not recognized'.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_windows_installer_keeps_discovered_info_separate_from_venv_executable():
    script = (ROOT / "install_spm_studio_windows.ps1").read_text(encoding="utf-8")
    stage = script.split("function Invoke-Stage {", 1)[1].split(
        "\n}\n\nfunction New-Shortcut", 1
    )[0]
    assert "$PythonInfo = Find-Python" in stage
    assert "& $PythonInfo.Path -m venv $Venv" in stage
    assert "& $Py -m pip install --upgrade pip" in stage
    assert "& $Py -m pip install -e" in stage
    assert not re.search(r"\$py\b", stage)
    assert "Test-Path -LiteralPath $Py -PathType Leaf" in stage
