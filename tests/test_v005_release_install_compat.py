"""Regression coverage for v0.0.5 Python support and clickable dock titles.

These are packaging and installer source checks; cross-platform Qt tests and
actual Python 3.14/3.15 wheel installation run in GitHub Actions.
"""
import re
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_package_allows_python_312_and_newer():
    data = tomllib.loads(source('pyproject.toml'))
    assert data['project']['requires-python'] == '>=3.12'


def test_linux_installer_discovers_modern_python_and_checks_venv():
    script = source('install_spm_studio_clean.sh')
    assert 'python3.14 python3.15 python3' in script
    assert 'sys.version_info[:2] < (3,12)' in script
    assert 'import sys, venv, ensurepip' in script
    assert '3.14+ are not supported' not in script


def test_windows_installer_discovers_modern_python():
    script = source('install_spm_studio_windows.ps1')
    assert "foreach ($v in '312', '313', '314', '315')" in script
    assert "'-3.14', '-3.15'" in script
    assert "[version]'3.14'" not in script
    assert '--source winget' in script
    assert 'import sys,venv,ensurepip' in script


def test_macos_installer_discovers_modern_python_and_honors_override():
    script = source('install_spm_studio_macos.sh')
    assert 'python3.14 python3.15' in script
    assert 'sys.version_info[:2] >= (3, 12)' in script
    assert 'import sys, venv, ensurepip' in script
    assert '"${SPM_PYTHON:-}"' in script


def test_close_button_is_given_sufficient_titlebar_height():
    script = source('src/spm_studio/shared/appearance.py')
    assert 'bar.setMinimumHeight(DOCK_CLOSE_BUTTON + 12)' in script
    assert 'close.setFixedSize(QSize(DOCK_CLOSE_BUTTON, DOCK_CLOSE_BUTTON))' in script
    assert re.search(r'DOCK_CLOSE_BUTTON\s*=\s*28', script)
