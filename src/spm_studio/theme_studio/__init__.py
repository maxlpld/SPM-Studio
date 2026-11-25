"""Theme Studio (v0.0.20, from the private beta): visual theme editor and SVG skins for SPM Studio.

Open it from Settings › Appearance › *Open Theme Studio*. It changes no file of the application: profiles and
skins live in ``<customization>/theme_studio``; an activated profile is also written as a normal theme
(``studio_<slug>.json`` in the themes folder) so that it appears in every theme list and survives restarts.

The runtime is installed once at start-up (``install(window)``): it re-adds the overlay of the active profile
every time SPM Studio applies a theme. Profiles made with the beta extension are imported automatically.
"""
from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

_STUDIO = None


def root() -> Path:
    from spm_studio.core import paths
    return paths.customization_dir() / 'theme_studio'


def _migrate_beta_profiles(target: Path):
    """Copy the profiles / skins of the beta extension (once, never overwriting)."""
    from spm_studio.core import paths
    old = paths.data_dir() / 'extension_data' / 'spm-studio-nano' / 'theme_studio'
    marker = target / '.migrated_from_beta'
    if marker.exists() or not old.is_dir():
        return
    for sub in ('profiles', 'skins'):
        src = old / sub
        if not src.is_dir():
            continue
        for item in src.iterdir():
            dest = target / sub / item.name
            if dest.exists():
                continue
            try:
                (shutil.copytree if item.is_dir() else shutil.copy2)(item, dest)
            except OSError:
                pass
    if (old / 'prefs.json').is_file() and not (target / 'prefs.json').exists():
        try:
            shutil.copy2(old / 'prefs.json', target / 'prefs.json')
        except OSError:
            pass
    try:
        marker.write_text('profiles imported from the beta Theme Studio\n', encoding='utf8')
    except OSError:
        pass


def shadow_beta_extension():
    """The private beta extension (≤ 0.1.0-beta.6) also shipped Theme Studio as ``spm_beta_themes``.

    Now that it is part of SPM Studio, its copy must not install a second runtime or a second Settings page: a
    no-op module takes its name before extensions are loaded (the companion itself is unaffected).
    """
    if 'spm_beta_themes' in sys.modules:
        return
    stub = types.ModuleType('spm_beta_themes')
    stub.__doc__ = 'Theme Studio is built into SPM Studio 0.0.20+; the beta copy is not activated.'
    stub.BUILTIN = True
    stub.activate = lambda api=None: None
    stub.deactivate = lambda: None
    sys.modules['spm_beta_themes'] = stub


class ThemeStudio:
    def __init__(self, window):
        from .runtime import Runtime
        from .store import Store
        self.window = window
        folder = root()
        self.store = Store(folder)
        _migrate_beta_profiles(folder)
        self.runtime = Runtime(self.store, window, folder / 'prefs.json')
        self.studio = None

    def open(self):
        from .ui import ThemeStudioWindow
        if self.studio is None or not self.studio.isVisible():
            self.studio = ThemeStudioWindow(self)
        self.studio.show()
        self.studio.raise_()
        self.studio.activateWindow()
        return self.studio

    def active_profile_name(self) -> str:
        slug = self.runtime.active_slug()
        profiles = self.store.list() if slug else {}
        return profiles[slug]['name'] if slug in profiles else ''

    def shutdown(self):
        if self.studio is not None:
            try:
                self.studio.picker.stop()
                self.studio.close()
            except RuntimeError:
                pass
        self.runtime.shutdown()


def install(window) -> ThemeStudio | None:
    global _STUDIO
    if _STUDIO is not None and _STUDIO.window is window:
        return _STUDIO
    if _STUDIO is not None:                  # another main window before (tests): unwrap its runtime first
        try:
            _STUDIO.shutdown()
        except Exception:
            pass
        _STUDIO = None
    try:
        _STUDIO = ThemeStudio(window)
    except Exception as exc:                 # Theme Studio must never prevent SPM Studio from starting
        try:
            window._log(f'Theme Studio not available: {exc}')
        except Exception:
            pass
        _STUDIO = None
    return _STUDIO


def instance() -> ThemeStudio | None:
    return _STUDIO


def shutdown():
    global _STUDIO
    if _STUDIO is not None:
        try:
            _STUDIO.shutdown()
        except Exception:
            pass
    _STUDIO = None
