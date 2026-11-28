# The AI assistant in SPM Studio (Agent Hub)

From 0.1.0 SPM Studio's assistant is the **Agent Hub** engine, with SPM Studio's context added by a small host
adapter, plus the calendar, the to-do list and e-mail.

| Where | What |
|---|---|
| `src/agent_hub/` | The engine and its views (chats, projects, agents, approvals, brainstorming, voice, usage, calendar, to-do, e-mail). Installed as the `agent_hub` package next to `spm_studio`. **Do not edit it here**: it is a pinned copy. |
| `src/spm_studio/assistant/agent_hub.pin.json` | Version, commit, host-contract version and SHA-256 of the copied tree. |
| `tools/vendor_agent_hub.py` | `--from <engine checkout>` copies a committed engine and writes the pin; `--check` verifies the copy. A test (`tests/test_v010_…::test_vendored_engine_matches_its_pin`) fails when they differ. |
| `src/spm_studio/assistant/host.py` | SPM Studio's side of the host contract: folders, guides, literature and editor requests, the managed Pi, theme, settings pages, the *Develop a tool* actions. |
| `src/spm_studio/assistant/controller.py` | What the main window keeps as `ai_dock`. Nothing is imported until the assistant is first opened. |
| `src/spm_studio/assistant/organizer.py` | Calendar and to-do windows and reminders, without any AI. |
| `src/spm_studio/assistant/migrate.py` | One-time copy of the classic assistant's chats and preferences (never modifies them). |

## Updating the engine

```bash
git -C ../Agent-Hub checkout <tag-or-commit>
python tools/vendor_agent_hub.py --from ../Agent-Hub
python -m pytest -q
```

## Extensions

`spm_studio.assistant.BUILTIN` is `True` and the main window has `agent_hub_builtin = True`: an extension must not
add a second assistant panel. The extension API keeps working (`assistant_state` follows the engine's states:
thinking, working, talking, listening, success, error; `prefill_assistant`, `open_assistant`,
`set_assistant_instructions`, `open_todo_count`).

## Data

* Chats, projects, settings, calendar, to-do and mail settings: the per-user Agent Hub folder
  (`~/.local/share/agent-hub`, macOS `~/Library/Application Support/Agent Hub`, Windows `%APPDATA%\Agent Hub`),
  shared with the standalone Agent Hub app if you use it (one of them owns the chats at a time).
* Passwords, API keys, OAuth tokens: the system keyring only.
* The previous to-do file (`<SPM Studio data>/todo/todo.json`) and the classic assistant's sessions are only read.
