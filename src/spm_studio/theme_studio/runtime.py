"""Theme Studio runtime (Qt): applies a profile on top of SPM Studio's own stylesheet, previews, reverts, picks.

* SPM Studio's design system (``shared.appearance.apply_theme``) stays the only base: Theme Studio appends its
  rules after a marker. Whenever the app re-applies a theme (theme menu, Settings), the overlay is re-added.
* A profile is also written as a normal SPM Studio theme (``studio_<slug>.json`` in the themes folder), so it
  shows up in the usual theme menu and survives restarts; selecting it there brings the overlay back.
* Pick mode swallows every click outside the Theme Studio window: picking a control for styling never runs it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QFrame,
                               QGroupBox, QHeaderView, QLabel, QLineEdit, QMenu, QMenuBar, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QRubberBand, QScrollBar, QStatusBar,
                               QTabBar, QTextEdit, QToolButton, QAbstractItemView, QWidget)

from . import model, svgskin

MARK = '/* ===== Theme Studio — generated overlay, not part of the app ===== */'
# The beta extension (<= 0.1.0-beta.6) wrote this marker; both are removed when the overlay is rebuilt.
OLD_MARKS = ('/* ===== Theme Studio (beta) — generated overlay, not part of the app ===== */',)
PREFIX = 'studio_'


def theme_name(slug: str) -> str:
    return PREFIX + slug


class Runtime(QObject):
    changed = Signal()

    def __init__(self, store, window, prefs_file: Path):
        super().__init__(window)
        from spm_studio.shared import appearance
        self.appearance = appearance
        self.store, self.window = store, window
        self.prefs_file = Path(prefs_file)
        self.preview_profile = None            # temporary whole-app preview (None = saved state)
        self._preview_before = ''
        self._orig_apply = appearance.apply_theme
        appearance.apply_theme = self._apply_theme_wrapper
        QTimer.singleShot(0, self.reapply)

    # ------------------------------------------------------------------ prefs
    def prefs(self) -> dict:
        try:
            return json.loads(self.prefs_file.read_text(encoding='utf8'))
        except (OSError, ValueError):
            return {}

    def set_prefs(self, **changes):
        data = self.prefs()
        data.update(changes)
        tmp = self.prefs_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=1), encoding='utf8')
        tmp.replace(self.prefs_file)

    # ------------------------------------------------------------------ stylesheet overlay
    def _apply_theme_wrapper(self, theme, app=None):
        result = self._orig_apply(theme, app)
        try:
            QTimer.singleShot(0, self.reapply)   # after the caller stored the theme name
        except RuntimeError:                     # the window owning this runtime is gone
            pass
        return result

    @staticmethod
    def _app():
        return QApplication.instance()

    def base_stylesheet(self) -> str:
        sheet = self._app().styleSheet()
        for mark in (MARK,) + OLD_MARKS:
            i = sheet.find(mark)
            if i >= 0:
                sheet = sheet[:i].rstrip()
        return sheet

    def set_overlay(self, qss: str):
        app = self._app()
        if app is None:
            return
        base = self.base_stylesheet()
        wanted = base + (f'\n{MARK}\n{qss}\n' if qss.strip() else '')
        if wanted == app.styleSheet():
            return                               # re-setting the same sheet re-polishes every widget (slow)
        try:
            app.setStyleSheet(wanted)
        except Exception:                        # never leave the app unstyled
            app.setStyleSheet(base)

    def current_theme(self) -> str:
        try:
            return str(self.window.settings.value('theme', 'graphite'))
        except Exception:
            return ''

    def active_slug(self) -> str:
        name = self.current_theme()
        return name[len(PREFIX):] if name.startswith(PREFIX) else ''

    def overlay_for(self, profile: dict, scope: str = '') -> str:
        parts = [model.role_qss(profile, scope)]
        if profile.get('skin'):
            folder = self.store.skins_dir / profile['skin']
            manifests = svgskin.installed_skins(self.store.skins_dir)
            if profile['skin'] in manifests:
                parts.append(svgskin.skin_qss(folder, manifests[profile['skin']], scope,
                                              rasterize(folder, manifests[profile['skin']])))
        return '\n'.join(p for p in parts if p)

    def reapply(self):
        """Re-add the overlay of the preview, or of the active profile (if its theme is selected)."""
        try:
            if self.preview_profile is not None:
                self.set_overlay(self.overlay_for(self.preview_profile))
                return
            slug = self.active_slug()
            profiles = self.store.list() if slug else {}
            self.set_overlay(self.overlay_for(profiles[slug]) if slug in profiles else '')
        except Exception as exc:                 # a broken profile falls back to the plain theme
            self.set_overlay('')
            try:
                self.window._log(f'Theme Studio: profile not applied ({exc})')
            except Exception:
                pass
        self.changed.emit()

    # ------------------------------------------------------------------ activation / preview
    def write_theme_file(self, slug: str, profile: dict) -> Path:
        from spm_studio.core import paths
        from .store import theme_json
        folder = paths.customization_dir() / 'themes'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'{theme_name(slug)}.json'
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(theme_json(profile), indent=1), encoding='utf8')
        tmp.replace(target)
        return target

    def remove_theme_file(self, slug: str):
        from spm_studio.core import paths
        (paths.customization_dir() / 'themes' / f'{theme_name(slug)}.json').unlink(missing_ok=True)

    def activate_profile(self, slug: str):
        profile = self.store.load(slug)
        self.write_theme_file(slug, profile)
        self.preview_profile = None
        self.window._apply_theme(theme_name(slug))          # SPM Studio's own path: saved, menus refreshed
        self.reapply()

    def activate_theme(self, name: str):
        self.preview_profile = None
        self.window._apply_theme(name)
        self.reapply()

    def start_preview(self, profile: dict):
        if self.preview_profile is None:
            self._preview_before = self.current_theme()
        self.preview_profile = model.snapshot(profile)
        self._orig_apply(dict(profile['base']))            # base tokens on the running app (not saved)
        self.set_overlay(self.overlay_for(self.preview_profile))

    def update_preview(self, profile: dict):
        if self.preview_profile is not None:
            self.start_preview(profile)

    def cancel_preview(self):
        """Back to exactly what was applied before the preview."""
        if self.preview_profile is None:
            return
        self.preview_profile = None
        before = self._preview_before or 'graphite'
        try:
            self.window._apply_theme(before)
        except Exception:
            self._orig_apply({})
        self.reapply()

    def activate_studio(self, name: str):
        """Switch to one of the built-in Studio themes (light_studio / dark_studio)."""
        self.activate_theme({'beta_studio_light': 'light_studio', 'beta_studio_dark': 'dark_studio'}.get(name, name))

    def shutdown(self):
        self.appearance.apply_theme = self._orig_apply
        self.preview_profile = None
        try:
            self.set_overlay('')
        except RuntimeError:
            pass


# ---------------------------------------------------------------------- SVG → PNG (HiDPI)
def rasterize(folder: Path, manifest: dict) -> dict[str, str]:
    """PNG copies at 1× and 2× (Qt picks name@2x.png on high-DPI screens); cached by content hash."""
    from PySide6.QtSvg import QSvgRenderer
    out = {}
    cache = Path(folder) / '.raster'
    cache.mkdir(exist_ok=True)
    for role, spec in manifest['roles'].items():
        w, h = spec['reference_size']
        for state, entry in spec['states'].items():
            src = Path(folder) / entry['file']
            if not src.is_file():
                continue
            data = src.read_bytes()
            digest = hashlib.sha1(data).hexdigest()[:12]
            base = cache / f'{role}__{state}__{digest}'
            png1, png2 = base.with_suffix('.png'), Path(str(base) + '@2x.png')
            if not (png1.is_file() and png2.is_file()):
                renderer = QSvgRenderer(data)
                if not renderer.isValid():
                    continue                        # validated before, but never crash on a bad file
                for path, scale in ((png1, 1), (png2, 2)):
                    image = QImage(QSize(w * scale, h * scale), QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    renderer.render(painter)
                    painter.end()
                    image.save(str(path))
            out[entry['file']] = str(png1)
    return out


def render_check(svgs: dict[str, bytes]) -> list[str]:
    """Qt must be able to draw every SVG (complexity bound by the validator)."""
    from PySide6.QtSvg import QSvgRenderer
    return [f'{path}: Qt cannot draw this SVG' for path, data in svgs.items() if not QSvgRenderer(data).isValid()]


# ---------------------------------------------------------------------- pick from the GUI
def role_of(widget: QWidget) -> str:
    """The style role a click on ``widget`` selects (most specific registered role)."""
    w = widget
    for _ in range(6):
        if w is None:
            break
        if isinstance(w, (QPushButton, QToolButton)):
            if w.property('primary') in (True, 'true'):
                return 'button.primary'
            if w.property('destructive') in (True, 'true'):
                return 'button.destructive'
            return 'button' if isinstance(w, QPushButton) else 'toolbutton'
        if isinstance(w, (QLineEdit, QAbstractSpinBox)):
            return 'input' if not isinstance(w.parent(), QComboBox) else 'combo'
        if isinstance(w, QComboBox):
            return 'combo'
        if isinstance(w, (QPlainTextEdit, QTextEdit)):
            return 'log' if w.isReadOnly() else 'textarea'
        if isinstance(w, QTabBar):
            return 'tab'
        if isinstance(w, QMenu):
            return 'menu.item'
        if isinstance(w, QMenuBar):
            return 'menubar'
        if isinstance(w, QProgressBar):
            return 'progress.track'
        if isinstance(w, QHeaderView):
            return 'table.header'
        if isinstance(w, QAbstractItemView):
            return 'list'
        if isinstance(w, QScrollBar):
            return 'scrollbar.handle'
        if isinstance(w, (QCheckBox, QRadioButton)):
            return 'checkbox'
        if isinstance(w, QStatusBar):
            return 'statusbar'
        if isinstance(w, QGroupBox) or (isinstance(w, QFrame) and w.objectName() in ('card', 'cardPanel')):
            return 'panel'
        if isinstance(w, QFrame) and w.objectName() == 'appHeader':
            return 'header'
        if isinstance(w, QLabel):
            name, role = w.objectName(), w.property('role')
            if name == 'heading' or role == 'heading':
                return 'label.heading'
            if name == 'hint' or role == 'hint':
                return 'label.hint'
            return 'label'
        w = w.parent() if isinstance(w.parent(), QWidget) else None
        if isinstance(w, QAbstractScrollArea) and not isinstance(w, (QPlainTextEdit, QTextEdit, QAbstractItemView)):
            break
    return 'window'


class Picker(QObject):
    """Swallows clicks everywhere except in ``owner``; reports the role under the pointer. Esc ends it."""
    picked = Signal(str, object)
    finished = Signal()
    BLOCKED = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
               QEvent.Type.ContextMenu, QEvent.Type.Wheel)

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.owner = owner
        self.band = QRubberBand(QRubberBand.Shape.Rectangle)
        self.active = False

    def start(self):
        self.active = True
        QApplication.instance().installEventFilter(self)
        QApplication.setOverrideCursor(Qt.CursorShape.CrossCursor)

    def stop(self):
        if not self.active:
            return
        self.active = False
        QApplication.instance().removeEventFilter(self)
        QApplication.restoreOverrideCursor()
        self.band.hide()
        self.finished.emit()

    def _inside_owner(self, obj) -> bool:
        w = obj if isinstance(obj, QWidget) else None
        return w is not None and (w is self.owner or self.owner.isAncestorOf(w))

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.stop()
            return True
        if not isinstance(obj, QWidget) or self._inside_owner(obj):
            return False
        if kind == QEvent.Type.MouseMove or kind == QEvent.Type.Enter:
            self._highlight(obj)
            return False
        if kind in self.BLOCKED:
            if kind == QEvent.Type.MouseButtonPress:
                self._highlight(obj)
                self.picked.emit(role_of(obj), obj)
            return True                          # never reaches the control: nothing is actuated
        return False

    def _highlight(self, widget: QWidget):
        rect = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
        self.band.setGeometry(rect.adjusted(-2, -2, 2, 2))
        self.band.show()
