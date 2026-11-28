"""Shared widgets of the hub: request cards, the composer, Markdown rendering, monitor strip, usage list."""
from __future__ import annotations

import html
import re
from collections import deque

from PySide6.QtCore import QPointF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTextDocument
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from . import theme

# ------------------------------------------------------------------ icons (SPM Studio line-icon set)
def icon_button(name: str, tip: str, checkable: bool = False, text: str = '', color_token: str | None = None):
    """Flat tool button with a themed line icon (``svg_icons``) and an optional text label."""
    from PySide6.QtCore import QSize
    from .svg_icons import set_icon
    b = QToolButton()
    b.setObjectName('hubIcon')
    b.setToolTip(tip)
    b.setAccessibleName(tip.split('(')[0].strip())
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setIconSize(QSize(18, 18))
    set_icon(b, name, color_token)
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    else:
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


# ------------------------------------------------------------------ markdown
_MATH = re.compile(r'(\$\$.+?\$\$|\\\[.+?\\\]|(?<![\\$])\$[^$\n]+?\$)', re.S)


def md_html(text: str) -> str:
    """Markdown → HTML (Qt's CommonMark: headings, lists, tables, code). LaTeX is kept readable as TeX
    in monospace (Qt has no math renderer); nothing is dropped."""
    def keep_math(m):
        return '`' + m.group(0).replace('`', "'") + '`'
    doc = QTextDocument()
    doc.setMarkdown(_MATH.sub(keep_math, text or ''))
    out = doc.toHtml()
    start = out.find('<body')
    start = out.find('>', start) + 1 if start >= 0 else 0
    end = out.rfind('</body>')
    return out[start:end if end > 0 else None]


def code_blocks(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'```[^\n]*\n(.*?)```', text or '', re.S)]


# ------------------------------------------------------------------ cards
class Card(QFrame):
    """A request shown above the message box. ``choices``: [(label, keys, value, primary)]. Keys work while
    the card has focus (Y / A / N, Enter, Esc …); Alt+letter works anywhere in the panel."""
    chosen = Signal(str)

    def __init__(self, kind: str, title: str, detail: str, choices, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName('hubCard')
        self.setProperty('kind', kind)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = QLabel(f'<b>{html.escape(title)}</b>')
        head.setWordWrap(True)
        lay.addWidget(head)
        if detail:
            body = QLabel(html.escape(detail[:1500]).replace('\n', '<br>'))
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if kind == 'approval':
                body.setStyleSheet('font-family: monospace;')
            lay.addWidget(body)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.keys = {}
        self.buttons = {}
        for label, keys, value, primary in choices:
            b = QPushButton(label)
            if primary:
                b.setObjectName('hubSend')
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, v=value: self.choose(v))
            row.addWidget(b)
            self.buttons[value] = b
            for k in keys:
                self.keys[k] = value
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel(' · '.join(f'{"/".join(keys)} {label.replace("&", "")}' for label, keys, _v, _p in choices))
        hint.setObjectName('hubHint')
        hint.setWordWrap(True)
        lay.addWidget(hint)

    def keyPressEvent(self, event):
        name = {Qt.Key.Key_Return: 'Enter', Qt.Key.Key_Enter: 'Enter', Qt.Key.Key_Escape: 'Esc'}.get(
            event.key(), event.text().upper())
        if name in self.keys:
            self.choose(self.keys[name])
            return
        super().keyPressEvent(event)

    def choose(self, value):
        self.chosen.emit(value)


