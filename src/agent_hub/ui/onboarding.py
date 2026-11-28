"""First-run wizard (optional, skippable). Never changes an existing setup without asking.

Four paths, combinable later in Settings:
A. Recommended Pi setup (through the host's own wizard when it has one, e.g. SPM Studio).
B. Use my existing Pi (detected; its ~/.pi configuration is used as it is, never modified).
C. Connect AI providers directly (API keys, Ollama, LM Studio, llama.cpp, custom endpoints) — no Pi needed.
D. Hybrid: any mix of the above; Auto routing picks among them.
"""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout)

from ..host import current as current_host


class Onboarding(QDialog):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.host = current_host()
        self.setWindowTitle('Welcome to Agent Hub')
        self.resize(620, 460)
        lay = QVBoxLayout(self)
        found = core.backends
        agents = ', '.join(b['label'] for b in found if b['tools']) or 'none'
        local = sum(1 for b in found if b['group'] == 'local')
        intro = QLabel(f'<p><b>How do you want to use AI here?</b> You can skip this and change everything later in '
                       f'Settings.</p><p>Found on this computer: agents — {html.escape(agents)}; local models — '
                       f'{local}.</p>')
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.group = QButtonGroup(self)
        has_wizard = self.host.name != 'standalone'
        options = [
            ('pi', 'A · Recommended Pi setup' + (f' (opens {self.host.label}\'s wizard: router, local Judge, sign-in)'
                                                 if has_wizard else ' (shows how to install Pi)')),
            ('pi_existing', 'B · Use my existing Pi as it is' + ('' if any(b['key'] == 'pi' for b in found)
                                                                 else ' (none detected)')),
            ('direct', 'C · Connect providers directly (API keys, Ollama, LM Studio, llama.cpp…) — no Pi'),
            ('hybrid', 'D · Hybrid: agents, direct APIs and local models together (Auto routing)'),
        ]
        for i, (key, text) in enumerate(options):
            b = QRadioButton(text)
            b.setProperty('key', key)
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.button(3 if found else 2).setChecked(True)
        note = QLabel('Nothing is installed without asking, and existing Pi, Ollama, Claude Code or Codex installations '
                      'and their sign-ins are never removed or overwritten.')
        note.setObjectName('hubHint')
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        buttons = QDialogButtonBox()
        go = buttons.addButton('Continue', QDialogButtonBox.ButtonRole.AcceptRole)
        skip = buttons.addButton('Skip for now', QDialogButtonBox.ButtonRole.RejectRole)
        go.clicked.connect(self.accept)
        skip.clicked.connect(self.reject)
        lay.addWidget(buttons)
        self.choice = ''

    def accept(self):
        b = self.group.checkedButton()
        self.choice = b.property('key') if b is not None else ''
        super().accept()


def maybe_run(core, hub_widget) -> None:
    """Show once, on the first start with this data folder."""
    marker = core.root / '.onboarded'
    if marker.exists():
        return
    dialog = Onboarding(core, hub_widget)
    result = dialog.exec()
    marker.write_text(dialog.choice or 'skipped', encoding='utf8')
    if result != QDialog.DialogCode.Accepted:
        return
    if dialog.choice == 'pi':
        hub_widget.open_settings('Pi Agent')
    elif dialog.choice in ('direct', 'hybrid'):
        hub_widget.open_settings('AI Providers')
    elif dialog.choice == 'pi_existing':
        hub_widget.open_settings('Pi Agent')
    conf = dict(core.conf)
    conf['routing_profile'] = 'balanced'
    core.save_settings(conf)
