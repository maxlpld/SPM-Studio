"""UI freeze recorder (v0.0.20).

Some Windows users saw the window stop responding for a few seconds. The cause cannot be seen from outside, so
SPM Studio notes it itself: a heartbeat timer runs on the GUI thread and a small background thread watches it.
When the heartbeat is late by more than ``THRESHOLD`` seconds, the Python stack of the GUI thread is captured
(what SPM Studio was doing at that moment) and, once the window responds again, one entry is appended to
``<data>/logs/ui_freezes.log`` with the duration. The Logs panel gets one short line.

Nothing leaves the computer; the report is a plain text file the user may attach to a bug report.
Settings › General › Performance and diagnostics › *Slow moments* switches it off.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

THRESHOLD = 1.0          # seconds without heartbeat = a freeze worth reporting
HEARTBEAT_MS = 200
MAX_BYTES = 512 * 1024
_SETTINGS_KEY = 'diagnostics/record_freezes'


def report_path() -> Path:
    from spm_studio.core import paths
    folder = paths.data_dir() / 'logs'
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return folder / 'ui_freezes.log'


def enabled() -> bool:
    from PySide6.QtCore import QSettings
    value = QSettings('SPM Studio', 'SPM Studio AI 0.7').value(_SETTINGS_KEY, True)
    return str(value).lower() in ('true', '1')


def set_enabled(on: bool):
    from PySide6.QtCore import QSettings
    QSettings('SPM Studio', 'SPM Studio AI 0.7').setValue(_SETTINGS_KEY, bool(on))
    if _WATCHDOG is not None:
        _WATCHDOG.active = bool(on)


class Watchdog:
    def __init__(self, log=None):
        from PySide6.QtCore import QTimer
        self.log = log
        self.active = enabled()
        self._main = threading.main_thread().ident
        self._beat = time.monotonic()
        self._stall_start = None
        self._stack = ''
        self._pending = []                    # (duration, stack, started) written by the GUI thread
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.timer = QTimer()
        self.timer.setInterval(HEARTBEAT_MS)
        self.timer.timeout.connect(self._heartbeat)
        self.timer.start()
        self.thread = threading.Thread(target=self._watch, name='spm-ui-watchdog', daemon=True)
        self.thread.start()

    # GUI thread
    def _heartbeat(self):
        self._beat = time.monotonic()
        with self._lock:
            pending, self._pending = self._pending, []
        for duration, stack, started in pending:
            self._write(duration, stack, started)

    def _write(self, duration, stack, started):
        path = report_path()
        try:
            if path.is_file() and path.stat().st_size > MAX_BYTES:
                path.replace(path.with_suffix('.old.log'))
            from spm_studio.core.updates import current_version
            with open(path, 'a', encoding='utf8') as f:
                f.write(f'=== {started:%Y-%m-%d %H:%M:%S} · not responding for {duration:.1f} s · '
                        f'SPM Studio {current_version()} · {sys.platform}\n{stack}\n')
        except Exception:
            pass
        if self.log is not None:
            where = stack.strip().splitlines()[-2].strip() if stack.strip() else ''
            try:
                self.log(f'The window did not respond for {duration:.1f} s ({where}). Details: {path}')
            except Exception:
                pass

    # watcher thread
    def _watch(self):
        while not self._stop.wait(0.25):
            if not self.active:
                self._stall_start = None
                continue
            late = time.monotonic() - self._beat
            if late > THRESHOLD and self._stall_start is None:
                self._stall_start = (time.monotonic() - late, datetime.now())
                frame = sys._current_frames().get(self._main)
                self._stack = ''.join(traceback.format_stack(frame, limit=18)) if frame is not None else ''
            elif late <= THRESHOLD and self._stall_start is not None:
                began, started = self._stall_start
                duration = max(0.0, self._beat - began)
                self._stall_start = None
                if duration >= THRESHOLD:
                    with self._lock:
                        self._pending.append((duration, self._stack, started))

    def stop(self):
        self._stop.set()
        try:
            self.timer.stop()
        except RuntimeError:
            pass


_WATCHDOG: Watchdog | None = None


def install(log=None) -> Watchdog | None:
    """Start once per process (never in headless test runs unless SPM_STUDIO_WATCHDOG=1)."""
    global _WATCHDOG
    if _WATCHDOG is not None:
        return _WATCHDOG
    if os.environ.get('QT_QPA_PLATFORM') == 'offscreen' and os.environ.get('SPM_STUDIO_WATCHDOG') != '1':
        return None
    try:
        _WATCHDOG = Watchdog(log)
    except Exception:
        _WATCHDOG = None
    return _WATCHDOG


def shutdown():
    global _WATCHDOG
    if _WATCHDOG is not None:
        _WATCHDOG.stop()
    _WATCHDOG = None
