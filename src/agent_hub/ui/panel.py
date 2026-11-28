"""One chat panel: conversation, request cards (approval, sorting, busy model, budget), composer.

A panel only *shows* a ChatRun of the engine: moving it to another window (detach / re-dock) or closing it
never stops the agent, and the draft text and attachments live in the widget (and are saved with the chat).
"""
from __future__ import annotations

import html
import time
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QComboBox, QSizePolicy,
                               QTextBrowser, QVBoxLayout)

from .. import brainstorm, sorting
from ..host import current as current_host
from ..icons import state_color, state_text
from . import theme
from .widgets import Card, Composer, code_blocks, icon_button, md_html

MAX_ATTACH = 200_000


def scheduler_find(backends, key):
    from ..scheduler import find
    return find(backends, key) if key else None


def _display(text: str) -> str:
    """Reply text as shown: tool request blocks become one short line; the host may hide its own tags."""
    from ..organizer import tools
    from ..host import current
    found = tools.parse(text)
    shown = tools.strip(text)
    if found:
        shown += '\n\n*Requested: ' + ', '.join(str(r.get('tool')) for r in found) + '*'
    try:
        shown = current().display_text(shown)
    except Exception:
        pass
    return shown


class PromptDialog(QDialog):
    """The generated final prompt: edit, copy, save as Markdown, or go on to Start execution."""

    def __init__(self, text: str, backends: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle('Final prompt — review and edit')
        self.resize(760, 680)
        self.execute = False
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('Review and edit the prompt. Nothing runs until you choose Start execution.'))
        self.edit = QPlainTextEdit(text)
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        copy = QPushButton('Copy')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.edit.toPlainText()))
        save = QPushButton('Save as Markdown…')
        save.clicked.connect(self._save)
        row.addWidget(copy)
        row.addWidget(save)
        row.addStretch(1)
        row.addWidget(QLabel('Run with'))
        self.model = QComboBox()
        self.model.addItem('Auto (routing profile)', 'auto')
        for b in backends:
            self.model.addItem(b['label'] + ('' if b['tools'] else '  (chat only)'), b['key'])
        row.addWidget(self.model)
        go = QPushButton('Start execution…')
        go.setObjectName('hubSend')
        go.clicked.connect(self._go)
        row.addWidget(go)
        lay.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save prompt', str(Path.home() / 'final_prompt.md'),
                                              'Markdown (*.md)')
        if path:
            Path(path).write_text(self.edit.toPlainText(), encoding='utf8')

    def _go(self):
        self.execute = True
        self.accept()


