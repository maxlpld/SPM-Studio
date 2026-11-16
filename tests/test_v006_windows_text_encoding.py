"""Regressions for Windows cp1252 locale installer failures (v0.0.6).

Windows/Anaconda often defaults to cp1252 for Path.read_text(). Pi's generated
system-prompt context is UTF-8 and can include Unicode quotes / arrows. The
Windows CI workflow executes a real GUI smoke test with -X utf8=0.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_assistant_smoke_reads_generated_context_as_utf8():
    smoke = source("src/spm_studio/smoke.py")
    assert "spm_context_file(paths.scripts_dir()).read_text(encoding='utf-8')" in smoke
    config = source("src/spm_studio/ai/config.py")
    assert "target.write_text(text,encoding='utf8')" in config


def test_windows_smoke_sets_utf8_without_changing_user_environment():
    script = source("install_spm_studio_windows.ps1")
    assert "PYTHONUTF8 = '1'" in script
    assert "PYTHONIOENCODING = 'utf-8'" in script
    assert "foreach ($k in $saved.Keys)" in script


def test_windows_launchers_use_utf8_even_after_powershell_closes():
    script = source("install_spm_studio_windows.ps1")
    assert "$lnk.Arguments = '-X utf8 -m spm_studio'" in script
    assert '-X utf8 -m spm_studio %*' in script


def test_ci_exercises_windows_legacy_encoding():
    workflow = source(".github/workflows/test-suite.yml")
    assert "Windows GUI smoke with UTF-8 mode disabled" in workflow
    assert "python -X utf8=0 -X faulthandler -m spm_studio --smoke-test" in workflow
