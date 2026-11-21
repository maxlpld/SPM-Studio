"""The public extension API (core extension API version 1).

An extension receives an ``ExtensionHandle`` in ``activate(api)``. Everything an extension adds goes through
it, so disabling or removing the extension can undo it: settings pages, tutorial decorations, assistant
instructions, shutdown callbacks, Qt widgets parented to the main window.

Without any extension nothing here changes the application.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .extensions import CORE_API


class ExtensionAPI(QObject):
    """Owned by the main window. ``assistantState`` forwards the real assistant states:
    idle, listening, thinking, working, talking, success, error, unavailable."""
    assistantState = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.settings_pages: dict[str, tuple[str, str, object]] = {}   # key → (ext id, label, factory)
        self.tutorial_decorators: list = []
        self.assistant_notes: dict[str, str] = {}
        self._shutdown: dict[str, list] = {}
        self._widgets: dict[str, list] = {}
        self._decorator_owner: dict[int, str] = {}
        dock = getattr(window, 'ai_dock', None)
        if dock is not None and hasattr(dock, 'agentState'):
            dock.agentState.connect(self.assistantState)

    def for_extension(self, descriptor: dict) -> 'ExtensionHandle':
        return ExtensionHandle(self, descriptor)

    def assistant_instructions(self) -> str:
        """Extra tone instructions for the next message (empty without extensions)."""
        return '\n'.join(text for text in self.assistant_notes.values() if text)

    def cleanup(self, ext_id: str):
        for callback in self._shutdown.pop(ext_id, []):
            try:
                callback()
            except Exception:
                pass
        for widget in self._widgets.pop(ext_id, []):
            try:
                widget.hide()
                widget.deleteLater()
            except RuntimeError:
                pass
        self.assistant_notes.pop(ext_id, None)
        for key in [k for k, v in self.settings_pages.items() if v[0] == ext_id]:
            self.settings_pages.pop(key)
        self.tutorial_decorators[:] = [d for d in self.tutorial_decorators
                                       if self._decorator_owner.get(id(d)) != ext_id]

    def shutdown(self):
        for ext_id in list(self._shutdown) + list(self._widgets):
            self.cleanup(ext_id)


class ExtensionHandle:
    """What one extension sees. Permissions declared in extension.json are enforced here."""
    api_version = CORE_API

    def __init__(self, api: ExtensionAPI, descriptor: dict):
        self._api = api
        self.descriptor = descriptor
        self.id = descriptor['id']
        self.permissions = set(descriptor.get('permissions', []))

    def _need(self, permission: str):
        if permission not in self.permissions:
            raise PermissionError(f'{self.id}: permission {permission!r} not declared in extension.json')

    # -- general
    @property
    def main_window(self):
        self._need('main_window_overlay')
        return self._api.window

    @property
    def core_version(self) -> str:
        from spm_studio.core.updates import current_version
        return current_version()

    def data_dir(self) -> Path:
        from spm_studio.core import paths
        folder = paths.data_dir() / 'extension_data' / self.id
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def beta_status(self) -> dict:
        from . import client
        state = client.load_state()
        return {'status': state.get('status', 'not_activated'), 'role': state.get('role', ''),
                'offline_grace_ok': client.offline_grace_ok(state)}

    def is_dark(self) -> bool:
        from PySide6.QtWidgets import QApplication
        return QApplication.palette().window().color().lightness() < 128

    def log(self, text: str):
        try:
            self._api.window._log(f'[{self.id}] {text}')
        except Exception:
            pass

    def own_widget(self, widget):
        """Hide and delete this widget when the extension is disabled or the app quits."""
        self._api._widgets.setdefault(self.id, []).append(widget)
        return widget

    def on_shutdown(self, callback):
        self._api._shutdown.setdefault(self.id, []).append(callback)

    # -- settings
    def add_settings_page(self, label: str, factory):
        """``factory(parent) -> QWidget`` shown as a page of Settings."""
        self._need('settings_page')
        self._api.settings_pages[f'ext:{self.id}'] = (self.id, label, factory)

    # -- assistant
    @property
    def assistant_state(self):
        self._need('assistant_state')
        return self._api.assistantState

    def open_assistant(self):
        dock = getattr(self._api.window, 'ai_dock', None)
        if dock is not None:
            dock.first_open()

    def prefill_assistant(self, text: str):
        """Put text in the assistant's input box (the user decides to send it)."""
        dock = getattr(self._api.window, 'ai_dock', None)
        if dock is not None:
            dock.first_open()
            try:
                dock.input.setPlainText(text)
                dock.input.setFocus()
            except AttributeError:
                pass

    def set_assistant_instructions(self, text: str | None):
        """Tone instructions added (hidden) to the next messages; ``None`` removes them at once."""
        self._need('assistant_instructions')
        if text:
            self._api.assistant_notes[self.id] = str(text)[:2000]
        else:
            self._api.assistant_notes.pop(self.id, None)

    # -- to-do
    def open_todo_count(self) -> int:
        self._need('todo_read')
        from spm_studio.documents import todo
        return sum(1 for task in todo.load()['tasks'] if not task.get('done'))

    def open_todo(self):
        self._need('todo_read')
        self._api.window.open_todo()

    # -- tutorial
    def add_tutorial_decorator(self, decorate):
        """``decorate(callout, manager)``: e.g. add an avatar to ``callout.decoration`` (a QHBoxLayout)."""
        self._need('tutorial_decorator')
        self._api._decorator_owner[id(decorate)] = self.id
        self._api.tutorial_decorators.append(decorate)
