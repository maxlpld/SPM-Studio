"""The twelve lessons of the basics tour, on the real KBr scans and the real controls of SPM Studio.

Each step names a target control (resolved on the live main window), what the user is expected to do, and a
check that reads the *real* state of the application (opened scan, selected channel, files written …). A step
with an expected action is finished only when its check is true or when the user presses **Skip step**; the
tutorial never clicks, types or changes data on the user's behalf.

The module is Qt-free: checks only call methods of the objects they are given, so they can be tested with
simple stand-ins.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import dataset


@dataclass
class Context:
    """What a step can read: the main window, a scratch dict filled at step setup, and helpers."""
    window: object
    memo: dict = field(default_factory=dict)
    started: float = field(default_factory=time.time)
    visible_window_types: Callable[[], set] = lambda: set()


@dataclass
class Step:
    id: str
    title: str
    text: str
    target: str = ''                     # attribute path on the main window, e.g. 'inspector.channel'
    action: str = ''                     # what the user has to do ('' = reading only, Next is enough)
    check: Callable[[Context], bool] | None = None
    setup: Callable[[Context], None] | None = None
    button: tuple[str, str] | None = None   # (label, main-window method) offered in the callout


def resolve(window, target: str):
    """``'inspector.channel'`` → the widget, or ``None`` when it does not exist (any more)."""
    obj = window
    for part in [p for p in target.split('.') if p]:
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


# ------------------------------------------------------------------ helpers reading the real state
def scan_name(window) -> str:
    scan = getattr(window, 'scan', None)
    return Path(str(getattr(scan, 'path', ''))).name if scan is not None else ''


def listed_tutorial_files(window) -> set[str]:
    return {Path(p).name for p in getattr(window, '_source_paths', [])} & set(dataset.FILES)


def channel_and_trace(window) -> tuple[str, str]:
    inspector = getattr(window, 'inspector', None)
    try:
        return inspector.channel.currentText(), str(inspector.trace.currentData() or inspector.trace.currentText())
    except AttributeError:
        return '', ''


def counter(window, name: str) -> int:
    return int(getattr(window, 'tutorial_counters', {}).get(name, 0))


def module_id(window) -> str:
    module = getattr(getattr(window, 'module_panel', None), 'module', None)
    return str(getattr(module, 'id', '') or '')


def new_files(folder, since: float, pattern: str = '*') -> list[Path]:
    try:
        folder = Path(folder)
        found = [p for p in folder.glob(pattern) if p.is_file() and p.stat().st_mtime >= since - 1]
        found += [p for p in folder.glob('*/' + pattern) if p.is_file() and p.stat().st_mtime >= since - 1]
        return found
    except OSError:
        return []


def profile_files(since: float) -> list[Path]:
    try:
        from spm_studio.core import library
        folder = library.kind_dir('profiles')
    except Exception:
        return []
    return [p for p in new_files(folder, since, '*.json') if 'tutorial' in p.stem.lower()]


def assistant_open(window) -> bool:
    dock = getattr(window, 'ai_dock', None)
    try:
        return bool(dock.is_open())
    except AttributeError:
        return False


# ------------------------------------------------------------------ the course
def _memo_selection(ctx: Context):
    ctx.memo['selection'] = channel_and_trace(ctx.window)


def _memo_counter(name):
    def setup(ctx: Context):
        ctx.memo[name] = counter(ctx.window, name)
    return setup


def _memo_module(ctx: Context):
    ctx.memo['module'] = module_id(ctx.window)


def _z_and_trace_changed(ctx: Context) -> bool:
    channel, trace = channel_and_trace(ctx.window)
    first = ctx.memo.get('selection', ('', ''))
    try:
        single_trace = ctx.window.inspector.trace.count() <= 1
    except AttributeError:
        single_trace = False
    return channel == 'Z' and scan_name(ctx.window) == dataset.MAIN and (trace != first[1] or single_trace)


def basics() -> list[Step]:
    return [
        Step('welcome', 'Welcome to SPM Studio',
             'Left: your files and tools. Centre: the scan and one preview per channel. Right: the inspector '
             '(channel, trace, colours, processing) and the tool settings. Top: open, profiles, export, the '
             'assistant and ⚙ Settings. This tour uses three real KBr(001) nc-AFM scans and works offline.',
             target='browser'),
        Step('dataset', 'Open the KBr tutorial scans',
             'The three scans are bundled with SPM Studio. The button below copies them to your tutorial folder '
             '(the originals stay untouched) and lists them, like Dataset… does for your own folders.',
             target='folder_button', action='Open the tutorial folder',
             check=lambda c: len(listed_tutorial_files(c.window)) == 3,
             button=('Open the KBr tutorial folder', 'open_tutorial_scans')),
        Step('import', 'Import a real scan',
             f'Click {dataset.MAIN} in the file list. It is a complete 256 × 256 scan of 10 × 10 nm, rotated '
             '90°, recorded downwards. The step is done when the scan is displayed.',
             target='browser.files', action='Open 20261119-KBr001_008',
             check=lambda c: scan_name(c.window) == dataset.MAIN),
        Step('channel', 'Channel, trace, units',
             'In the inspector choose the Z channel (topography, in metres) and switch the trace between forward '
             'and backward. The scale bar, the colour range and Metadata (native Nanonis header) follow the '
             'channel you choose.',
             target='inspector.channel', action='Choose Z and change the trace',
             check=_z_and_trace_changed, setup=_memo_selection),
        Step('profile', 'Apply a profile',
             'A profile stores processing and display (plane, colours, range) and never changes the raw data. '
             'Pick a profile in the list at the top and press Apply profile.',
             target='profile_combo', action='Apply a profile to this scan',
             check=lambda c: counter(c.window, 'profile_applied') > c.memo.get('profile_applied', 0),
             setup=_memo_counter('profile_applied')),
        Step('library', 'Your own profile, safely',
             'Open ⚙ Settings › Library › Profiles, select a profile, press Duplicate… and give the copy a name '
             'containing “tutorial”. The original is kept; the copy is checked before it is saved.',
             target='settings_button', action='Duplicate a profile as …tutorial…',
             check=lambda c: bool(profile_files(c.started))),
        Step('compare', 'Same area, other direction',
             f'Open {dataset.UP_SCAN}. Its header gives the same nominal area as _008 but an upward scan. It is a '
             'separate acquisition: compare the drift and the features, they are not identical pixels.',
             target='browser.files', action='Open 20261119-KBr001_009',
             check=lambda c: scan_name(c.window) == dataset.UP_SCAN),
        Step('incomplete', 'An incomplete scan',
             f'Open {dataset.INCOMPLETE} (192 × 192, 10 × 10 nm, 0°) and look at Z: the scan was stopped, the '
             'last lines hold no measurement. SPM Studio shows them as missing and never invents values; '
             '“Auto-crop incomplete” can crop to the measured part (the file itself is not changed).',
             target='browser.files', action='Open 20261119-KBr001_015 and show Z',
             check=lambda c: scan_name(c.window) == dataset.INCOMPLETE and channel_and_trace(c.window)[0] == 'Z'),
        Step('tool', 'Use an analysis tool',
             'Open the Tools tab on the left and click a tool, for example “Line profile” or “Histogram”. Its '
             'settings, its README and Run appear on the right; every tool checks its module.json and entry '
             'point before it runs.',
             target='browser.tools', action='Select a tool',
             check=lambda c: bool(module_id(c.window)) and module_id(c.window) != c.memo.get('module'),
             setup=_memo_module),
        Step('guides', 'The guides',
             'Every folder of SPM Studio has a README: tools, profiles, themes, export presets … In ⚙ Settings › '
             'Library press Guide (or Read me on a tool). You, and the assistant, read these before changing '
             'anything.',
             target='settings_button', action='Open a guide',
             check=lambda c: 'GuideDialog' in c.visible_window_types()),
        Step('assistant', 'The assistant (optional)',
             'Press Assistant. You choose a backend (Pi, Claude Code, Codex or an API); nothing is installed, '
             'connected or sent before you agree. The tutorial itself never needs AI.',
             target='ai_toolbar_button', action='Open the assistant panel',
             check=lambda c: assistant_open(c.window)),
        Step('export', 'Export a figure',
             'Back on a scan, press Export… and save a figure (PNG, SVG or PDF) in a folder of yours. Raw data '
             'are never modified by an export.',
             target='export_tool', action='Export the displayed scan',
             check=lambda c: bool(new_files(getattr(c.window, 'last_export_dir', ''), c.started))
                             or counter(c.window, 'export') > c.memo.get('export', 0),
             setup=_memo_counter('export')),
    ]
