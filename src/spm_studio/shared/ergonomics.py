"""Application-wide ergonomics (v0.0.18), installed once on the QApplication.

* **Scrolling scrolls the panel.** The mouse wheel over a drop-down list, number box or slider no longer changes
  its value while you scroll a panel: the wheel goes to the panel. A control reacts to the wheel only after you
  clicked into it (it has the keyboard focus).
* **Short help texts.** Long grey hint texts show their essential first sentence; the full text is in the
  tooltip (Settings › General › *Full help texts* brings the long versions back).
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QLabel,
                               QSlider, QWidget)

HINT_LIMIT = 120          # characters kept in a compact hint
_SETTINGS_KEY = 'ui/full_help_texts'


def full_help_texts() -> bool:
    from PySide6.QtCore import QSettings
    value = QSettings('SPM Studio', 'SPM Studio AI 0.7').value(_SETTINGS_KEY, False)
    return str(value).lower() in ('true', '1')


def set_full_help_texts(on: bool):
    from PySide6.QtCore import QSettings
    QSettings('SPM Studio', 'SPM Studio AI 0.7').setValue(_SETTINGS_KEY, bool(on))
    app = QApplication.instance()
    if app is not None:
        for label in app.allWidgets():
            if isinstance(label, QLabel) and label.property('spmFullText') is not None:
                compact_hint(label, force_full=on)


def _is_value_control(widget) -> bool:
    return isinstance(widget, (QComboBox, QAbstractSpinBox, QSlider))


def _scroll_area_of(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea) and not _is_value_control(parent):
            return parent
        parent = parent.parentWidget()
    return None


def short_text(text: str, limit: int = HINT_LIMIT) -> str:
    """The essential part of a help text: its first sentence, at most ``limit`` characters."""
    plain = ' '.join(str(text).split())
    if len(plain) <= limit:
        return plain
    m = re.match(r'^(.{20,}?[.!?:])\s', plain)
    first = m.group(1) if m else plain
    if len(first) > limit:
        cut = first[:limit].rsplit(' ', 1)[0]
        first = cut.rstrip(',;:–—- ') + '…'
    return first


def compact_hint(label: QLabel, force_full: bool | None = None):
    """Show the short form of a long hint label (full text in its tooltip)."""
    full = label.property('spmFullText')
    if full is None:
        if label.textFormat() == Qt.TextFormat.RichText or re.search(r'<[a-zA-Z/][^>]*>', label.text()):
            return
        full = label.text()
        if len(' '.join(full.split())) <= HINT_LIMIT:
            return
        label.setProperty('spmFullText', full)
        if not label.toolTip():
            label.setToolTip(full)
    show_full = full_help_texts() if force_full is None else force_full
    label.blockSignals(True)
    label.setText(full if show_full else short_text(full))
    label.blockSignals(False)


class _Ergonomics(QObject):
    def eventFilter(self, obj, event):
        try:
            return self._filter(obj, event)
        except Exception:                       # an ergonomic helper must never break the application
            return False

    def _filter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Wheel and isinstance(obj, QWidget) and _is_value_control(obj):
            if not obj.hasFocus():
                area = _scroll_area_of(obj)
                if area is not None:
                    bar = area.horizontalScrollBar() if (event.angleDelta().y() == 0 and
                                                         event.angleDelta().x() != 0) else area.verticalScrollBar()
                    QApplication.sendEvent(bar, event)
                return True                     # never change a value that was not chosen
        elif kind == QEvent.Type.Polish and isinstance(obj, QWidget):
            if _is_value_control(obj) and obj.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        elif kind == QEvent.Type.Show and isinstance(obj, QLabel):
            if obj.objectName() == 'hint' or obj.property('role') == 'hint':
                compact_hint(obj)
        return False


def install(app=None):
    app = app or QApplication.instance()
    if app is None or getattr(app, '_spm_ergonomics', None) is not None:
        return
    app._spm_ergonomics = _Ergonomics(app)
    app.installEventFilter(app._spm_ergonomics)
