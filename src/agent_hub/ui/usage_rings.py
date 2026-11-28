"""Usage indicators: one small ring per connected cloud AI account (Claude subscription, ChatGPT / Codex, Pi
accounts, each API-key provider), in that provider's colour, always visible in the sidebar.

* The ring shows the share of the **current limit window** used, as reported by the provider
  (``limits.Limits``), with the time to reset beside it. When the provider reports nothing, the ring is an empty
  dashed track labelled “n/a” — no number is invented (an estimate from locally observed usage is shown only in
  the details, labelled as such).
* A click opens the details: current window, weekly window when the provider has one, reset times, tokens and
  cost observed in Agent Hub, and where each figure comes from.
"""
from __future__ import annotations

from .theme import scale_font

import html
import time

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from . import theme

LABELS = {'anthropic': 'Claude', 'openai': 'ChatGPT', 'pi': 'Pi', 'api': 'API'}
LONG = {'anthropic': 'Claude subscription (Claude Code)', 'openai': 'ChatGPT subscription (Codex)',
        'pi': 'Pi accounts', 'api': 'API keys'}
PREFERRED = ('five_hour', 'primary', 'tokens', 'requests', 'seven_day', 'secondary')
STALE_S = 15 * 60                         # per-minute API windows older than this are not shown as current


def accounts(core) -> list[dict]:
    """The connected cloud accounts, one entry per indicator: {'key', 'group', 'provider', 'label', 'long'}."""
    out, seen = [], set()
    for b in core.backends:
        group = b.get('group', '')
        if group == 'local':
            continue
        if group == 'api':
            provider = (b.get('connection') or {}).get('provider') or b.get('provider') or 'custom'
            key = 'api:' + provider
            label = provider.capitalize() if provider != 'openrouter' else 'OpenRouter'
            long_ = f'{label} API key'
        else:
            provider, key = '', group
            label, long_ = LABELS.get(group, group), LONG.get(group, group)
        if key in seen:
            continue
        seen.add(key)
        out.append({'key': key, 'group': group, 'provider': provider, 'label': label, 'long': long_})
    return out


def current_window(limits: dict | None, now: float | None = None):
    """(name, window) to draw: the 5-hour window when reported, else another fresh one; None when none."""
    if not limits:
        return None
    now = now or time.time()
    wins = limits.get('windows') or {}
    for name in PREFERRED:
        w = wins.get(name)
        if not w or w.get('used') is None:
            continue
        if w.get('window_s', 0) <= 120 and now - float(w.get('observed') or 0) > STALE_S:
            continue
        return name, w
    return None


