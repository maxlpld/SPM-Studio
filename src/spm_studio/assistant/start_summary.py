"""On start: reminders missed while SPM Studio was closed, and what comes in the next 24 hours."""
from __future__ import annotations

import datetime as dt
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class StartSummary(QDialog):
    openCalendar = Signal()
    openTodo = Signal()

    def __init__(self, summary: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Calendar and to-do')
        self.setModal(False)
        lay = QVBoxLayout(self)
        rows = []

        def when(value):
            if isinstance(value, dt.datetime):
                return value.strftime('%a %d %b %H:%M')
            return value.strftime('%a %d %b') if hasattr(value, 'strftime') else str(value)
        if summary.get('missed'):
            rows.append('<b>Missed while SPM Studio was closed</b>')
            rows += [f"{html.escape(when(r['at']))} · {html.escape(r['title'])}" for r in summary['missed'][:12]]
        if summary.get('overdue'):
            rows.append('<b>Overdue to-dos</b>')
            rows += [f"{html.escape(t.get('due', '').replace('T', ' '))} · {html.escape(t['title'])}"
                     for t in summary['overdue'][:12]]
        if summary.get('upcoming'):
            rows.append('<b>Next 24 hours</b>')
            rows += [f"{html.escape('all day' if u['all_day'] else when(u['start']))} · {html.escape(u['title'])}"
                     + (' (to-do)' if u['kind'] == 'task' else '') for u in summary['upcoming'][:15]]
        label = QLabel('<br>'.join(rows))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        lay.addWidget(label)
        buttons = QDialogButtonBox()
        cal = buttons.addButton('Open the calendar', QDialogButtonBox.ButtonRole.ActionRole)
        todo = buttons.addButton('Open the to-do list', QDialogButtonBox.ButtonRole.ActionRole)
        close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        cal.clicked.connect(lambda: (self.openCalendar.emit(), self.accept()))
        todo.clicked.connect(lambda: (self.openTodo.emit(), self.accept()))
        close.clicked.connect(self.accept)
        lay.addWidget(buttons)
        self.resize(460, 360)
