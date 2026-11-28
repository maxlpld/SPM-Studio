"""Calendar, to-do and e-mail of Agent Hub (the data layer is Qt-free; views are in ``agent_hub.ui.organizer``).

``shared()`` returns the one :class:`~agent_hub.organizer.links.Organizer` of this process for a data folder, so
the calendar window, the to-do window, the assistant's tools and the reminder notifier all see the same data
(and their change notifications). Nothing here imports an AI backend: the calendar and the to-do list work
without any assistant connected.
"""
from __future__ import annotations

from pathlib import Path

_shared: dict[str, object] = {}


def default_root() -> Path:
    from ..host import current
    try:
        found = current().organizer_dir()
        if found:
            return Path(found)
    except Exception:
        pass
    return Path(current().data_dir()) / 'organizer'


def shared(root: Path | None = None):
    from .links import Organizer
    root = Path(root) if root else default_root()
    key = str(root.resolve()) if root.exists() else str(root)
    org = _shared.get(key)
    if org is None:
        org = Organizer(root)
        _shared[key] = org
        try:
            from ..host import current
            for legacy in current().legacy_todo_files() or []:
                org.todo.migrate_v1(Path(legacy))
        except Exception:
            pass
    return org


def reset():
    _shared.clear()
