"""SPM Studio's AI assistant: the Agent Hub engine (``agent_hub``, vendored in ``src/agent_hub`` at a pinned
commit, see ``agent_hub.pin.json``) with SPM Studio's context, plus the calendar, the to-do list and e-mail.

* ``controller.AssistantController`` — what the main window holds as ``ai_dock``: a light object until the
  assistant is first opened (no AI module is imported at start-up), then the docked, detachable Agent Hub panel.
* ``host.SPMHost`` — SPM Studio's side of the Agent Hub host contract (folders, guides, literature, editors,
  managed Pi, theme, settings pages).
* ``migrate`` — one-time copy of the classic assistant's chats and preferences (the originals are never changed).
* ``organizer`` — the calendar and to-do windows and reminders, which work without any AI connected.

Extensions detect the built-in assistant with ``spm_studio.assistant.BUILTIN`` (or the main window's
``agent_hub_builtin`` attribute) and must not add a second Agent Hub panel.
"""
BUILTIN = True
ENGINE = 'agent_hub'
CONTRACT_RANGE = ((1, 0), (2, 0))
