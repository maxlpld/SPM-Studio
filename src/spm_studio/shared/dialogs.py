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
        layout.setContentsMargins(24, 20, 24, 20)
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
    dialog.setProperty('researchDialog', True)
    return dialog


class _DialogStyle(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
            configure_dialog(watched)
        return False


def install_dialog_style() -> None:
    """Polish legacy custom dialogs too, including lazily constructed windows."""
    app = QApplication.instance()
    if app is not None and not hasattr(app, '_research_dialog_style'):
        app._research_dialog_style = _DialogStyle(app)
        app.installEventFilter(app._research_dialog_style)


class MessageDialog(QMessageBox):
    """A QMessageBox-compatible message with safe defaults and optional details."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                     Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.setSizeGripEnabled(True)

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
