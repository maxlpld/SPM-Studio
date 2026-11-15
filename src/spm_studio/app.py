"""Application entrypoint with persistent crash diagnostics, no hardware connections."""
from __future__ import annotations
import faulthandler
import sys
import traceback


def _ensure_streams():
    """pythonw.exe (Windows Start-menu launch) and .app bundles have no console:
    sys.stdout/stderr are None and any print() would raise."""
    import os
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))


def main():
    _ensure_streams()
    if '--check-update' in sys.argv or '--update' in sys.argv:
        # Terminal updater: same launcher on every OS (spm-studio --update)
        from .core.updates import main as update_main
        raise SystemExit(update_main(['--update'] if '--update' in sys.argv else ['--check']))
    smoke_test = "--smoke-test" in sys.argv
    if smoke_test:
        # Tested headless by the clean installer; no real hardware involved.
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.argv = [a for a in sys.argv if a != "--smoke-test"]
    from .core.paths import cache_dir
    crash_dir = cache_dir()
    crash_dir.mkdir(parents=True, exist_ok=True)
    log_path = crash_dir / 'crash.log'
    crash_log = log_path.open('a', buffering=1, encoding='utf-8')
    crash_log.write('\nSPM Studio startup\n')
    # Native Qt/NumPy faults otherwise simply close the GUI. Preserve a Python
    # traceback/all-thread dump on disk for instrument-specific fault reports.
    faulthandler.enable(file=crash_log, all_threads=True)
    original_hook = sys.excepthook

    def excepthook(t, value, tb):
        traceback.print_exception(t, value, tb, file=crash_log)
        traceback.print_exception(t, value, tb, file=sys.stderr)

    sys.excepthook = excepthook
    if sys.platform.startswith('win'):
        try:  # own taskbar group + icon instead of the generic Python one
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SPMStudio.SPMStudio')
        except Exception:
            pass
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from pathlib import Path
    from .ui.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('SPM Studio')
    app.setOrganizationName('SPM Studio')  # Keep existing user settings
    icon_path = Path(__file__).resolve().parent / 'resources' / 'spm-studio.png'
    if smoke_test:
        print('SPM Studio smoke test on', sys.platform, flush=True)
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    if sys.platform.startswith('linux'):
        app.setDesktopFileName('org.spmstudio.SPMStudio')
    win = MainWindow()
    win.show()
    if smoke_test:
        from PySide6.QtCore import QTimer
        from .smoke import run as smoke_run
        QTimer.singleShot(300, lambda: app.exit(smoke_run(win)))
    try:
        return app.exec()
    finally:
        faulthandler.disable()
        sys.excepthook = original_hook
        crash_log.close()


if __name__ == '__main__':
    raise SystemExit(main())
