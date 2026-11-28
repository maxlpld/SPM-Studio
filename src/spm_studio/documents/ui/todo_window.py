"""To-do list & notes window (v0.0.12; v0.1.0: upgraded in place).

From 0.1.0 the window is the upgraded to-do list (lists with colour and icon, tags, priority, deadline and start
date, repeat, subtasks, links, Today / Upcoming / Overdue / Completed, search, sort, filter, drag and drop, quick add
in plain language, the Notes page, keep on top, done-task style, erase with a kept copy, and the assistant actions
"do it", "plan", "write from my notes"). Tasks with a deadline appear in the calendar, linked both ways. The first
list (``<data>/todo/todo.json``) is copied into it once and never modified.

This module keeps the names older code used: ``TodoWindow(hub)`` and ``ai_action(request, window=None)``.
"""
from __future__ import annotations


def TodoWindow(hub=None, parent=None):          # noqa: N802 — kept name of the first version
    from spm_studio.assistant.todo_bridge import organizer
    from agent_hub.ui.organizer.windows import open_window
    return open_window('todo', parent=parent, organizer=organizer())


def ai_action(request: dict, window=None) -> str:
    """One ``<spm-doc>{"app": "todo", …}`` request on the to-do list (open windows refresh by themselves)."""
    from spm_studio.assistant.todo_bridge import ai_action as run
    return run(request)
