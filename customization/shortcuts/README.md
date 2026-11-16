# Editable keyboard shortcut profiles

Choose a shortcut profile in **Settings (gear button) › General › Keyboard shortcuts…**. Select an action,
press the new keys in the editor, then click Assign. Your change is applied and
saved immediately. Import/Export JSON and Save as… are available in the same
window. The search field filters the live action reference; it always reflects
the active profile.

Example JSON:

```json
{
  "schema_version": 1,
  "name": "my_shortcuts",
  "bindings": {
    "nav.scan_previous": "Up",
    "nav.scan_next": "Down",
    "nav.channel_left": "Left",
    "nav.channel_right": "Right",
    "tool.run": "Ctrl+R"
  }
}
```

Unknown action IDs and duplicate shortcuts are rejected. Omitted actions use
the built-in defaults; use an empty string (`""`) to unbind an action. Only
single-combination Qt portable key names are supported, e.g. `Ctrl+Alt+J`.

**Global arrows** work while navigating scans, tools, panels, and image views;
they do not take over editable text boxes or open menus/dialogs. Up/Down change
the active scan, Left/Right scroll horizontally between visible channels.

Profiles are saved in `~/.config/spm-studio/customization/shortcuts/` and the
selected profile persists across application restarts. Shortcut files are data,
not Python code. Global GNOME shortcuts can override application shortcuts:
choose another combination if Ubuntu handles a key first.

## Share

**Settings › Library › Keyboard shortcuts › Export…** writes one `.zip`; a colleague uses **Import…**.
