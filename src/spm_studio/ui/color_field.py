"""v34: one colour chooser for every colour setting (swatch button + colour dialog)."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QColorDialog


class ColorField(QWidget):
    """A colour swatch that opens the colour selector; the #rrggbb code stays editable."""
    changed = Signal(str)

    def __init__(self, color='#111111', title='Choose colour', parent=None):
        super().__init__(parent)
        self._title = title
        row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0)
        self.swatch = QPushButton('Choose…')
        self.swatch.setObjectName('ColorFieldSwatchV34')
        self.swatch.setToolTip('Open the colour selector')
        self.swatch.clicked.connect(self.pick)
        self.edit = QLineEdit(str(color)); self.edit.setMaximumWidth(96)
        self.edit.setToolTip('Colour code (#rrggbb); use the button to pick visually')
        self.edit.textChanged.connect(self._text_changed)
        row.addWidget(self.swatch, 1); row.addWidget(self.edit)
        self._paint()

    def text(self):
        return self.edit.text().strip()

    def setText(self, value):
        self.edit.setText(str(value))

    def _text_changed(self, *_):
        self._paint()
        self.changed.emit(self.text())

    def _paint(self):
        c = QColor(self.text())
        if not c.isValid():
            self.swatch.setStyleSheet('')
            return
        fg = '#000000' if c.lightness() > 140 else '#ffffff'
        self.swatch.setStyleSheet(f'background-color:{c.name()};color:{fg};border:1px solid #666;padding:3px 8px;')

    def pick(self):
        start = QColor(self.text())
        picked = QColorDialog.getColor(start if start.isValid() else QColor('#111111'), self, self._title)
        if picked.isValid():
            self.setText(picked.name())