class Ring(QWidget):
    """A small ring: colour arc = share used (0–100 %), dashed track = not available."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.fraction = None
        self.warn = False
        self.setFixedSize(QSize(22, 22))

    def set_value(self, fraction, warn=False):
        self.fraction = None if fraction is None else max(0.0, float(fraction))
        self.warn = warn
        self.update()

    def paintEvent(self, _e):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)
        track = QPen(QColor(str(t.get('border', '#E2DDD3'))), 3)
        if self.fraction is None:
            track.setStyle(Qt.PenStyle.DotLine)
            track.setColor(QColor(self.color))
            track.setWidthF(2)
        p.setPen(track)
        p.drawEllipse(rect)
        if self.fraction is not None:
            pen = QPen(QColor(str(t.get('error', '#C94A3F'))) if self.warn else QColor(self.color), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            span = int(-min(1.0, self.fraction) * 360 * 16)
            if span:
                p.drawArc(rect, 90 * 16, span)
        p.end()


class Indicator(QFrame):
    """Ring + short text (‘Claude 64% · 2h11’); a click (or Enter / Space) opens the details."""
    opened = Signal(str)

    def __init__(self, account: dict, parent=None):
        super().__init__(parent)
        self.account = account
        self.setObjectName('hubUsageIndicator')
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.color = theme.provider_color(account['group'], account['provider'])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 6, 2)
        lay.setSpacing(4)
        self.ring = Ring(self.color)
        self.text = QLabel('')                     # 'Claude 64%'
        self.reset = QLabel('')                    # '2h 11m' (muted, second line)
        self.reset.setObjectName('hubMeta')
        f = QFont(self.text.font())
        scale_font(f, 0.86, 7.0)
        self.text.setFont(f)
        small = QFont(f)
        small = scale_font(QFont(f), 0.9, 6.5)
        self.reset.setFont(small)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.text)
        col.addWidget(self.reset)
        lay.addWidget(self.ring)
        lay.addLayout(col, 1)
        self.setAccessibleName(account['long'] + ' usage')

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.opened.emit(self.account['key'])

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.opened.emit(self.account['key'])
        else:
            super().keyPressEvent(e)

    def refresh(self, limits: dict | None, now: float | None = None):
        from ..limits import human_reset
        found = current_window(limits, now)
        name = self.account['label']
        if found is None:
            self.ring.set_value(None)
            self.text.setText(name)
            self.reset.setText('limit n/a')
            self.setToolTip(f"{self.account['long']}: limit not available from provider. Click for the usage "
                            'observed in Agent Hub.')
            return
        key, w = found
        if w.get('reset'):
            self.ring.set_value(0.0)
            self.text.setText(name)
            self.reset.setText('window reset')
            self.setToolTip(f"{self.account['long']}: the {w['label'].lower()} has reset since it was last reported.")
            return
        pct = round(100 * float(w['used']))
        left = (w.get('resets_at') or 0) - (now or time.time())
        short = ('reset not reported' if not w.get('resets_at') else
                 f'resets in {int(left // 86400)}d {int(left % 86400 // 3600)}h' if left >= 86400 else
                 f'resets in {int(left // 3600)}h {int(left % 3600 // 60):02d}m' if left >= 3600 else
                 f'resets in {max(1, int(left // 60))}m')
        self.ring.set_value(w['used'], warn=pct >= 90 or w.get('status') == 'rejected')
        self.text.setText(f'{name} {pct}%')
        self.reset.setText(short)
        self.setToolTip(f"{self.account['long']}: {pct}% of the {w['label'].lower()} used, "
                        f"{human_reset(w.get('resets_at'), now)} ({limits.get('source', 'reported by provider')}).")


class UsagePopover(QFrame):
    """Details of one account (opened from its ring)."""

    def __init__(self, core, account: dict, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName('hubPopover')
        self.core, self.account = core, account
        t = theme.tokens()
        self.setStyleSheet(f"#hubPopover {{ background: {t['surface']}; border: 1px solid {t['border']}; "
                           f"border-radius: 10px; }} QLabel {{ color: {t['text']}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        head = QHBoxLayout()
        ring = Ring(theme.provider_color(account['group'], account['provider']))
        head.addWidget(ring)
        title = QLabel(f"<b>{html.escape(account['long'])}</b>")
        head.addWidget(title, 1)
        lay.addLayout(head)
        self.body = QLabel('')
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setWordWrap(True)
        self.body.setOpenExternalLinks(True)
        self.body.setMinimumWidth(320)
        self.body.setMaximumWidth(380)
        lay.addWidget(self.body)
        self.ring = ring
        self.fill()

    def fill(self, now: float | None = None):
        from ..limits import human_reset
        from ..usage import human
        now = now or time.time()
        t = theme.tokens()
        muted = t.get('muted', '#6F6A62')
        limits = self.core.limits.get(self.account['key'], now)
        found = current_window(limits, now)
        self.ring.set_value(found[1]['used'] if found and not found[1].get('reset') else None)
        rows = []
        if limits and limits.get('windows'):
            for name, w in sorted(limits['windows'].items(), key=lambda kv: PREFERRED.index(kv[0])
                                  if kv[0] in PREFERRED else 99):
                if w.get('used') is None:
                    continue
                observed = time.strftime('%H:%M', time.localtime(w.get('observed') or now))
                if w.get('reset'):
                    value = 'has reset since last report'
                else:
                    value = f"<b>{round(100 * float(w['used']))}% used</b> · {human_reset(w.get('resets_at'), now)}"
                    if w.get('limit'):
                        value += f" · {human(int(w.get('remaining') or 0))} of {human(int(w['limit']))} left"
                    if w.get('status') in ('allowed_warning', 'rejected'):
                        value += ' · ' + ('limit reached' if w['status'] == 'rejected' else 'near the limit')
                rows.append(f"{html.escape(w['label'])}: {value} "
                            f"<span style='color:{muted}'>(as of {observed})</span>")
            rows.append(f"<span style='color:{muted}'>Source: {html.escape(limits.get('source', 'reported by '
                                                                                        'provider'))}</span>")
        else:
            rows.append('Current window: <b>not available from provider</b>')
            rows.append('Weekly: <b>not available from provider</b>')
            hint = {'anthropic': 'Claude Code reports its 5-hour and weekly windows during a reply; they appear '
                                 'here after the next Claude reply in Agent Hub (API-key sessions have none).',
                    'openai': 'Codex writes its limits to its session log; they appear after the next Codex reply.',
                    'pi': 'Pi does not expose limits.'}.get(self.account['group'],
                                                            'Per-minute limits appear after the next reply when '
                                                            'the API sends rate-limit headers.')
            rows.append(f"<span style='color:{muted}'>{html.escape(hint)}</span>")
        # locally observed usage
        summary = [r for r in self.core.ledger.summary(now) if self._mine(r)]
        tokens5 = sum(r['tokens_5h'] for r in summary)
        tokensw = sum(r['tokens_week'] for r in summary)
        turns5 = sum(r['turns_5h'] for r in summary)
        cost = [r['cost_usd_week'] for r in summary if r['cost_usd_week'] is not None]
        estimated = any(r['estimated'] for r in summary)
        models = sorted({m for r in summary for m in r['models']})
        rows.append('<hr>')
        rows.append(f"<b>Observed in Agent Hub</b> (this computer){' — partly estimated from text length' if estimated else ''}")
        rows.append(f"Last 5 h: {human(tokens5)} tokens, {turns5} replies · last 7 days: {human(tokensw)} tokens")
        rows.append('Cost reported: ' + (f'${sum(cost):.2f} (7 days)' if cost else
                                         'not reported (subscriptions are not billed per token)'))
        if models:
            rows.append(f"<span style='color:{muted}'>Models: {html.escape(', '.join(models[:6]))}</span>")
        from ..usage import OFFICIAL_PAGES
        page = OFFICIAL_PAGES.get(self.account['key']) or {'anthropic': 'https://claude.ai/settings/usage',
                                                            'openai': 'https://chatgpt.com/codex/settings/usage'}.get(
            self.account['group'], '')
        if page:
            rows.append(f"<a href='{page}'>The provider's own usage page</a>")
        self.body.setText('<br>'.join(rows))
        self.adjustSize()

    def _mine(self, row: dict) -> bool:
        if self.account['group'] == 'api':
            return row['group'] == 'api' and (row['account'] or '').lower().startswith(self.account['provider'])
        return row['group'] == self.account['group']


class UsageRings(QFrame):
    """Row of indicators at the bottom of the sidebar (wraps onto two lines when needed)."""

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setObjectName('hubUsageRings')
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(4, 4, 4, 2)
        self.lay.setSpacing(0)
        self.rows = []
        self.indicators: dict[str, Indicator] = {}
        self.popover = None
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        core.backendsChanged.connect(self.rebuild)
        core.limitsChanged.connect(self.refresh)
        core.usageChanged.connect(self.refresh)
        core.settingsChanged.connect(self._visibility)
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)                  # reset countdowns; no request is made
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.rebuild()

    def _visibility(self):
        self.setVisible(bool(self.core.conf.get('usage_rings', True)) and bool(self.indicators))

    def rebuild(self):
        for ind in self.indicators.values():
            ind.setParent(None)
            ind.deleteLater()
        self.indicators.clear()
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.layout():
                while item.layout().count():
                    item.layout().takeAt(0)
        found = accounts(self.core)
        row = None
        for n, acc in enumerate(found):
            if n % 2 == 0:
                row = QHBoxLayout()
                row.setSpacing(2)
                row.setContentsMargins(0, 0, 0, 0)
                self.lay.addLayout(row)
            ind = Indicator(acc, self)
            ind.opened.connect(self.open_details)
            row.addWidget(ind, 1)
            self.indicators[acc['key']] = ind
        if row is not None and len(found) % 2:
            row.addStretch(1)
        self.refresh()
        self._visibility()

    def refresh(self):
        now = time.time()
        for key, ind in self.indicators.items():
            try:
                ind.refresh(self.core.limits.get(key, now), now)
            except RuntimeError:
                continue
        if self.popover is not None and self.popover.isVisible():
            self.popover.fill(now)

    def open_details(self, key: str):
        ind = self.indicators.get(key)
        if ind is None:
            return
        self.popover = UsagePopover(self.core, ind.account, self.window())
        pos = ind.mapToGlobal(QPoint(0, 0))
        self.popover.adjustSize()
        self.popover.move(pos.x(), max(0, pos.y() - self.popover.height() - 6))
        self.popover.show()
