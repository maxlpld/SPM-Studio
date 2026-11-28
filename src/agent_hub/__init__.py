"""Agent Hub — an independent, general-purpose AI assistant engine and desktop app.

* ``agent_hub.host`` — the contract with a host application (SPM Studio, other programs, or none).
* ``agent_hub.core`` — the engine (chats, agents, approvals, queue, usage), shared by every view.
* ``agent_hub.ui`` — the desktop interface (PySide6): standalone window, dockable panel, detached window.
* ``agent_hub.organizer`` — calendar, to-do list and e-mail (Qt-free data layer; views in ``agent_hub.ui.organizer``).

Run standalone with ``agent-hub`` (or ``python -m agent_hub``).
"""
__version__ = '0.3.0'