# ------------------------------------------------------------------ composer
class ChatInput(QPlainTextEdit):
    send = Signal()
    files = Signal(list)
    escape = Signal()

    def __init__(self, enter_sends=True, parent=None):
        super().__init__(parent)
        self.enter_sends = enter_sends
        self.setAcceptDrops(True)
        self.textChanged.connect(self._grow)

    def _grow(self):
        lines = max(1, min(10, int(self.document().size().height())))
        h = self.fontMetrics().lineSpacing() * lines + 16
        self.setFixedHeight(max(44, min(220, h)))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ControlModifier or \
                    (self.enter_sends and not mods & (Qt.KeyboardModifier.ShiftModifier |
                                                      Qt.KeyboardModifier.AltModifier)):
                self.send.emit()
                return
        if event.key() == Qt.Key.Key_Escape:
            self.escape.emit()
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class Composer(QFrame):
    """Rounded message box: text, then a row with attach · context · mic · brainstorm · model · send/stop."""
    sendRequested = Signal()
    stopRequested = Signal()

    def __init__(self, enter_sends=True, parent=None):
        super().__init__(parent)
        self.setObjectName('hubComposer')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 8, 6)
        lay.setSpacing(4)
        self.attachments = QLabel('')
        self.attachments.setObjectName('hubHint')
        self.attachments.setWordWrap(True)
        self.attachments.hide()
        lay.addWidget(self.attachments)
        self.input = ChatInput(enter_sends)
        self.input.setPlaceholderText('Message  ·  Enter to send, Shift+Enter for a new line')
        self.input.setFixedHeight(44)
        lay.addWidget(self.input)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.attach = icon_button('attach', 'Attach files (or drop them on the message box)')
        self.context = icon_button('scan', 'Attach context from the application (e.g. the active scan)')
        self.mic = icon_button('mic', 'Voice input: click to record, click again to stop (Esc cancels; hold F11 '
                                      'to talk). The text is inserted for editing, never sent automatically.',
                               checkable=True)
        self.brainstorm = icon_button('brainstorm', 'Brainstorming mode: refine the idea with an economical model; '
                                                    'no files, commands or agents run (Ctrl+Shift+B)', checkable=True)
        self.voice_label = QLabel('')
        self.voice_label.setObjectName('hubHint')
        self.voice_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.model = QComboBox()
        self.model.setToolTip('Model for this chat (Ctrl+Shift+M). Auto chooses by task size, routing profile and '
                              'free capacity.')
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setMinimumContentsLength(10)
        self.route = QLabel('')
        self.route.setObjectName('hubMeta')
        self.route.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.budget = QLabel('')
        self.budget.setObjectName('hubMeta')
        self.stop = icon_button('stop', 'Stop (Ctrl+.)')
        self.stop.hide()
        self.send = QPushButton()
        self.send.setObjectName('hubSend')
        from PySide6.QtCore import QSize
        from .svg_icons import set_icon
        set_icon(self.send, 'send', 'accent_fg')
        self.send.setIconSize(QSize(16, 16))
        self.send.setToolTip('Send (Enter)')
        self.send.setFixedWidth(40)
        for w in (self.attach, self.context, self.mic, self.brainstorm, self.voice_label):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.budget)
        row.addWidget(self.route)
        row.addWidget(self.model)
        row.addWidget(self.stop)
        row.addWidget(self.send)
        lay.addLayout(row)
        self.send.clicked.connect(self.sendRequested.emit)
        self.input.send.connect(self.sendRequested.emit)
        self.stop.clicked.connect(self.stopRequested.emit)

    def set_busy(self, busy: bool):
        self.stop.setVisible(busy)
        self.send.setVisible(not busy)

    def set_flag(self, name: str, on: bool):
        self.setProperty(name, 'true' if on else 'false')
        self.style().unpolish(self)
        self.style().polish(self)

    def compact(self, narrow: bool):
        """Narrow embedded panel: hide secondary controls."""
        self.route.setVisible(not narrow)
        self.budget.setVisible(not narrow)
        self.context.setVisible(not narrow)
        self.model.setMinimumContentsLength(6 if narrow else 10)


