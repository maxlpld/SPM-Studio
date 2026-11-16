"""Pin winget source when Pi setup installs Git for Windows.

Windows machines with a failing Microsoft Store source can fail to install
Git even though the Git.Git manifest is available from the winget source.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_git_for_windows_install_uses_winget_source():
    source = (ROOT / "src/spm_studio/ai/pi_wizard.py").read_text(encoding="utf-8")
    git_step = source.split("    def _install_git(self):", 1)[1].split(
        "    # ------------------------------------------------------------- 2 sign in", 1
    )[0]
    assert "'Git.Git', '--source', 'winget'" in git_step
    assert "'--accept-source-agreements'" in git_step
    assert "'--accept-package-agreements'" in git_step
    assert "https://git-scm.com/download/win" in git_step
    assert "if code != 0:" in git_step
