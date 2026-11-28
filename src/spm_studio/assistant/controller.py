"""What the main window holds as ``ai_dock``: nothing is imported or started until the assistant is first
opened (no start-up cost, no AI anywhere for someone who never opens it). Then it creates the Agent Hub engine
and its **docked panel** (detachable into its own window and back, without stopping anything).

It keeps the small interface the rest of SPM Studio used with the classic panel (``first_open``, ``is_open``,
``close_panel``, ``setup``, ``ask``, ``agentState`` …), so the editors, the to-do list, the tutorial and
extensions keep working."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class AssistantController(QObject):
    agentState = Signal(str)            # idle · working · listening · success · error (for decorations)
    shownChanged = Signal(bool)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.core = None
        self.dock = None
        self.guard = None
        self.host = None
        self.migration = {}
        self.conf = {'configured': True}

    # ---- engine, created on first use
    def ensure(self):
        if self.core is not None:
            return self.core
        from agent_hub import host as ah_host
        from . import CONTRACT_RANGE
        if not ah_host.compatible(*CONTRACT_RANGE):
            raise RuntimeError(f'Agent Hub contract {ah_host.CONTRACT} is not supported')
        from .host import SPMHost
        self.host = ah_host.set_host(SPMHost(self.main_window))
        from agent_hub.instance import InstanceGuard
        guard = InstanceGuard(self.host.data_dir())
        if not guard.acquire():
            guard.ask_owner_to_show()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self.main_window, 'AI assistant', 'The assistant is open in its own Agent Hub '
                                    'window on this computer and owns the chats (brought to the front). Close it '
                                    'there to use it inside SPM Studio.')
            return None
        self.guard = guard
        from agent_hub.core import HubCore
        from agent_hub.ui.window import HubDock
        self.core = HubCore(parent=self.main_window)
        self.dock = HubDock(self.core, self.main_window)
        self.dock.setWindowTitle('AI assistant')
        try:
            from spm_studio.shared.appearance import style_dock_titlebar
            style_dock_titlebar(self.dock, keep_floatable=True)   # same large close button as the other panels
        except Exception:
            pass
        guard.activateRequested.connect(self.open_panel)
        self.dock.shownChanged.connect(self._shown)
        self.dock.restore_saved()
        from . import migrate
        try:
            self.migration = migrate.run(self.core, self.host, getattr(self.main_window, 'settings', None))
        except Exception:
            self.migration = {}
        if self.migration.get('chats'):
            self.dock.hub.show_banner(f"{self.migration['chats']} conversation(s) of the classic assistant were "
                                      'copied here (the originals are unchanged).')
        return self.core

    def _shown(self, shown):
        self.shownChanged.emit(bool(shown))

    # ---- open / close
    def first_open(self):
        return self.open_panel()

    def open_panel(self):
        if self.ensure() is None:
            self.shownChanged.emit(False)
            return None
        if self.core.conf.get('open_mode') == 'window':
            self.dock.detach()
        else:
            self.dock.open_panel()
        if not self.core.backends:
            QTimer.singleShot(200, self._first_run_hint)
        return self.dock

    def _first_run_hint(self):
        if self.dock is not None and not self.core.backends:
            self.dock.hub.show_banner('No model is connected yet: open the settings (gear button) › AI Providers & '
                                      'Accounts, or SPM Studio assistant & Pi setup.')

    def close_panel(self):
        if self.dock is not None:
            self.dock.close_panel()

    def toggle(self):
        if self.is_open():
            self.dock.toggle()
        else:
            self.open_panel()

    def is_open(self) -> bool:
        return self.dock is not None and self.dock.is_open()

    def detached(self) -> bool:
        return self.dock is not None and self.dock.detached()

    def undock_panel(self, geometry=None, show=True):
        if self.ensure() is None:
            return None
        return self.dock.detach(show=show)

    def dock_panel(self):
        if self.dock is not None:
            self.dock.redock()

    def panel_window(self):
        return self.dock.panel_window() if self.dock is not None else None

    def isAncestorOf(self, widget) -> bool:
        """True when ``widget`` is part of the assistant (docked or detached)."""
        hub = self.dock.hub if self.dock is not None else None
        try:
            return hub is not None and (hub is widget or hub.isAncestorOf(widget))
        except RuntimeError:
            return False

    def isVisible(self) -> bool:
        return self.is_open()

    def show(self):
        self.open_panel()

    def hide(self):
        self.close_panel()

    def setup(self, page: str = ''):
        """The assistant's settings (Agent Hub › Settings): every AI option is there."""
        if self.ensure() is None:
            return
        if not self.is_open():
            self.open_panel()
        self.dock.hub.open_settings(page)

    # ---- the editors, the to-do list and extensions ask the assistant
    @property
    def input(self):
        hub = self.dock.hub if self.dock is not None else None
        panel = hub.panels.get(hub.current) if hub is not None else None
        return panel.input if panel is not None else None

    def ask(self, text: str, send: bool = False, source=None):
        """Open the assistant (beside ``source``) with ``text`` in a new chat; send it when ``send``."""
        if self.open_panel() is None:
            return None
        hub = self.dock.hub
        chat = hub.new_chat()
        panel = hub.panels.get(chat['id'])
        if panel is None:
            return None
        panel.input.setPlainText(text)
        if send:
            QTimer.singleShot(0, panel.send)
        else:
            panel.focus_input()
        return panel

    def prefill(self, text: str):
        self.ask(text, send=False)

    def send_prompt(self):
        hub = self.dock.hub if self.dock is not None else None
        panel = hub.panels.get(hub.current) if hub is not None else None
        if panel is not None:
            panel.send()

    def _open_backend(self):
        """Classic name kept for older callers: the hub reads changed settings at the next message."""
        if self.core is not None:
            self.core.refresh_backends()

    # ---- stop
    def save_state(self):
        if self.dock is not None:
            self.dock.hub.save_state()

    def shutdown(self):
        if self.dock is not None:
            try:
                self.dock.shutdown()
                self.dock.deleteLater()
            except RuntimeError:
                pass
            self.dock = None
        if self.core is not None:
            try:
                self.core.shutdown()
            except RuntimeError:
                pass
            self.core = None
        if self.guard is not None:
            self.guard.release()
            self.guard = None