# ------------------------------------------------------------------ monitor
class Sparkline(QWidget):
    def __init__(self, color_key='hub_graph_1', maximum=100.0, parent=None):
        super().__init__(parent)
        self.values = deque(maxlen=90)
        self.color_key = color_key
        self.maximum = maximum
        self.setMinimumSize(60, 18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(90, 20)

    def add(self, value):
        self.values.append(value)
        self.update()

    def paintEvent(self, _event):
        vals = [v for v in self.values if v is not None]
        if len(vals) < 2:
            return
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        top = max(self.maximum or 0, max(vals)) or 1
        path = QPainterPath()
        n = len(self.values)
        first = True
        for i, v in enumerate(self.values):
            if v is None:
                continue
            pt = QPointF(i * (w - 2) / max(1, n - 1) + 1, h - 2 - (h - 4) * float(v) / top)
            if first:
                path.moveTo(pt)
                first = False
            else:
                path.lineTo(pt)
        p.setPen(QPen(QColor(str(t.get(self.color_key, '#4C8DF6'))), 1.6))
        p.drawPath(path)
        p.end()


class _Sampler(QThread):
    sampled = Signal(dict)

    def __init__(self, interval_ms, base, parent=None):
        super().__init__(parent)
        self.interval = interval_ms
        self.base = base
        self.alive = True

    def run(self):
        from .. import monitor
        while self.alive:
            try:
                self.sampled.emit(monitor.sample(self.base))
            except Exception:
                pass
            for _ in range(max(1, self.interval // 100)):
                if not self.alive:
                    return
                self.msleep(100)


class MonitorStrip(QFrame):
    """Compact local inference monitor: shown while a local model runs or is loaded. Measured values only."""

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setObjectName('hubStrip')
        self.sampler = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)
        self.model_label = QLabel('')
        self.model_label.setObjectName('hubMeta')
        self.speed = QLabel('')
        self.speed.setObjectName('hubMeta')
        self.speed.setToolTip('Tokens per second and time to first token of the last local reply, as counted '
                              'by Ollama')
        self.gpu_label = QLabel('')
        self.gpu_label.setObjectName('hubMeta')
        self.gpu_spark = Sparkline('hub_graph_1')
        self.cpu_label = QLabel('')
        self.cpu_label.setObjectName('hubMeta')
        self.cpu_spark = Sparkline('hub_graph_2')
        self.mem_label = QLabel('')
        self.mem_label.setObjectName('hubMeta')
        for w in (self.model_label, self.speed, self.gpu_label, self.gpu_spark, self.cpu_label, self.cpu_spark,
                  self.mem_label):
            lay.addWidget(w)
        self.setToolTip('Host-wide measurements of this computer (not of a remote server). Missing values are '
                        'not exposed by this system.')
        core.localStats.connect(self._stats)
        core.stateChanged.connect(lambda *_: self.refresh())
        core.settingsChanged.connect(self.refresh)
        core.backendsChanged.connect(self.refresh)
        self.hide()
        self._loaded = False
        self.refresh()

    def _local_active(self) -> bool:
        return any(r.busy and (r.backend_info or {}).get('group') == 'local' for r in self.core.runs.values())

    def refresh(self):
        enabled = bool(self.core.conf.get('monitor', True))
        want = enabled and (self._local_active() or self._loaded)
        has_local = any(b.get('group') == 'local' for b in self.core.backends)
        if enabled and has_local and self.sampler is None:
            self.sampler = _Sampler(int(self.core.conf.get('monitor_interval_ms', 1000)),
                                    (self.core.ai_conf or {}).get('judge_url') or 'http://127.0.0.1:11434', self)
            self.sampler.sampled.connect(self._sample)
            from PySide6.QtWidgets import QApplication
            QApplication.instance().aboutToQuit.connect(self.stop)
            self.sampler.start()
        elif (not enabled or not has_local) and self.sampler is not None:
            self.stop()
        self.setVisible(want)

    def _stats(self, s):
        parts = []
        if s.get('tokens_per_s'):
            parts.append(f"{s['tokens_per_s']} tok/s")
        if s.get('ttft_s') is not None:
            parts.append(f"first token {s['ttft_s']} s")
        self.speed.setText(' · '.join(parts))

    def _sample(self, s):
        loaded = s.get('loaded') or []
        self._loaded = bool(loaded)
        if loaded:
            m = loaded[0]
            vram = m.get('size_vram') or 0
            size = m.get('size') or 0
            where = 'GPU' if size and vram >= size * 0.9 else ('GPU+CPU' if vram else 'CPU')
            self.model_label.setText(f"{m['name']} · {where}")
        else:
            self.model_label.setText('')
        gpus = s.get('gpus') or []
        if gpus:
            g = gpus[0]
            bits = []
            if g.get('util') is not None:
                bits.append(f"GPU {g['util']:.0f}%")
            if g.get('vram_used') is not None and g.get('vram_total'):
                bits.append(f"VRAM {g['vram_used'] / 2 ** 30:.1f}/{g['vram_total'] / 2 ** 30:.0f} GB")
            if g.get('temp') is not None:
                bits.append(f"{g['temp']:.0f} °C")
            if g.get('power_w') is not None:
                bits.append(f"{g['power_w']:.0f} W")
            self.gpu_label.setText(' · '.join(bits))
            self.gpu_spark.add(g.get('util'))
            self.gpu_spark.show()
        else:
            self.gpu_label.setText(s.get('gpu_note', ''))
            self.gpu_spark.hide()
        cpu = s.get('cpu')
        self.cpu_label.setText((f'CPU {cpu:.0f}%' if cpu is not None else '') +
                               (f" · {s['cpu_temp']:.0f} °C" if s.get('cpu_temp') is not None else ''))
        self.cpu_spark.add(cpu)
        if s.get('ram_total'):
            self.mem_label.setText(f"RAM {s['ram_used'] / 2 ** 30:.1f}/{s['ram_total'] / 2 ** 30:.0f} GB")
        self.setVisible(bool(self.core.conf.get('monitor', True)) and (self._local_active() or self._loaded))

    def stop(self):
        if self.sampler is not None:
            self.sampler.alive = False
            self.sampler.wait(1500)
            self.sampler = None

    def hideEvent(self, event):
        super().hideEvent(event)

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)


# ------------------------------------------------------------------ usage (sidebar)
class UsageBox(QFrame):
    """Collapsible sidebar section: locally observed usage per account; quotas only when a provider exposes
    them (none of the current subscription CLIs does), otherwise “Not available from provider”."""

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)
        self.toggle = icon_button('chevron-down', 'Usage observed in Agent Hub', checkable=True, text='Usage')
        from .svg_icons import set_icon
        set_icon(self.toggle, 'usage')
        self.toggle.setToolTip('Usage observed in Agent Hub (this computer). Subscription quotas and reset times '
                               'are not available from the providers.')
        self.body = QLabel('')
        self.body.setObjectName('hubMeta')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.hide()
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)
        self.toggle.toggled.connect(self._toggle)
        core.usageChanged.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.refresh)

    def _toggle(self, on):
        from .svg_icons import set_icon
        set_icon(self.toggle, 'chevron-up' if on else 'usage')
        self.body.setVisible(on)
        (self._timer.start if on else self._timer.stop)()
        if on:
            self.refresh()

    def refresh(self):
        if not self.body.isVisible():
            return
        from ..usage import human
        from ..scheduler import GROUP_LABELS
        rows = self.core.ledger.summary()
        if not rows:
            self.body.setText('No usage recorded yet.')
            return
        lines = []
        for r in rows[:6]:
            est = ' (partly estimated)' if r['estimated'] else ''
            lines.append(f"<b>{html.escape(GROUP_LABELS.get(r['group'], r['group']))}</b> · "
                         f"{html.escape(str(r['account']))}<br>5 h: {human(r['tokens_5h'])} tokens, "
                         f"{r['turns_5h']} replies · 7 d: {human(r['tokens_week'])}{est}"
                         + (f"<br>cost reported: ${r['cost_usd_week']:.2f}" if r['cost_usd_week'] else '') +
                         f"<br><i>quota: {r['quota_reason']}</i>")
        self.body.setText('<br>'.join(lines))
