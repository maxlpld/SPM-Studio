"""Studio design (v0.0.19): the structural look of the "Studio Light" and "Studio Dark" themes.

A theme file with ``"design": "studio"`` gets, on top of the normal stylesheet:

* borderless rounded cards with the title inside; neighbouring cards tinted (``surface`` → ``tint_a`` →
  ``tint_b``), like the panels of the reference design;
* pill buttons, soft input fields, outlined round number badges ("01"), round BETA marks;
* quieter header, lists, menus, tabs and scroll bars.

Selected (checked) buttons keep their icon and text readable: a soft accent fill with an accent outline, never a
solid dark block.
"""
from __future__ import annotations

TONE_CYCLE = ('neutral', 'a', 'b', 'neutral')


def is_studio(tokens) -> bool:
    return str((tokens or {}).get('design', '')).lower() == 'studio'


def overlay(t: dict) -> str:
    """QSS appended after the normal stylesheet (uses the same @token names)."""
    px = max(9, round(float(t['font_size']) * 96 / 72))
    small = max(8, px - 2)
    tint_a = t.get('tint_a') or t['surface']
    tint_b = t.get('tint_b') or t['surface']
    tint_text = t.get('tint_text') or t['foreground']
    qss = f'''
/* ---- Studio design ---- */
QLabel#heading, QLabel[role="heading"] {{ font-size: {px + 9}px; font-weight: 700; letter-spacing: -0.4px; }}
QLabel#hero, QLabel#aboutTitle {{ font-size: {px * 2 + 4}px; font-weight: 700; letter-spacing: -0.8px; }}
QLabel#sectionTitle, QLabel#eyebrow, QLabel[role="section"], QLabel#panelTitle {{
    color: @muted; font-size: {small}px; font-weight: 600; letter-spacing: 0px; }}

QFrame#appHeader, QScrollArea#headerScroll, QScrollArea#headerScroll > QWidget,
QScrollArea#headerScroll > QWidget > QWidget {{ background: @bg; border: 0; }}
QStatusBar {{ background: @bg; border: 0; }}
QWidget#dockTitleBar, QDockWidget::title {{ background: @bg; border: 0; }}
QFrame#docHeader, QFrame#docRibbon {{ background: @bg; border: 0; }}
QMainWindow::separator {{ background: @bg; }}

QGroupBox {{ background: @surface; border: 0; border-radius: 18px; margin-top: 4px;
    padding: {px + 22}px 14px 12px 14px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: padding; subcontrol-position: top left; left: 14px; top: 11px;
    padding: 0; color: @fg; font-size: {px + 3}px; font-weight: 700; }}
QGroupBox[flat="true"] {{ background: transparent; border: 0; border-top: 1px solid @border; border-radius: 0;
    padding: 10px 0 0 0; }}
QGroupBox[studioTone="a"] {{ background: {tint_a}; }}
QGroupBox[studioTone="b"] {{ background: {tint_b}; }}
QGroupBox[studioTone="a"]::title, QGroupBox[studioTone="b"]::title,
QGroupBox[studioTone="a"] QLabel, QGroupBox[studioTone="b"] QLabel {{ color: {tint_text}; }}
QFrame#card, QFrame#cardPanel, QFrame#docPanel, QFrame#launcherCard, QFrame#choiceCard {{
    background: @surface; border: 0; border-radius: 18px; }}
QFrame#launcherCard:hover {{ background: @hover; border: 0; }}
QFrame#choiceCard[selected="true"] {{ border: 1.5px solid @accent; }}

QLabel#stepBadge {{ border: 1.5px solid @fg; border-radius: 15px; padding: 3px 11px; min-height: 20px;
    font-size: {px}px; font-weight: 600; background: transparent; }}
QLabel#stepTitle {{ font-size: {px + 6}px; font-weight: 700; letter-spacing: -0.3px; }}
QLabel#badge, QLabel#BetaBadgeV0014 {{ background: transparent; color: @fg; border: 1.5px solid @fg;
    border-radius: 9px; padding: 0 7px; font-size: {small}px; font-weight: 700; }}

QPushButton {{ background: @raised; border: 1px solid @border; border-radius: 15px; padding: 6px 15px;
    font-weight: 600; }}
QPushButton:hover {{ background: @hover; }}
QPushButton:pressed {{ background: @pressed; }}
QPushButton:focus {{ border: 1.5px solid @accent; }}
QPushButton:checked, QToolButton:checked {{ background: @accent_soft; color: @fg; border: 1.5px solid @accent; }}
QPushButton:disabled {{ background: @hover; color: @subtle; border-color: @hover; }}
QPushButton#primaryAction, QPushButton[primary="true"], QToolButton[primary="true"] {{
    background: @accent; color: @accent_fg; border: 1px solid @accent; font-weight: 700; }}
QPushButton#primaryAction:hover, QPushButton[primary="true"]:hover, QToolButton[primary="true"]:hover {{
    background: @accent_hover; border-color: @accent_hover; }}
QPushButton[destructive="true"] {{ background: transparent; color: @danger; border: 1.5px solid @danger; }}
QPushButton[segment="true"] {{ border-radius: 12px; padding: 5px 10px; background: transparent; border: 0; }}
QPushButton[segment="true"]:checked {{ background: @raised; color: @fg; border: 1px solid @border_strong; }}
QFrame#segmented {{ background: @surface; border: 0; border-radius: 15px; }}
QToolButton {{ border-radius: 12px; }}

QLineEdit, QComboBox, QAbstractSpinBox, QDateEdit, QTimeEdit {{ border-radius: 11px; padding: 4px 10px; }}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{ border: 1.5px solid @accent; }}
QPlainTextEdit, QTextEdit {{ border-radius: 14px; padding: 8px; }}
QComboBox QAbstractItemView {{ border-radius: 12px; }}

QListView, QListWidget, QTreeView, QTreeWidget, QTableView, QTableWidget {{ border: 0; border-radius: 14px;
    background: @surface; padding: 6px; }}
QAbstractItemView::item {{ border-radius: 8px; }}
QAbstractItemView::item:selected {{ background: @accent_soft; color: @fg; }}
QHeaderView::section {{ background: transparent; border: 0; border-bottom: 1px solid @border; }}
QMenu {{ border-radius: 14px; padding: 6px; }}
QMenu::item {{ border-radius: 8px; padding: 6px 28px 6px 12px; }}
QTabBar::tab {{ padding: 7px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ border-bottom: 2px solid @accent; color: @fg; }}
QProgressBar {{ border: 0; border-radius: 6px; background: @hover; }}
QProgressBar::chunk {{ background: @accent; border-radius: 6px; }}
QToolTip {{ border-radius: 10px; padding: 6px 10px; }}
QScrollBar:vertical {{ width: 8px; }}
QScrollBar:horizontal {{ height: 8px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ border-radius: 4px; background: @border_strong; }}
QListWidget#docOutline {{ background: @bg; border: 0; border-radius: 0; }}
QTextBrowser#docBody {{ border: 0; border-radius: 0; }}
QDialogButtonBox QPushButton {{ min-width: 88px; }}
'''
    return qss


