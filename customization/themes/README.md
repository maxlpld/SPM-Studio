# Themes — how to build one for SPM Studio

**Read this before creating or changing a file in this folder** (person or AI assistant).

A theme is one `.json` file here. It sets the colours, font and corner radius of the interface.
It never changes scan images, exports or analysis figures. Choose it in **Settings › General ›
Theme**; a file added here appears in that list at once.

## Complete example

```json
{
  "schema_version": 1,
  "background": "#121417",
  "surface": "#1A1D22",
  "foreground": "#E6E8EC",
  "accent": "#3FB8A6",
  "muted": "#99A1AE",
  "font_family": "Inter",
  "font_size": 10,
  "radius": 6
}
```

Only `schema_version` (always `1`) and the five colours above are needed; every other colour is
derived from them.

| Key | Meaning |
|---|---|
| `background` | Window background. |
| `surface` | Panels, cards. |
| `foreground` | Text. |
| `accent` | Primary buttons, selection, progress bars. Use one accent colour. |
| `muted` | Secondary text, labels. |
| `font_family` | A font installed on the computer (Inter is bundled). Optional. |
| `font_size` | 7–20, in points. Optional. |
| `radius` | 0–16, corner radius in pixels. Optional. |

Optional colours, to override what is derived: `raised`, `sidebar`, `input`, `subtle`, `border`,
`border_strong`, `hover`, `pressed`, `accent_hover`, `accent_fg`, `accent_soft`, `selection`,
`danger`, `success`, `warning`.

Rules: every colour is exactly `#RRGGBB` (seven characters, no alpha, no colour names). Keep text
readable: a contrast of at least 4.5 : 1 between `foreground` and `background`/`surface`, and make
sure `accent` is visible on `surface`. A theme is dark when its background is dark; icons follow
automatically.

## Check

```
python -m json.tool my_theme.json
```

Then select it in **Settings › General › Theme** and look at buttons, lists, the Logs panel and a
dialog.

## Share

**Settings › Library › Themes › Export…** → one `.zip`; a colleague uses **Import…**.
