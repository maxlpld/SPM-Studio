"""The host contract: everything Agent Hub may ask of the application it runs in (Qt-free).

The engine and the GUI never import a host application. A host (SPM Studio, another
program) subclasses :class:`Host`, overrides what it offers and calls :func:`set_host` before creating the
hub. The standalone app uses :class:`Host` itself.

Contract version: bump the major number of ``CONTRACT`` for any incompatible change; a host declares the
range it supports with :func:`compatible`.
"""
from __future__ import annotations

from pathlib import Path

CONTRACT = (1, 1)
# 1.1 (Agent Hub 0.3): optional organizer_dir, legacy_todo_files, handle_reply, extra_instructions,
#     settings_pages, project_actions, notify; all with safe defaults below.

GENERAL_PROJECTS = [
    {'id': 'everyday', 'name': 'Everyday & admin', 'folder': 'general',
     'keywords': ['email', 'e-mail', 'mail', 'reply to', 'letter', 'form', 'invoice', 'appointment', 'bank',
                  'insurance', 'tax', 'administrative', 'translate', 'courrier', 'répondre', 'lettre',
                  'facture', 'impôt', 'administratif', 'rendez-vous', 'traduire', 'assurance'],
     'instructions': 'Everyday tasks: e-mails, letters, forms, administrative questions, translations. Write '
                     'drafts the user can copy; never send anything on the user\'s behalf without asking.'},
    {'id': 'research', 'name': 'Research & literature', 'folder': 'general',
     'keywords': ['paper', 'literature', 'citation', 'reference', 'bibtex', 'study', 'review article', 'doi',
                  'zotero', 'consensus', 'publication', 'bibliographie'],
     'instructions': 'Scientific research and literature. Cite only sources you actually retrieved; separate '
                     'verified facts from interpretation.'},
    {'id': 'programming', 'name': 'Programming', 'folder': 'general',
     'keywords': ['python', 'javascript', 'rust', 'compile', 'refactor', 'unit test', 'stack trace',
                  'exception', 'repository', 'docker', 'bash script'],
     'instructions': 'Software projects outside SPM Studio. Keep changes minimal and tested.'},
]


class Host:
    """Standalone defaults. Every method is safe to call and never raises."""
    name = 'standalone'
    label = 'Agent Hub'

    # ---- storage
    def data_dir(self) -> Path:
        from .paths import hub_dir
        return hub_dir()

    def legacy_data_dirs(self) -> list[Path]:
        """Older stores to copy once into the shared store (never modified)."""
        return []

    def models_dir(self) -> Path | None:
        return None

    # ---- appearance (semantic tokens; see ui/theme.py)
    def colors(self) -> dict:
        return {}

    def window_icon(self):
        return None

    # ---- agents
    def managed_pi(self) -> dict | None:
        """``{'executable', 'env', 'router': {...}, 'label'}`` for a Pi set up by the host, else None."""
        return None

    def ai_config(self) -> dict:
        """Connections and Judge settings (``connections``, ``provider``, ``model``, ``judge`` …)."""
        from .settings_store import load_ai
        return load_ai()

    def app_folders(self) -> list[Path]:
        """Folders the agent may always change (the host's own customization folders)."""
        return []

    def workspace(self, folder_key: str) -> Path | None:
        """Working folder for a project folder key, or None for the hub's own folder."""
        return None

    def base_context(self, workspace: Path, tools: bool) -> str:
        """Host instructions put before the hub's (e.g. SPM Studio folders, guides, literature tools)."""
        return ''

    def agent_allowed_tools(self) -> list[str]:
        """Extra tools pre-allowed for Claude Code (e.g. literature MCP tools)."""
        return []

    def extra_bin_dirs(self) -> list[Path]:
        return []

    def default_projects(self) -> list[dict]:
        return [dict(p) for p in GENERAL_PROJECTS]

    def judge_port_hook(self):
        """Called before starting the managed Pi (e.g. start a Judge proxy)."""
        return None

    # ---- host UI
    def open_setup(self, parent=None) -> bool:
        """Open the host's own AI setup wizard; False when the host has none."""
        return False

    def integrations(self) -> list[dict]:
        """Connections shown under Settings › Connections: ``{'id','label','status','open': callable}``."""
        return []

    def entitlement_ok(self) -> bool:
        return True

    def assistant_state(self, state: str):
        """The hub's overall state (idle, working, listening, success, error) for host decorations."""
        return None

    def scientific_context(self) -> str:
        """Optional context the user can attach (e.g. the active scan's metadata)."""
        return ''

    # ---- 1.1: organizer (calendar, to-do, e-mail) and host follow-ups
    def organizer_dir(self) -> Path | None:
        """Folder of the calendar, to-do and mail data (default: ``<data_dir>/organizer``)."""
        return None

    def legacy_todo_files(self) -> list[Path]:
        """Older to-do files to copy once into the to-do store (only read, never modified)."""
        return []

    def extra_instructions(self, kind: str) -> str:
        """More instructions for chat-only models (``kind`` = 'direct'): e.g. the host's own request tags."""
        return ''

    def handle_reply(self, text: str, chat: dict, done) -> bool:
        """The host may act on a finished reply (its own request tags). Return True when it does, then call
        ``done(message_or_None, summary)`` once: a message is sent back to the assistant as a follow-up."""
        return False

    def settings_pages(self) -> list[tuple]:
        """Extra pages of the Agent Hub settings: ``[(title, factory(parent) -> QWidget, save_callable|None)]``."""
        return []

    def project_actions(self, project: dict) -> list[tuple]:
        """Extra entries of a project's context menu: ``[(label, callable(hub_widget))]``."""
        return []

    def ask_assistant(self, text: str, send: bool = True) -> bool:
        """Hand a request to the assistant (e.g. "do this to-do"); False when the host has no assistant view."""
        return False

    def todo_writing_actions(self) -> list[tuple]:
        """Extra "write from my notes" requests of the to-do window: ``[(label, what to write)]``."""
        return []

    def display_text(self, text: str) -> str:
        """Reply text as shown in a chat (a host may shorten its own request tags)."""
        return text

    def notify(self, title: str, text: str) -> bool:
        """Show a desktop notification through the host (True when shown)."""
        return False


_current: Host = Host()


def set_host(host: Host) -> Host:
    global _current
    _current = host
    return host


def current() -> Host:
    return _current


def compatible(minimum: tuple = (1, 0), below: tuple = (2, 0)) -> bool:
    return tuple(minimum) <= CONTRACT < tuple(below)