class Tones:
    """Sibling cards (QGroupBox) get the tints neutral → a → b while the Studio design is active."""

    def __init__(self):
        self.enabled = False
        self.filter = None

    @staticmethod
    def tone_for(index: int) -> str:
        return TONE_CYCLE[index % len(TONE_CYCLE)]

    def install(self, app):
        if self.filter is not None:
            return
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtWidgets import QGroupBox
        tones = self

        class _Filter(QObject):
            def eventFilter(self, obj, event):
                if tones.enabled and event.type() == QEvent.Type.Show and isinstance(obj, QGroupBox):
                    try:
                        tones.tint(obj)
                    except Exception:
                        pass
                return False
        self.filter = _Filter(app)
        app.installEventFilter(self.filter)

    def tint(self, box):
        from PySide6.QtWidgets import QGroupBox
        if box.property('studioTone') or box.isFlat() or box.property('flat'):
            return
        parent = box.parentWidget()
        siblings = [w for w in (parent.findChildren(QGroupBox) if parent else [box])
                    if w.parentWidget() is parent and not w.isFlat()]
        index = siblings.index(box) if box in siblings else 0
        box.setProperty('studioTone', self.tone_for(index))
        box.style().unpolish(box)
        box.style().polish(box)

    def set_enabled(self, on: bool, app):
        from PySide6.QtWidgets import QGroupBox
        self.enabled = bool(on)
        for box in app.allWidgets():
            if not isinstance(box, QGroupBox):
                continue
            if on:
                if box.isVisible():
                    self.tint(box)
            elif box.property('studioTone'):
                box.setProperty('studioTone', None)
                box.style().unpolish(box)
                box.style().polish(box)


TONES = Tones()