class ChatPanel(QFrame):
    focused = Signal(str)
    closeRequested = Signal(str)
    stateChanged = Signal(str, str)
    executionStarted = Signal(str)

    def __init__(self, core, chat_id: str, parent=None):
        super().__init__(parent)
        self.core = core
        self.chat_id = chat_id
        self.run = core.run_for(chat_id)
        self.setObjectName('hubPanel')
        self._cache = {}
        self.cards: dict[str, Card] = {}
        self.attached: list[tuple[str, str]] = []
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(90)
        self._render_timer.timeout.connect(self.render)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 10)
        lay.setSpacing(6)
        # header
        head = QHBoxLayout()
        head.setSpacing(6)
        self.dot = QLabel()
        self.dot.setFixedSize(16, 16)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        self.mode_badge = QLabel('BRAINSTORMING')
        self.mode_badge.setObjectName('hubModeBadge')
        self.mode_badge.setToolTip('Economical model, no execution: files, commands, agents, pushes are blocked')
        self.mode_badge.hide()
        self.project_button = icon_button('folder', 'Project of this chat (Ctrl+M to move it)', text='No project')
        self.project_button.setPopupMode(self.project_button.ToolButtonPopupMode.InstantPopup)
        self.more = icon_button('more', 'Chat actions: copy, regenerate, edit, final prompt…')
        self.more.setPopupMode(self.more.ToolButtonPopupMode.InstantPopup)
        self.close_button = icon_button('close', 'Close this panel (Ctrl+W); the chat stays in the list')
        self.close_button.clicked.connect(lambda: self.closeRequested.emit(self.chat_id))
        head.addWidget(self.dot)
        head.addWidget(self.title, 1)
        head.addWidget(self.mode_badge)
        head.addWidget(self.project_button)
        head.addWidget(self.more)
        head.addWidget(self.close_button)
        lay.addLayout(head)
        self.info = QLabel('')
        self.info.setObjectName('hubHint')
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.info)
        self.view = QTextBrowser()
        self.view.setObjectName('hubConversation')
        self.view.setOpenExternalLinks(True)
        self.view.setPlaceholderText('Ask anything — science, code, writing, everyday tasks.')
        self.view.document().setDefaultStyleSheet(theme.html_css())
        lay.addWidget(self.view, 1)
        self.card_box = QVBoxLayout()
        self.card_box.setSpacing(6)
        lay.addLayout(self.card_box)
        self.composer = Composer(bool(core.conf.get('send_with_enter', True)))
        self.input = self.composer.input
        lay.addWidget(self.composer)
        c = self.composer
        c.sendRequested.connect(self.send)
        c.stopRequested.connect(self.run.stop)
        c.attach.clicked.connect(self.attach)
        c.context.clicked.connect(self.attach_context)
        c.mic.clicked.connect(self._mic_clicked)
        c.brainstorm.toggled.connect(self._brainstorm_toggled)
        c.model.activated.connect(self._model_chosen)
        c.input.files.connect(self._add_files)
        c.input.escape.connect(self._escape)
        self.input.installEventFilter(self)
        self.view.installEventFilter(self)
        c.context.setVisible(bool(self._host_context_available()))
        # voice (one controller per panel; Esc cancels, F11 held = push-to-talk)
        from ..voice.controller import VoiceController
        self.voice = VoiceController(lambda: self.core.conf, self)
        self.voice.stateChanged.connect(self._voice_state)
        self.voice.elapsed.connect(lambda s: c.voice_label.setText(f'Recording {s // 60}:{s % 60:02d}  (click to '
                                                                    'stop, Esc to cancel)'))
        self.voice.transcribed.connect(self._insert_text)
        self.voice.failed.connect(lambda m: self.info.setText('Voice: ' + m))
        self.voice.needsModel.connect(self._download_model)
        # shortcuts inside the panel
        scope = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for seq, slot in (('Ctrl+.', self.run.stop), ('Alt+Y', lambda: self._card_key('allow')),
                          ('Alt+A', lambda: self._card_key('always')), ('Alt+N', lambda: self._card_key('deny')),
                          ('Ctrl+Shift+M', self._focus_model), ('Ctrl+M', self.show_move_menu),
                          ('Ctrl+Shift+B', lambda: c.brainstorm.toggle()), ('Ctrl+Shift+V', self.voice.toggle),
                          ('Ctrl+Shift+R', self.run.regenerate), ('Ctrl+Shift+E', self.edit_last),
                          ('Ctrl+Shift+C', self.copy_last), ('Ctrl+Shift+G', self.generate_prompt)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(scope)
            sc.activated.connect(slot)
        QApplication.instance().installEventFilter(self)
        self._ptt = False
        # engine
        r = self.run
        r.delta.connect(lambda _part: self._render_timer.start())
        r.finished.connect(self._finished)
        r.stateChanged.connect(self._state)
        r.approvalAsked.connect(self._approval)
        r.routeAsked.connect(self._route)
        r.budgetAsked.connect(self._budget)
        r.info.connect(self.info.setText)
        r.modelChanged.connect(lambda text: c.route.setText(text[:60]))
        r.activity.connect(lambda text: self.info.setText(text.replace('Running tool: ', 'Using ')))
        r.finalPrompt.connect(self._final_prompt)
        r.toolCard.connect(self._tool_card)
        r.toolApproval.connect(self._tool_approval)
        core.backendsChanged.connect(self._fill_models)
        core.chatsChanged.connect(self._refresh_header)
        core.moveSuggested.connect(self._move_suggested)
        core.settingsChanged.connect(self._settings_changed)
        core.usageChanged.connect(self._budget_label)
        self._fill_models()
        self._refresh_header()
        self._state(r.state)
        draft = self.chat.get('draft') or ''
        if draft:
            self.input.setPlainText(draft)
        self.render()
        if r.approvals:
            a = r.approvals[0]
            self._approval({'title': a['title'], 'detail': a['detail'], 'tool': a['tool']})
        if r.pending_route:
            self._route({**r.pending_route, 'label': core.label(r.pending_route['backend']),
                         'alt_label': core.label(r.pending_route['alternative'])})
        if r.pending_budget:
            self._budget(r.pending_budget)
        for request in list(r.tool_approvals):
            self._tool_approval(request)

    # ------------------------------------------------------------------ header
    @property
    def chat(self) -> dict:
        return self.core.store.get_chat(self.chat_id) or {'title': 'Deleted chat', 'messages': [], 'project': ''}

    def _refresh_header(self):
        chat = self.chat
        self.title.setText(chat.get('title', 'New chat'))
        self.title.setToolTip(chat.get('title', ''))
        project = self.core.store.project(chat.get('project', '')) if chat.get('project') else None
        self.project_button.setText(project['name'] if project else 'No project')
        menu = QMenu(self.project_button)
        for p in self.core.store.projects():
            act = menu.addAction(p['name'])
            act.setCheckable(True)
            act.setChecked(bool(project and project['id'] == p['id']))
            act.triggered.connect(lambda _=False, pid=p['id']: self.move_to(pid))
        menu.addSeparator()
        menu.addAction('No project', lambda: self.move_to(''))
        self.project_button.setMenu(menu)
        brainstorming = chat.get('mode') == 'brainstorm'
        self.mode_badge.setVisible(brainstorming)
        self.composer.brainstorm.blockSignals(True)
        self.composer.brainstorm.setChecked(brainstorming)
        self.composer.brainstorm.blockSignals(False)
        self.composer.set_flag('brainstorm', brainstorming)
        more = QMenu(self.more)
        from .svg_icons import icon
        more.addAction(icon('copy'), 'Copy last reply\tCtrl+Shift+C', self.copy_last)
        more.addAction(icon('copy'), 'Copy last code block', self.copy_code)
        more.addAction(icon('regenerate'), 'Regenerate last reply\tCtrl+Shift+R', self.run.regenerate)
        more.addAction(icon('edit'), 'Edit last message\tCtrl+Shift+E', self.edit_last)
        more.addSeparator()
        more.addAction(icon('prompt'), 'Generate final prompt\tCtrl+Shift+G', self.generate_prompt).setEnabled(brainstorming)
        more.addAction(icon('prompt'), 'Open last final prompt…', self.open_last_prompt).setEnabled(
            any(m.get('kind') == 'final_prompt' for m in chat.get('messages', [])))
        links = chat.get('links') or {}
        if links.get('brainstorm'):
            more.addAction('Open the brainstorming chat', lambda: self.executionStarted.emit(links['brainstorm']))
        for cid in links.get('executions', [])[-5:]:
            more.addAction(icon('run'), 'Open execution', lambda c=cid: self.executionStarted.emit(c))
        more.addSeparator()
        more.addAction(icon('copy'), 'Copy whole conversation', self.copy_all)
        self.more.setMenu(more)
        self._budget_label()

    def show_move_menu(self):
        self.project_button.showMenu()

    def move_to(self, project_id: str):
        try:
            self.core.store.move_chat(self.chat_id, project_id)
        except KeyError:
            return
        self._drop_card('move')
        self.core.chatsChanged.emit()

    def _fill_models(self):
        model = self.composer.model
        current = self.chat.get('backend', 'auto')
        model.blockSignals(True)
        model.clear()
        model.addItem('Auto', 'auto')
        model.setItemData(0, 'Chosen by task size, routing profile and free capacity', Qt.ItemDataRole.ToolTipRole)
        for b in self.core.backends:
            provider = (b.get('connection') or {}).get('provider') or b.get('provider', '')
            model.addItem(theme.dot_icon(theme.provider_color(b.get('group', ''), provider)),
                          b['label'] + ('' if b['tools'] else '  · chat'), b['key'])
            model.setItemData(model.count() - 1, b.get('note', ''), Qt.ItemDataRole.ToolTipRole)
        i = model.findData(current)
        if i < 0 and current != 'auto':
            model.addItem(current + ' (not available)', current)
            i = model.count() - 1
        model.setCurrentIndex(max(0, i))
        model.blockSignals(False)

    def _model_chosen(self, _index):
        if 'id' in self.chat:
            self.core.store.set_meta(self.chat_id, backend=self.composer.model.currentData() or 'auto')

    def _focus_model(self):
        self.composer.model.setFocus()
        self.composer.model.showPopup()

    def _settings_changed(self):
        self.input.enter_sends = bool(self.core.conf.get('send_with_enter', True))
        self.view.document().setDefaultStyleSheet(theme.html_css())
        self._cache.clear()
        self.render()

    # ------------------------------------------------------------------ rendering
    def _meta_line(self, m: dict) -> str:
        bits = []
        if m.get('actual_model') and m.get('actual_model') not in (m.get('model') or ''):
            bits.append(html.escape(m['actual_model']))
        bits.append('local' if m.get('local') else 'cloud')
        if m.get('duration_s') is not None:
            bits.append(f"{m['duration_s']:.0f} s" if m['duration_s'] >= 1 else f"{m['duration_s']} s")
        u = m.get('usage') or {}
        if u.get('input_tokens') or u.get('output_tokens'):
            bits.append(f"{u.get('input_tokens', 0)} in / {u.get('output_tokens', 0)} out tokens")
            if u.get('cost_usd'):
                bits.append(f"${float(u['cost_usd']):.4f}")
        s = m.get('stats') or {}
        if s.get('tokens_per_s'):
            bits.append(f"{s['tokens_per_s']} tok/s")
        if m.get('mode') == 'brainstorm':
            bits.append('brainstorming')
        route = m.get('route') or []
        tip = ' → '.join(route)
        line = ' · '.join(bits)
        if tip:
            line += f' · <span title="{html.escape(tip)}">route: {html.escape(tip[:90])}</span>'
        return line

    def _message_html(self, m: dict) -> str:
        t = theme.tokens()
        role = m.get('role')
        key = (role, m.get('ts'), len(m.get('content', '')))
        if key not in self._cache:
            if role == 'note':
                body = f'<p style="color:{t["muted"]}"><i>{html.escape(m["content"])}</i></p>'
            elif role == 'user' and m.get('kind') in ('tool_result', 'host_result'):
                lines = [ln[4:] for ln in m['content'].splitlines() if ln.startswith('### ')]
                what = ', '.join(lines[:6]) or 'results'
                body = (f'<p style="color:{t["subtle"]};font-size:small"><i>Sent back to the assistant: '
                        f'{html.escape(what)}</i></p>')
            elif role == 'user':
                shown = m['content']
                if m.get('kind') == 'final_prompt_request':
                    shown = '*Generate the final prompt from this brainstorming.*'
                body = (f'<table width="100%" cellpadding="10" style="background:{t["hub_user_bubble"]};'
                        f'color:{t["hub_user_text"]}"><tr><td>{md_html(shown)}</td></tr></table>')
            else:
                content = brainstorm.strip_spec(m['content']) if m.get('mode') == 'brainstorm' else m['content']
                body = md_html(_display(content))
                if m.get('kind') == 'final_prompt':
                    body = '<p><b>Final prompt</b> (chat actions › Open last final prompt to edit and run)</p>' + body
                body += f'<p style="color:{t["subtle"]};font-size:small">{self._meta_line(m)}</p>'
            self._cache[key] = body
        if role == 'user' and m.get('kind') in ('tool_result', 'host_result'):
            return self._cache[key]
        who = {'user': '', 'assistant': html.escape(str(m.get('model') or 'Assistant')),
               'note': 'Agent Hub'}.get(role, role)
        color = t['muted']
        if role == 'assistant':
            provider = ''
            backend = scheduler_find(self.core.backends, m.get('backend', ''))
            if backend is not None:
                provider = (backend.get('connection') or {}).get('provider') or backend.get('provider', '')
            color = theme.provider_color(m.get('group', ''), provider) if m.get('group') else t['muted']
        head = (f'<p style="margin:14px 0 2px 0;color:{color};font-weight:600">{who}</p>' if who else
                '<p style="margin:10px 0 0 0"></p>')
        return head + self._cache[key]

    def render(self):
        bar = self.view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 30
        keep = bar.value()
        msgs = self.chat.get('messages', [])
        out = ''
        if len(msgs) > 160:
            out = f'<p style="color:gray"><i>{len(msgs) - 160} earlier messages hidden (search finds them).</i></p>'
        out += ''.join(self._message_html(m) for m in msgs[-160:])
        if self.chat.get('mode') == 'brainstorm' and self.chat.get('spec'):
            t = theme.tokens()
            out += (f'<table width="100%" cellpadding="8" style="border:1px solid {t["warning"]}"><tr><td>'
                    f'<b>Running specification</b><br>{md_html(self.chat["spec"])}</td></tr></table>')
        if self.run.partial:
            t = theme.tokens()
            out += (f'<p style="margin:14px 0 2px 0;color:{t["muted"]};font-weight:600">'
                    f'{html.escape((self.run.backend_info or {}).get("label", "Assistant"))} '
                    f'<span style="color:{t["subtle"]};font-weight:normal">· writing…</span></p>' +
                    md_html(_display(brainstorm.strip_spec(self.run.partial))))
        self.view.setHtml(out)
        bar.setValue(bar.maximum() if (at_end or self.run.partial) else keep)

    def _finished(self):
        self._drop_card('approval')
        self.render()
        self._refresh_header()

    def _tick(self):
        if self.run.state == 'running' and self.run.started_at:
            seconds = int(time.monotonic() - self.run.started_at)
            label = self.run.backend_info['label'] if self.run.backend_info else ''
            if not self.info.text().startswith(('Using', 'Error', 'Voice')):
                self.info.setText(f'Working {seconds} s · {label}')

    def _state(self, state: str):
        from ..icons import state_icon
        self.dot.setPixmap(state_icon(state, 0, True).pixmap(14, 14))
        self.dot.setToolTip(state_text(state))
        busy = state in ('running', 'approval', 'queued')
        self.composer.set_busy(busy)
        if state == 'running':
            self._clock.start()
        else:
            self._clock.stop()
        if state == 'queued':
            self.info.setText('Waiting for a free model…')
        self.stateChanged.emit(self.chat_id, state)

    def _budget_label(self):
        if self.chat.get('mode') != 'brainstorm':
            self.composer.budget.setText('')
            return
        used = self.core.ledger.chat_tokens(self.chat_id, mode='brainstorm')
        limit = int(self.chat.get('budget') or self.core.conf.get('brainstorm_budget_tokens', 60000))
        self.composer.budget.setText(f'{used // 1000}k/{limit // 1000}k tokens')
        self.composer.budget.setToolTip('Brainstorming budget of this chat: tokens reported by the model, or '
                                        'estimated from text length when it reports none')

    # ------------------------------------------------------------------ cards
    def _add_card(self, key: str, card: Card):
        self._drop_card(key)
        self.cards[key] = card
        self.card_box.addWidget(card)
        card.show()
        if self.isVisible() and (self.isAncestorOf(QApplication.focusWidget() or self)
                                 or not self.input.toPlainText().strip()):
            QTimer.singleShot(0, card.setFocus)

    def _drop_card(self, key: str):
        card = self.cards.pop(key, None)
        if card is not None:
            refocus = card.hasFocus()
            card.hide()
            card.deleteLater()
            if refocus:
                self.input.setFocus()

    def _card_key(self, value: str):
        mapping = {'allow': {'approval': 'allow', 'route': 'alternative', 'move': 'move', 'budget': 'continue'},
                   'always': {'approval': 'always', 'route': 'anyway', 'move': 'auto', 'budget': 'continue'},
                   'deny': {'approval': 'deny', 'route': 'queue', 'move': 'keep', 'budget': 'stop'}}[value]
        for key in ('approval', 'budget', 'route', 'move'):
            card = self.cards.get(key)
            if card is not None:
                card.choose(mapping[key])
                return

    def _approval(self, request: dict):
        rule = request.get('rule') or {}
        always = 'Always allow'
        if rule.get('tool') == 'bash' and rule.get('prefix'):
            always = f'Always allow “{rule["prefix"]}”'
        elif rule.get('tool') == 'write' and rule.get('path'):
            always = 'Always allow in this folder'
        if request.get('outbound'):
            # something would leave this computer on the user's behalf: always asked, never "always"
            card = Card('approval', 'Leaves your computer — ' + request['title'],
                        request.get('detail', '') + '\n\nThis is asked every time, also with full access.',
                        [('&Allow once', ('Y', 'Enter'), 'allow', True), ('&Deny', ('N', 'Esc'), 'deny', False)])
        else:
            card = Card('approval', 'The assistant asks: ' + request['title'], request.get('detail', ''),
                        [('&Allow', ('Y', 'Enter'), 'allow', True), (always, ('A',), 'always', False),
                         ('&Deny', ('N', 'Esc'), 'deny', False)])
        card.chosen.connect(self._approval_answer)
        self._add_card('approval', card)

    def _approval_answer(self, value: str):
        self._drop_card('approval')
        self.run.answer_approval(value)

    def _route(self, decision: dict):
        card = Card('route', decision.get('reason', 'This model is busy.'),
                    f"Use {decision.get('alt_label')} for this request instead?",
                    [(f"&Use {decision.get('alt_label')}", ('U', 'Enter'), 'alternative', True),
                     ('Wait in the &queue', ('Q', 'Esc'), 'queue', False),
                     (f"&Run on {decision.get('label')} anyway", ('R',), 'anyway', False)])
        card.chosen.connect(self._route_answer)
        self._add_card('route', card)

    def _route_answer(self, value: str):
        self._drop_card('route')
        self.run.resume_after_route(value)

    def _budget(self, info: dict):
        card = Card('budget', f"Brainstorming budget reached ({info['used'] // 1000}k of {info['limit'] // 1000}k "
                              'tokens).', 'Continue with a 50 % larger budget, or stop here (nothing is sent).',
                    [('&Continue', ('C', 'Enter'), 'continue', True), ('&Stop', ('S', 'Esc'), 'stop', False)])
        card.chosen.connect(lambda v: (self._drop_card('budget'), self.run.answer_budget(v)))
        self._add_card('budget', card)

    def _move_suggested(self, chat_id: str, suggestion: dict):
        if chat_id != self.chat_id:
            return
        why = 'The assistant suggests' if suggestion.get('by') == 'agent' else 'This looks like'
        card = Card('move', f"{why} the project “{suggestion['name']}”.",
                    'Move this chat there to keep your chats sorted?',
                    [(f"&Move to {suggestion['name']}", ('M', 'Enter'), 'move', True),
                     ('&Keep here', ('K', 'Esc'), 'keep', False),
                     ('&Always sort automatically', ('A',), 'auto', False)])
        card.chosen.connect(lambda value, s=suggestion: self._move_answer(value, s))
        self._add_card('move', card)

    def _move_answer(self, value: str, suggestion: dict):
        self._drop_card('move')
        if value in ('move', 'auto'):
            self.move_to(suggestion['project'])
        if value == 'auto':
            conf = dict(self.core.conf)
            conf['auto_sort'] = 'auto'
            self.core.save_settings(conf)

    # ------------------------------------------------------------------ calendar / to-do / e-mail cards
    openOrganizer = Signal(str, str)            # 'calendar' | 'todo' | 'mail', id

    def _tool_card(self, card: dict):
        from .organizer.cards import make_card
        widget = make_card(self.core.organizer, card, self)
        key = f"tool:{card.get('kind')}:{card.get('id') or card.get('uid') or len(self.cards)}"
        self._add_card(key, widget)
        if hasattr(widget, 'closed'):
            widget.closed.connect(lambda *_a, k=key: self._drop_card(k))
        if hasattr(widget, 'sent'):
            widget.sent.connect(lambda *_a: self.info.setText('Sent after your approval.'))
        if hasattr(widget, 'openRequested'):
            widget.openRequested.connect(self.openOrganizer.emit)
        if hasattr(widget, 'outboxed'):
            widget.outboxed.connect(lambda item_id: self._tool_card({'kind': 'mail', 'id': item_id}))

    def _tool_approval(self, request: dict):
        from .organizer.cards import ToolApprovalCard
        card = ToolApprovalCard(request, self)
        key = 'tool-approval:' + str(id(request))
        card.answered.connect(lambda ok, rq=request, k=key: (self._drop_card(k), self.run.answer_tool(rq, ok)))
        self._add_card(key, card)

    # ------------------------------------------------------------------ brainstorming
    def _brainstorm_toggled(self, on: bool):
        if self.run.busy:
            self.composer.brainstorm.blockSignals(True)
            self.composer.brainstorm.setChecked(not on)
            self.composer.brainstorm.blockSignals(False)
            self.info.setText('Wait for the current reply before switching brainstorming.')
            return
        self.core.store.set_meta(self.chat_id, mode='brainstorm' if on else 'normal')
        self.info.setText('Brainstorming: economical model, no execution. Chat actions › Generate final prompt when ready.'
                          if on else 'Normal mode: the agent may use its tools (with your permissions).')
        self._cache.clear()
        self._refresh_header()
        self.render()

    def generate_prompt(self):
        if self.chat.get('mode') != 'brainstorm' or self.run.busy:
            return
        self.core.generate_final_prompt(self.chat_id)
        self.render()

    def _final_prompt(self, text: str):
        self.open_prompt_editor(text)

    def open_last_prompt(self):
        last = next((m for m in reversed(self.chat.get('messages', [])) if m.get('kind') == 'final_prompt'), None)
        if last:
            self.open_prompt_editor(last['content'])

    def open_prompt_editor(self, text: str):
        dialog = PromptDialog(text, self.core.backends, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.execute:
            return
        prompt = dialog.edit.toPlainText().strip()
        backend = dialog.model.currentData() or 'auto'
        if not prompt:
            return
        conf = self.core.conf
        perms = ('Full access is ON: the agent will not ask before acting.' if conf.get('full_access') else
                 'Permissions stay as set: actions outside the allowed folders, pushes and deletions ask first.')
        from ..usage import estimate_tokens
        box = QMessageBox(self)
        box.setWindowTitle('Start execution')
        box.setText(f'Run this prompt with {self.core.label(backend)}?')
        box.setInformativeText(f'{perms}\nPrompt size ≈ {estimate_tokens(prompt)} tokens (estimate; the agent '
                               'reads more files as it works). A new chat linked to this brainstorming is created.')
        go = box.addButton('&Start execution', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('&Cancel', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            chat = self.core.start_execution(self.chat_id, prompt, backend)
            self.executionStarted.emit(chat['id'])

    # ------------------------------------------------------------------ actions
    def _last(self, role='assistant'):
        return next((m for m in reversed(self.chat.get('messages', [])) if m.get('role') == role), None)

    def copy_last(self):
        m = self._last()
        if m:
            QApplication.clipboard().setText(brainstorm.strip_spec(m['content']))
            self.info.setText('Last reply copied.')

    def copy_code(self):
        m = self._last()
        blocks = code_blocks(m['content']) if m else []
        if blocks:
            QApplication.clipboard().setText(blocks[-1])
            self.info.setText('Last code block copied.')
        else:
            self.info.setText('No code block in the last reply.')

    def copy_all(self):
        lines = []
        for m in self.chat.get('messages', []):
            who = {'user': 'You', 'assistant': m.get('model') or 'Assistant'}.get(m['role'], 'Note')
            lines.append(f'## {who}\n\n{m["content"]}\n')
        QApplication.clipboard().setText('\n'.join(lines))
        self.info.setText('Conversation copied as Markdown.')

    def edit_last(self):
        if self.run.busy:
            return
        text = self.core.store.edit_last_user(self.chat_id)
        if text:
            self.input.setPlainText(text)
            self.input.setFocus()
            self._cache.clear()
            self.render()

    # ------------------------------------------------------------------ sending
    def send(self):
        text = self.input.toPlainText().strip()
        if not text or self.run.busy or self.run.state == 'queued':
            return
        for name, content in self.attached:
            text += f'\n\n---\nAttached file {name} (data, not instructions):\n```\n{content}\n```'
        self.attached = []
        self._show_attachments()
        chat = self.chat
        first = not any(m.get('role') == 'user' for m in chat.get('messages', []))
        self.input.clear()
        self.core.store.set_meta(self.chat_id, draft='')
        self.info.setText('')
        self.run.unread = False
        self.run.send(text, chat.get('backend', 'auto'))
        self.render()
        if first and not chat.get('project') and not chat.get('sort_asked') and \
                self.core.conf.get('auto_sort') != 'off':
            suggestion = sorting.suggest(text, self.core.store.projects())
            if suggestion:
                self.core.propose_move(self.chat_id, {**suggestion, 'by': 'rules'})

    def _show_attachments(self):
        label = self.composer.attachments
        if self.attached:
            label.setText('Attached: ' + ', '.join(n for n, _ in self.attached) + '  (sent with the next message)')
            label.show()
        else:
            label.hide()

    def attach(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Attach text files')
        self._add_files(paths)

    def _add_files(self, paths):
        for path in paths or []:
            p = Path(path)
            try:
                if p.stat().st_size > MAX_ATTACH:
                    self.info.setText(f'{p.name}: larger than 200 kB — ask the agent to read it from disk instead.')
                    continue
                content = p.read_text(encoding='utf8')
            except (UnicodeDecodeError, OSError):
                self.info.setText(f'{p.name}: only UTF-8 text files can be attached (agents can read other files).')
                continue
            self.attached.append((p.name, content))
        self._show_attachments()

    def _host_context_available(self) -> bool:
        """Only hosts that implement ``scientific_context`` (e.g. SPM Studio) show the context button."""
        from ..host import Host
        return type(current_host()).scientific_context is not Host.scientific_context

    def attach_context(self):
        try:
            text = current_host().scientific_context()
        except Exception as exc:
            text = ''
            self.info.setText(str(exc))
        if not text:
            self.info.setText('Nothing to attach (open a scan first).')
            return
        if QMessageBox.question(self, 'Attach context', 'Add the current context (metadata, no image data) to the '
                                'next message? With a cloud model it is sent to its provider.') != \
                QMessageBox.StandardButton.Yes:
            return
        self.attached.append(('context', text[:12000]))
        self._show_attachments()

    # ------------------------------------------------------------------ voice
    def _mic_clicked(self):
        self.composer.mic.setChecked(self.voice.state == 'recording')
        self.voice.toggle()

    def _voice_state(self, state):
        c = self.composer
        c.mic.setChecked(state == 'recording')
        c.set_flag('recording', state == 'recording')
        from .svg_icons import set_icon
        set_icon(c.mic, 'mic', 'error' if state == 'recording' else None)
        if state == 'idle':
            c.voice_label.setText('')
        elif state == 'transcribing':
            c.voice_label.setText('Transcribing…')
        elif state == 'recording':
            c.voice_label.setText('Recording 0:00')
            self.info.setText('Voice: recording with ' + self.voice.backend_label())

    def _insert_text(self, text: str):
        current = self.input.toPlainText()
        sep = '' if not current or current.endswith((' ', '\n')) else ' '
        self.input.setPlainText(current + sep + text)
        cursor = self.input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input.setTextCursor(cursor)
        self.input.setFocus()
        self.info.setText('Voice: transcribed — edit it if needed, then press Enter to send.')

    def _download_model(self, language: str):
        from ..voice import speech
        names = {'en': 'English', 'fr': 'French', 'de': 'German'}
        if QMessageBox.question(self, 'Download offline speech model?',
                                f'Voice input needs a small (~40–50 MB) generic {names.get(language, language)} '
                                'speech model (Apache-2.0, no personal data) from the Vosk project. It is cached on '
                                'this computer; afterwards speech-to-text runs fully offline. Download it now?') != \
                QMessageBox.StandardButton.Yes:
            return
        self.info.setText('Downloading the offline speech model…')
        from PySide6.QtCore import QThread

        class Job(QThread):
            def run(self_):
                try:
                    speech.download_model(language=language)
                    self_.error = ''
                except Exception as exc:
                    self_.error = str(exc)
        job = Job(self)
        job.finished.connect(lambda: self.info.setText('Speech model ready — click the microphone again.'
                                                       if not getattr(job, 'error', '') else
                                                       'Download failed: ' + job.error))
        job.start()

    def _escape(self):
        if self.voice.state == 'recording':
            self.voice.cancel()
            self.info.setText('Voice: recording cancelled.')

    def focus_input(self):
        card = next(iter(self.cards.values()), None)
        try:
            (card or self.input).setFocus()
        except RuntimeError:                 # the panel was closed in the meantime
            pass

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and not event.isAutoRepeat() and \
                event.key() == self._ptt_key() and self.isVisible() and \
                self.isAncestorOf(QApplication.focusWidget() or self):
            if et == QEvent.Type.KeyPress and not self._ptt:
                self._ptt = True
                self.voice.start()
            elif et == QEvent.Type.KeyRelease and self._ptt:
                self._ptt = False
                self.voice.stop()
            return True
        if obj in (self.input, self.view) and et == QEvent.Type.FocusIn:
            self.focused.emit(self.chat_id)
            if self.run.state == 'done':
                self.run.unread = False
        return super().eventFilter(obj, event)

    def _ptt_key(self):
        """The push-to-talk key (Settings › Voice), F11 by default."""
        text = str(self.core.conf.get('voice_shortcut', 'F11') or 'F11')
        if getattr(self, '_ptt_cache', ('', None))[0] != text:
            key = Qt.Key.Key_F11
            try:
                seq = QKeySequence(text)
                if seq.count():
                    key = seq[0].key()
            except Exception:
                pass
            self._ptt_cache = (text, key)
        return self._ptt_cache[1]

    def focusInEvent(self, event):
        self.focused.emit(self.chat_id)
        super().focusInEvent(event)

    def save_draft(self):
        try:
            if 'id' in self.chat:
                self.core.store.set_meta(self.chat_id, draft=self.input.toPlainText())
        except (KeyError, RuntimeError):
            pass

    def compact(self, narrow: bool):
        self.composer.compact(narrow)
        self.project_button.setVisible(not narrow)

    def dispose(self):
        """Before the widget is deleted: keep the draft, stop listening (the chat itself keeps running)."""
        self.save_draft()
        self.voice.shutdown()
        try:
            QApplication.instance().removeEventFilter(self)
        except RuntimeError:
            pass
