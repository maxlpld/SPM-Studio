"""Event editor: title, all-day, start / end, time zone, recurrence (daily, weekly, monthly, yearly, custom with
exceptions), location, description, colour, calendar, several reminders."""
from __future__ import annotations

from ..theme import scale_font

import datetime as dt

from PySide6.QtCore import QDate, QDateTime, QTime, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from ...organizer import rrule
from ...organizer.calendar import PALETTE, iso, local_zone_name, parse_time
from .. import theme
from ..svg_icons import icon, set_icon

COMMON_ZONES = ['', 'UTC', 'Europe/London', 'Europe/Paris', 'Europe/Zurich', 'Europe/Berlin', 'Europe/Rome',
                'Europe/Madrid', 'Europe/Amsterdam', 'Europe/Stockholm', 'Europe/Athens', 'Europe/Moscow',
                'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Sao_Paulo',
                'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Kolkata', 'Asia/Singapore', 'Asia/Dubai', 'Australia/Sydney',
                'Pacific/Auckland', 'Africa/Johannesburg']
DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
ORD = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', -1: 'last'}


def repeat_choices(day: dt.date) -> list[tuple[str, str]]:
    n = (day.day - 1) // 7 + 1
    last = (day + dt.timedelta(days=7)).month != day.month
    nth = -1 if last and n >= 4 else n
    wd = DAY_NAMES[day.weekday()]
    return [('Does not repeat', ''), ('Daily', 'FREQ=DAILY'),
            (f'Weekly on {wd}', f'FREQ=WEEKLY;BYDAY={DAYS[day.weekday()]}'),
            ('Every weekday (Monday to Friday)', 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'),
            (f'Monthly on day {day.day}', f'FREQ=MONTHLY;BYMONTHDAY={day.day}'),
            (f'Monthly on the {ORD.get(nth, str(nth))} {wd}', f'FREQ=MONTHLY;BYDAY={nth}{DAYS[day.weekday()]}'),
            (f'Annually on {day:%d %B}'.replace(' 0', ' '), 'FREQ=YEARLY'), ('Custom…', '__custom__')]


class CustomRepeat(QDialog):
    def __init__(self, text: str, start: dt.date, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Custom recurrence')
        try:
            r = rrule.parse(text) if text else {'freq': 'WEEKLY', 'interval': 1, 'count': None, 'until': None,
                                                'byday': [(0, start.weekday())], 'bymonthday': [], 'bymonth': [],
                                                'bysetpos': [], 'wkst': 'MO'}
        except rrule.RRuleError:
            r = rrule.parse('FREQ=WEEKLY')
        self.rule = r
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('Repeat every'))
        self.interval = QSpinBox()
        self.interval.setRange(1, 99)
        self.interval.setValue(r['interval'])
        self.freq = QComboBox()
        for label, key in (('day(s)', 'DAILY'), ('week(s)', 'WEEKLY'), ('month(s)', 'MONTHLY'), ('year(s)', 'YEARLY')):
            self.freq.addItem(label, key)
        self.freq.setCurrentIndex(max(0, self.freq.findData(r['freq'])))
        row.addWidget(self.interval)
        row.addWidget(self.freq)
        row.addStretch(1)
        lay.addLayout(row)
        self.days_box = QWidget()
        dl = QHBoxLayout(self.days_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(QLabel('On'))
        self.days = []
        chosen = {d for _n, d in r['byday']} or {start.weekday()}
        for i, name in enumerate(['M', 'T', 'W', 'T', 'F', 'S', 'S']):
            b = QToolButton()
            b.setText(name)
            b.setCheckable(True)
            b.setChecked(i in chosen)
            b.setToolTip(DAY_NAMES[i])
            b.setFixedSize(30, 30)
            dl.addWidget(b)
            self.days.append(b)
        dl.addStretch(1)
        lay.addWidget(self.days_box)
        self.monthly = QComboBox()
        n = (start.day - 1) // 7 + 1
        self.monthly.addItem(f'Monthly on day {start.day}', f'BYMONTHDAY={start.day}')
        self.monthly.addItem(f'Monthly on the {ORD.get(n, str(n))} {DAY_NAMES[start.weekday()]}',
                             f'BYDAY={n}{DAYS[start.weekday()]}')
        self.monthly.addItem(f'Monthly on the last {DAY_NAMES[start.weekday()]}', f'BYDAY=-1{DAYS[start.weekday()]}')
        if r['byday'] and r['byday'][0][0]:
            self.monthly.setCurrentIndex(2 if r['byday'][0][0] < 0 else 1)
        lay.addWidget(self.monthly)
        lay.addWidget(QLabel('Ends'))
        self.never = QRadioButton('Never')
        self.on = QRadioButton('On')
        self.after = QRadioButton('After')
        self.until = QDateEdit(QDate(start.year, start.month, start.day).addMonths(3))
        self.until.setCalendarPopup(True)
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setValue(r['count'] or 10)
        self.count.setSuffix(' occurrences')
        g = QGridLayout()
        g.addWidget(self.never, 0, 0)
        g.addWidget(self.on, 1, 0)
        g.addWidget(self.until, 1, 1)
        g.addWidget(self.after, 2, 0)
        g.addWidget(self.count, 2, 1)
        lay.addLayout(g)
        if r['count']:
            self.after.setChecked(True)
        elif r['until']:
            self.on.setChecked(True)
            u = r['until'] if not isinstance(r['until'], dt.datetime) else r['until'].date()
            self.until.setDate(QDate(u.year, u.month, u.day))
        else:
            self.never.setChecked(True)
        self.freq.currentIndexChanged.connect(self._mode)
        self._mode()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _mode(self):
        f = self.freq.currentData()
        self.days_box.setVisible(f == 'WEEKLY')
        self.monthly.setVisible(f == 'MONTHLY')

    def text(self) -> str:
        f = self.freq.currentData()
        parts = [f'FREQ={f}']
        if self.interval.value() > 1:
            parts.append(f'INTERVAL={self.interval.value()}')
        if f == 'WEEKLY':
            days = [DAYS[i] for i, b in enumerate(self.days) if b.isChecked()]
            if days:
                parts.append('BYDAY=' + ','.join(days))
        if f == 'MONTHLY':
            parts.append(self.monthly.currentData())
        if self.after.isChecked():
            parts.append(f'COUNT={self.count.value()}')
        elif self.on.isChecked():
            d = self.until.date()
            parts.append(f'UNTIL={d.year():04d}{d.month():02d}{d.day():02d}T235959')
        return ';'.join(parts)


class EventEditor(QDialog):
    """``result_fields`` after Save; ``deleted`` after Delete."""

    def __init__(self, organizer, event: dict | None = None, start=None, end=None, all_day=False, parent=None,
                 calendar_id: str = ''):
        super().__init__(parent)
        self.org = organizer
        self.event = event
        self.deleted = False
        self.result_fields = None
        self.setWindowTitle('Edit event' if event else 'New event')
        self.resize(560, 640)
        ev = dict(event or {})
        s = parse_time(ev['start']) if ev.get('start') else (start or dt.datetime.now().replace(minute=0, second=0,
                                                                                                microsecond=0)
                                                             + dt.timedelta(hours=1))
        e = parse_time(ev['end']) if ev.get('end') else (end or (s + (dt.timedelta(days=1) if all_day else
                                                                       dt.timedelta(hours=1))))
        all_day = ev.get('all_day', all_day)
        lay = QVBoxLayout(self)
        self.title = QLineEdit(ev.get('title', ''))
        self.title.setPlaceholderText('Add title')
        f = self.title.font()
        scale_font(f, 1.35)
        self.title.setFont(f)
        lay.addWidget(self.title)
        form = QFormLayout()
        lay.addLayout(form)
        self.all_day = QCheckBox('All day')
        self.all_day.setChecked(bool(all_day))
        form.addRow('', self.all_day)
        self.start = QDateTimeEdit()
        self.end = QDateTimeEdit()
        for w in (self.start, self.end):
            w.setCalendarPopup(True)
        self._set(self.start, s)
        self._set(self.end, (e - dt.timedelta(days=1)) if all_day and not isinstance(e, dt.datetime) else e)
        form.addRow('Starts', self.start)
        form.addRow('Ends', self.end)
        self.tz = QComboBox()
        self.tz.setEditable(True)
        local = local_zone_name()
        for z in COMMON_ZONES:
            self.tz.addItem(z or f'This computer ({local or "local time"})', z)
        current = ev.get('tz', '')
        if current and self.tz.findData(current) < 0:
            self.tz.addItem(current, current)
        self.tz.setCurrentIndex(max(0, self.tz.findData(current)))
        self.tz.setToolTip('Time zone of the start and end times (shown in this computer\'s zone in the calendar)')
        form.addRow('Time zone', self.tz)
        self.repeat = QComboBox()
        self.custom_rule = ev.get('rrule', '')
        self._fill_repeat(s.date() if isinstance(s, dt.datetime) else s)
        form.addRow('Repeat', self.repeat)
        self.exdates = QListWidget()
        self.exdates.setMaximumHeight(70)
        for x in ev.get('exdates', []):
            self.exdates.addItem(x)
        exrow = QHBoxLayout()
        self.exdate_edit = QDateEdit(QDate.currentDate())
        self.exdate_edit.setCalendarPopup(True)
        add_ex = QPushButton('Skip this date')
        rem_ex = QPushButton('Remove')
        add_ex.clicked.connect(self._add_exception)
        rem_ex.clicked.connect(lambda: [self.exdates.takeItem(self.exdates.row(i)) for i in self.exdates.selectedItems()])
        exrow.addWidget(self.exdate_edit)
        exrow.addWidget(add_ex)
        exrow.addWidget(rem_ex)
        self.ex_box = QWidget()
        exl = QVBoxLayout(self.ex_box)
        exl.setContentsMargins(0, 0, 0, 0)
        exl.addWidget(self.exdates)
        exl.addLayout(exrow)
        form.addRow('Exceptions', self.ex_box)
        self.ex_box.setVisible(bool(self.custom_rule))
        self.location = QLineEdit(ev.get('location', ''))
        self.location.setPlaceholderText('Add location')
        form.addRow('Location', self.location)
        self.calendar = QComboBox()
        for c in organizer.calendar.calendars():
            if c.get('readonly') and c['id'] != ev.get('calendar'):
                continue
            self.calendar.addItem(theme.dot_icon(c['color']), c['name'], c['id'])
        cid = ev.get('calendar') or calendar_id
        self.calendar.setCurrentIndex(max(0, self.calendar.findData(cid)))
        form.addRow('Calendar', self.calendar)
        self.color = QComboBox()
        self.color.addItem('Calendar colour', '')
        for c in PALETTE:
            self.color.addItem(theme.dot_icon(c), c, c)
        self.color.setCurrentIndex(max(0, self.color.findData(ev.get('color', ''))))
        form.addRow('Colour', self.color)
        # reminders
        self.reminders = QListWidget()
        self.reminders.setMaximumHeight(80)
        default = int(organizer_default_reminder(organizer))
        for m in (ev.get('reminders') if event else ([default] if default >= 0 else [])):
            self._add_reminder_item(int(m))
        rrow = QHBoxLayout()
        self.r_value = QSpinBox()
        self.r_value.setRange(0, 999)
        self.r_value.setValue(10)
        self.r_unit = QComboBox()
        for label, mult in (('minutes before', 1), ('hours before', 60), ('days before', 1440), ('weeks before', 10080)):
            self.r_unit.addItem(label, mult)
        add_r = QPushButton()
        set_icon(add_r, 'plus')
        add_r.setToolTip('Add this reminder (notification)')
        add_r.clicked.connect(lambda: self._add_reminder_item(self.r_value.value() * self.r_unit.currentData()))
        rem_r = QPushButton()
        set_icon(rem_r, 'minus')
        rem_r.setToolTip('Remove the selected reminder')
        rem_r.clicked.connect(lambda: [self.reminders.takeItem(self.reminders.row(i))
                                       for i in self.reminders.selectedItems()])
        for w in (self.r_value, self.r_unit, add_r, rem_r):
            rrow.addWidget(w)
        rbox = QWidget()
        rl = QVBoxLayout(rbox)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.reminders)
        rl.addLayout(rrow)
        form.addRow('Notifications', rbox)
        self.description = QPlainTextEdit(ev.get('description', ''))
        self.description.setPlaceholderText('Add description')
        self.description.setMaximumHeight(110)
        form.addRow('Description', self.description)
        if (ev.get('links') or {}).get('todo'):
            form.addRow('', QLabel('Linked to a to-do: editing the title or time updates it as well.'))
        buttons = QDialogButtonBox()
        save = buttons.addButton(QDialogButtonBox.StandardButton.Save)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        if event:
            delete = buttons.addButton('Delete', QDialogButtonBox.ButtonRole.DestructiveRole)
            delete.clicked.connect(self._delete)
        save.clicked.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.all_day.toggled.connect(self._all_day)
        self.repeat.activated.connect(self._repeat_chosen)
        self.start.dateTimeChanged.connect(self._start_moved)
        self._all_day(self.all_day.isChecked())
        self._last_start = self.start.dateTime()
        self.title.setFocus()

    @staticmethod
    def _set(widget, value):
        if isinstance(value, dt.datetime):
            widget.setDateTime(QDateTime(QDate(value.year, value.month, value.day), QTime(value.hour, value.minute)))
        else:
            widget.setDateTime(QDateTime(QDate(value.year, value.month, value.day), QTime(9, 0)))

    @staticmethod
    def _get(widget) -> dt.datetime:
        d = widget.dateTime()
        return dt.datetime(d.date().year(), d.date().month(), d.date().day(), d.time().hour(), d.time().minute())

    def _fill_repeat(self, day: dt.date):
        self.repeat.blockSignals(True)
        self.repeat.clear()
        found = False
        for label, value in repeat_choices(day):
            self.repeat.addItem(label, value)
            if value == self.custom_rule:
                found = True
        if self.custom_rule and not found:
            self.repeat.insertItem(self.repeat.count() - 1, rrule.describe(self.custom_rule), self.custom_rule)
        self.repeat.setCurrentIndex(max(0, self.repeat.findData(self.custom_rule)))
        self.repeat.blockSignals(False)
        self.ex_box.setVisible(bool(self.custom_rule)) if hasattr(self, 'ex_box') else None

    def _repeat_chosen(self, _i):
        value = self.repeat.currentData()
        if value == '__custom__':
            dialog = CustomRepeat(self.custom_rule, self._get(self.start).date(), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.custom_rule = dialog.text()
            self._fill_repeat(self._get(self.start).date())
        else:
            self.custom_rule = value
        self.ex_box.setVisible(bool(self.custom_rule))

    def _start_moved(self, value):
        delta = self._last_start.secsTo(value)
        self.end.setDateTime(self.end.dateTime().addSecs(delta))
        self._last_start = value
        if not self.custom_rule or self.custom_rule in [v for _l, v in repeat_choices(self._get(self.start).date())]:
            pass

    def _all_day(self, on):
        fmt = 'ddd d MMM yyyy' if on else 'ddd d MMM yyyy  HH:mm'
        self.start.setDisplayFormat(fmt)
        self.end.setDisplayFormat(fmt)
        self.tz.setEnabled(not on)

    def _add_exception(self):
        d = self.exdate_edit.date()
        day = dt.date(d.year(), d.month(), d.day())
        s = self._get(self.start)
        value = day.isoformat() if self.all_day.isChecked() else iso(dt.datetime.combine(day, s.time()))
        if not self.exdates.findItems(value, Qt.MatchFlag.MatchExactly):
            self.exdates.addItem(value)

    def _add_reminder_item(self, minutes: int):
        for i in range(self.reminders.count()):
            if self.reminders.item(i).data(Qt.ItemDataRole.UserRole) == minutes:
                return
        if minutes == 0:
            text = 'At the start'
        elif minutes % 10080 == 0:
            text = f'{minutes // 10080} week(s) before'
        elif minutes % 1440 == 0:
            text = f'{minutes // 1440} day(s) before'
        elif minutes % 60 == 0:
            text = f'{minutes // 60} hour(s) before'
        else:
            text = f'{minutes} minutes before'
        item = QListWidgetItem(icon('bell'), text)
        item.setData(Qt.ItemDataRole.UserRole, minutes)
        self.reminders.addItem(item)

    def _save(self):
        s, e = self._get(self.start), self._get(self.end)
        if self.all_day.isChecked():
            start, end = s.date(), e.date() + dt.timedelta(days=1)
            if end <= start:
                end = start + dt.timedelta(days=1)
        else:
            start, end = s, e
            if end <= start:
                QMessageBox.warning(self, 'Event', 'The end must be after the start.')
                return
        if self.custom_rule:
            try:
                rrule.parse(self.custom_rule)
            except rrule.RRuleError as exc:
                QMessageBox.warning(self, 'Repeat', str(exc))
                return
        self.result_fields = {
            'title': self.title.text().strip() or '(no title)', 'all_day': self.all_day.isChecked(),
            'start': iso(start), 'end': iso(end), 'tz': '' if self.all_day.isChecked() else (self.tz.currentData() or
                                                                                            self.tz.currentText()
                                                                                            if 'This computer' not in
                                                                                            self.tz.currentText() else ''),
            'rrule': self.custom_rule, 'exdates': [self.exdates.item(i).text() for i in range(self.exdates.count())],
            'location': self.location.text().strip(), 'description': self.description.toPlainText(),
            'calendar': self.calendar.currentData() or '', 'color': self.color.currentData() or '',
            'reminders': [self.reminders.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.reminders.count())]}
        self.accept()

    def _delete(self):
        self.deleted = True
        self.accept()


def organizer_default_reminder(organizer) -> int:
    try:
        from ... import settings as hubsettings
        from ...host import current
        return int(hubsettings.load(current().data_dir()).get('calendar_default_reminder', 10))
    except Exception:
        return 10
