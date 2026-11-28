"""“SPM Studio assistant & Pi setup” — a page of the Agent Hub settings (0.1.0: moved here from SPM Studio's
main Settings). It opens the same dialogs as before, which edit the same settings, so nothing was lost or copied:
the Pi that SPM Studio installs and manages (router, local Judge, accounts), and the classic connection choice
(Pi, Claude Code, Codex, a direct API key) that Agent Hub also offers as models."""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget


class SetupPage(QWidget):
    title = 'SPM Studio assistant & Pi setup'

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        lay = QVBoxLayout(self)
        box = QGroupBox('Pi agent installed by SPM Studio')
        v = QVBoxLayout(box)
        hint = QLabel('Install or update the Pi agent that SPM Studio manages, sign in to your cloud or local '
                      'models, and choose its router (Fast / Smart tiers, local Judge). It appears in Agent Hub as '
                      '“Pi (SPM Studio)”.')
        hint.setWordWrap(True)
        v.addWidget(hint)
        b = QPushButton('Pi setup wizard…')
        b.clicked.connect(self.pi_wizard)
        v.addWidget(b)
        lay.addWidget(box)
        box = QGroupBox('Connections of the classic assistant')
        v = QVBoxLayout(box)
        hint = QLabel('Your own Pi, Claude Code, Codex, or a direct API key with a model (the Judge and routing '
                      'options included). Agent Hub lists them as models; more API keys and local servers can be '
                      'added under AI Providers & Accounts.')
        hint.setWordWrap(True)
        v.addWidget(hint)
        b = QPushButton('Assistant connection…')
        b.clicked.connect(lambda: self.host.open_setup(self))
        v.addWidget(b)
        lay.addWidget(box)
        lay.addStretch(1)

    def pi_wizard(self):
        from spm_studio.ai.pi_wizard import PiSetupWizard
        PiSetupWizard(self).exec()
