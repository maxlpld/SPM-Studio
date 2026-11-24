"""Shared Qt dialogs and layout conventions for every native module.

Native file choosers retain their platform behavior. Message text is plain text;
callers can put a traceback or compiler output in the expandable details panel.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QInputDialog, QLabel, QLayout, QLineEdit, QMessageBox, QPushButton,
)


def configure_dialog(dialog: QDialog, *, minimum_width: int = 360) -> QDialog:
    """Apply consistent spacing and usable defaults without replacing content."""
    if isinstance(dialog, QFileDialog):
        return dialog
    screen = dialog.screen() or QApplication.primaryScreen()
    available = screen.availableGeometry().width() - 48 if screen else 900
    dialog.setMinimumWidth(min(max(minimum_width, dialog.minimumWidth()), max(240, available)))
    layout = dialog.layout()
    if layout:
        titled = dialog.property('spmRounded') and dialog.findChild(QLabel, 'popupTitle') is not None
        layout.setContentsMargins(24, 42 if titled else 20, 24, 20)
        layout.setSpacing(12)
    for form in dialog.findChildren(QFormLayout):
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    for box in dialog.findChildren(QDialogButtonBox):
        box.setCenterButtons(False)
        for button in box.buttons():
            button.setMinimumWidth(80)
        # A deliberate confirm action is activated by Return; Escape cancels.
        for role in (() if isinstance(dialog, QMessageBox) or any(b.isDefault() for b in box.buttons()) else
                     (QDialogButtonBox.ButtonRole.AcceptRole, QDialogButtonBox.ButtonRole.YesRole)):
            candidates = [b for b in box.buttons() if box.buttonRole(b) == role]
            if candidates:
                candidates[0].setDefault(True)
                break
    _normalise_buttons(dialog)
    dialog.setProperty('researchDialog', True)
    return dialog


def _normalise_buttons(dialog: QDialog) -> None:
    """v0.0.18: one look for every pop-up: the confirming button is the primary (accent) button.

    Applies to the button boxes of message boxes, input dialogs and custom dialogs; buttons that already chose a
    style (primary / destructive / flat) keep it.
    """
    from PySide6.QtGui import QIcon
    for box in dialog.findChildren(QDialogButtonBox):
        buttons = box.buttons()
        for b in buttons:                     # v0.0.19: no green tick / red cross icons on pop-up buttons
            if not b.icon().isNull():
                b.setIcon(QIcon())
        if any(b.property('primary') for b in buttons):
            continue
        accept = (QDialogButtonBox.ButtonRole.AcceptRole, QDialogButtonBox.ButtonRole.YesRole,
                  QDialogButtonBox.ButtonRole.ApplyRole)
        chosen = [b for b in buttons if b.isDefault() and box.buttonRole(b) in accept] or \
                 [b for b in buttons if box.buttonRole(b) in accept]
        if len(buttons) == 1:
            chosen = buttons
        if chosen and not chosen[0].property('destructive'):
            button = chosen[0]
            button.setProperty('primary', True)
            button.style().unpolish(button)
            button.style().polish(button)


def size_to_content(widget) -> None:
    """Open a window large enough for its content (v0.0.19): nothing cut, no scroll bar when it fits.

    Grows to the layout's size hint and, for scroll areas, to the size of what they contain; never shrinks a
    window and never exceeds the screen (see :func:`fit_to_screen`). Done once, at the first show.
    """
    from PySide6.QtWidgets import QScrollArea
    if widget.property('spmSized'):
        return
    widget.setProperty('spmSized', True)
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    hint = widget.sizeHint()
    w, h = max(widget.width(), hint.width()), max(widget.height(), hint.height())
    extra_w = extra_h = 0
    for area in widget.findChildren(QScrollArea):
        inner = area.widget()
        if inner is None or not area.isVisibleTo(widget) or not area.widgetResizable():
            continue
        need = inner.sizeHint()
        view = area.viewport().size()
        extra_w = max(extra_w, need.width() - view.width())
        extra_h = max(extra_h, need.height() - view.height())
    w += max(0, min(extra_w, 900))
    h += max(0, min(extra_h, 900))
    if (w, h) != (widget.width(), widget.height()):
        widget.resize(w, h)


def fit_to_screen(widget) -> None:
    """Keep a window inside the available screen area (no part off-screen, no overlap with the task bar)."""
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry().adjusted(12, 12, -12, -12)
    w, h = min(widget.width(), area.width()), min(widget.height(), area.height())
    if (w, h) != (widget.width(), widget.height()):
        widget.resize(w, h)
    frame = widget.frameGeometry()
    x = min(max(frame.x(), area.x()), area.right() - frame.width())
    y = min(max(frame.y(), area.y()), area.bottom() - frame.height())
    if (x, y) != (frame.x(), frame.y()) and widget.isWindow():
        widget.move(x, y)


ROUNDED_POPUPS = (QMessageBox, QInputDialog)
ROUND_RADIUS = 16


def rounded_popups_enabled() -> bool:
    from PySide6.QtCore import QSettings
    value = QSettings('SPM Studio', 'SPM Studio AI 0.7').value('ui/rounded_popups', True)
    return str(value).lower() in ('true', '1')


def make_rounded(dialog) -> None:
    """Small pop-ups get all four corners rounded (v0.0.19): drawn by the app instead of the system frame.

    The pop-up has no system title bar; it can be moved by dragging its background. Large windows keep the
    system frame (needed to resize them).
    """
    if dialog.property('spmRounded') is not None or dialog.isVisible():
        return
    dialog.setProperty('spmRounded', True)
    title = dialog.windowTitle()
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    dialog.setWindowTitle(title)
    if isinstance(dialog, QMessageBox) and title:
        box_title = QLabel(title, dialog)
        box_title.setObjectName('popupTitle')
        box_title.move(24, 14)
        box_title.adjustSize()
    layout = dialog.layout()
    if layout is not None:
        m = layout.contentsMargins()
        layout.setContentsMargins(max(m.left(), 24), max(m.top(), 40 if isinstance(dialog, QMessageBox) and title
                                                          else 22), max(m.right(), 24), max(m.bottom(), 20))


def _paint_rounded(dialog) -> None:
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
    from .appearance import colors
    t = colors()
    painter = QPainter(dialog)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = dialog.rect().adjusted(1, 1, -1, -1)
    path = QPainterPath()
    path.addRoundedRect(rect, ROUND_RADIUS, ROUND_RADIUS)
    painter.fillPath(path, QColor(t['background']))
    painter.setPen(QPen(QColor(t['border_strong']), 1))
    painter.drawPath(path)
    painter.end()


class _DialogStyle(QObject):
    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.Show and isinstance(watched, QDialog):
            configure_dialog(watched)
            if not isinstance(watched, QFileDialog):
                size_to_content(watched)
                fit_to_screen(watched)
        elif kind == QEvent.Type.Paint and isinstance(watched, QDialog) and watched.property('spmRounded'):
            _paint_rounded(watched)
        elif (kind == QEvent.Type.MouseButtonPress and isinstance(watched, QDialog)
              and watched.property('spmRounded') and event.button() == Qt.MouseButton.LeftButton):
            handle = watched.windowHandle()
            if handle is not None:
                handle.startSystemMove()           # drag the pop-up by its background
        return False


def _rounded_static(icon, default_buttons):
    """QMessageBox.information / warning / critical / question, as rounded pop-ups (v0.0.19)."""
    def message(parent, title, text, buttons=None, defaultButton=None):
        SB = QMessageBox.StandardButton
        box = QMessageBox(icon, str(title), str(text), buttons if buttons is not None else default_buttons, parent)
        if defaultButton is not None and defaultButton != SB.NoButton:
            box.setDefaultButton(defaultButton)
        if rounded_popups_enabled():
            make_rounded(box)
        box.exec()
        clicked = box.clickedButton()
        return box.standardButton(clicked) if clicked is not None else SB.NoButton
    message._spm_rounded = True
    return message


def install_dialog_style() -> None:
    """Polish legacy custom dialogs too, including lazily constructed windows."""
    app = QApplication.instance()
    if app is not None and not hasattr(app, '_research_dialog_style'):
        app._research_dialog_style = _DialogStyle(app)
        app.installEventFilter(app._research_dialog_style)
        SB, Icon = QMessageBox.StandardButton, QMessageBox.Icon
        for name, icon, default in (('information', Icon.Information, SB.Ok), ('warning', Icon.Warning, SB.Ok),
                                    ('critical', Icon.Critical, SB.Ok),
                                    ('question', Icon.Question, SB.Yes | SB.No)):
            if not getattr(getattr(QMessageBox, name), '_spm_rounded', False):
                setattr(QMessageBox, name, staticmethod(_rounded_static(icon, default)))


class MessageDialog(QMessageBox):
    """A QMessageBox-compatible message with safe defaults and optional details."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                     Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.setSizeGripEnabled(True)
        if rounded_popups_enabled():
            make_rounded(self)

    def showEvent(self, event):
        label = self.findChild(QLabel, 'qt_msgbox_label')
        if label:
            screen = self.screen() or QApplication.primaryScreen()
            available = screen.availableGeometry().width() if screen else 800
            label.setMinimumWidth(max(180, min(300, available - 120)))
            label.setWordWrap(True)
        super().showEvent(event)
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        configure_dialog(self, minimum_width=400)

    @classmethod
    def _message(cls, icon, parent, title, text, buttons, defaultButton, *, details=None):
        dialog = cls(parent)
        dialog.setWindowTitle(title)
        dialog.setIcon(icon)
        dialog.setText(str(text))
        dialog.setStandardButtons(buttons)
        if details:
            dialog.setDetailedText(str(details))
        if defaultButton == cls.StandardButton.NoButton:
            for candidate in (cls.StandardButton.Cancel, cls.StandardButton.No, cls.StandardButton.Ok):
                if buttons & candidate:
                    defaultButton = candidate
                    break
        if defaultButton != cls.StandardButton.NoButton:
            dialog.setDefaultButton(defaultButton)
        try:
            return cls.StandardButton(dialog.exec())
        finally:
            dialog.deleteLater()

    @classmethod
    def information(cls, parent, title, text, buttons=QMessageBox.StandardButton.Ok,
                    defaultButton=QMessageBox.StandardButton.NoButton, *, details=None):
        return cls._message(cls.Icon.Information, parent, title, text, buttons, defaultButton, details=details)

    @classmethod
    def warning(cls, parent, title, text, buttons=QMessageBox.StandardButton.Ok,
                defaultButton=QMessageBox.StandardButton.NoButton, *, details=None):
        return cls._message(cls.Icon.Warning, parent, title, text, buttons, defaultButton, details=details)

    @classmethod
    def critical(cls, parent, title, text, buttons=QMessageBox.StandardButton.Ok,
                 defaultButton=QMessageBox.StandardButton.NoButton, *, details=None):
        return cls._message(cls.Icon.Critical, parent, title, text, buttons, defaultButton, details=details)

    @classmethod
    def question(cls, parent, title, text,
                 buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                 defaultButton=QMessageBox.StandardButton.NoButton, *, details=None):
        return cls._message(cls.Icon.Question, parent, title, text, buttons, defaultButton, details=details)

    @classmethod
    def confirm(cls, parent, title, text, action='Delete', *, details=None) -> bool:
        """Describe a destructive action explicitly; Cancel is always the default."""
        dialog = cls(parent)
        dialog.setWindowTitle(title)
        dialog.setIcon(cls.Icon.Warning)
        dialog.setText(text)
        if details:
            dialog.setDetailedText(details)
        proceed = dialog.addButton(action, cls.ButtonRole.DestructiveRole)
        proceed.setProperty('destructive', True)
        cancel = dialog.addButton(cls.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        try:
            dialog.exec()
            return dialog.clickedButton() is proceed
        finally:
            dialog.deleteLater()


class TextInputDialog(QInputDialog):
    """Native Qt inputs with the shared dialog spacing and accessible labels."""
    def showEvent(self, event):
        super().showEvent(event)
        configure_dialog(self)
        for label in self.findChildren(QLabel):
            label.setWordWrap(True)

    @classmethod
    def getText(cls, parent, title, label, echo=QLineEdit.EchoMode.Normal, text='',
                flags=Qt.WindowType.Widget, inputMethodHints=Qt.InputMethodHint.ImhNone):
        dialog = cls(parent, flags)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextEchoMode(echo)
        dialog.setTextValue(text)
        dialog.setInputMethodHints(inputMethodHints)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return dialog.textValue(), accepted
        finally:
            dialog.deleteLater()

    @classmethod
    def getItem(cls, parent, title, label, items, current=0, editable=True,
                flags=Qt.WindowType.Widget, inputMethodHints=Qt.InputMethodHint.ImhNone):
        dialog = cls(parent, flags)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(items)
        dialog.setComboBoxEditable(editable)
        if items and 0 <= current < len(items):
            dialog.setTextValue(items[current])
        dialog.setInputMethodHints(inputMethodHints)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return dialog.textValue(), accepted
        finally:
            dialog.deleteLater()
