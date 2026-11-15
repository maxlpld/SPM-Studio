"""Packaging regressions for SPM Studio v0.0.2 (no Qt import required)."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_mac_vosk_wheel_marker_and_supported_python():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["version"] == "0.0.2"
    assert project["requires-python"] == ">=3.11,<3.14"
    for extra in ("voice", "all"):
        deps = project["optional-dependencies"][extra]
        assert "vosk==0.3.44; sys_platform == 'darwin'" in deps
        assert "vosk>=0.3.45; sys_platform != 'darwin'" in deps


def test_public_readme_and_mac_python_preference():
    readme = (ROOT / "README.md").read_text()
    installer = (ROOT / "install_spm_studio_macos.sh").read_text()
    assert "### Private repository (invited collaborators)" not in readme
    assert "## Installation" in readme
    assert "for c in python3.12 python3.13 python3.11" in installer
    assert "sys.version_info < (3, 14)" in installer


def test_ci_keeps_tests_and_uses_xvfb():
    workflow = (ROOT / ".github/workflows/test-suite.yml").read_text()
    assert "xvfb-run -a" in workflow
    assert "-m pytest -vv -rs" in workflow
    assert "-X faulthandler" in workflow
