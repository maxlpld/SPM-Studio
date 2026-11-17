# Presentation templates — how to build one for SPM Studio

**Read this before creating or changing anything in this folder** (person or AI assistant).

A presentation template sets the **theme** (colours, fonts, title bar, footer, slide numbers),
the **slide size** and, optionally, **starter slides** of a new presentation of the
**presentation editor** (*Slides* button of the main window › *New presentation*; the button
appears once *Settings › Documents › Presentation editor* is switched on). A file added here
appears in the list at once.

A template is **either** one `.json` file, **or** a folder with `template.json` plus the images it
uses (background pictures, logos), referenced by relative paths such as `media/logo.png`.

## Complete example

```json
{
  "format": "spm-slides-template-v1",
  "name": "Group meeting",
  "description": "Blue title bar, footer, 16:9.",
  "size": "16:9",
  "theme": {
    "background_color": "#FFFFFF",
    "text_color": "#16181D",
    "muted_color": "#5E6672",
    "accent_color": "#1F5FA8",
    "title_font": "Inter",
    "body_font": "Inter",
    "title_size": 30,
    "body_size": 19,
    "title_bar": true,
    "title_bar_color": "#1F5FA8",
    "footer": "Group meeting",
    "slide_numbers": true,
    "background_image": ""
  },
  "slides": [
    {
      "layout": "title",
      "notes": "Say who you are.",
      "items": [
        {"type": "text", "role": "title", "x": 48, "y": 170, "w": 864, "h": 90,
         "html": "<p align=\"center\" style=\"font-size:42pt; font-weight:600; color:#16181D;\">Talk title</p>"},
        {"type": "latex", "x": 48, "y": 300, "w": 864, "h": 80, "size": 28, "color": "#16181D",
         "source": "\\[ E = mc^2 \\]"}
      ]
    }
  ]
}
```

### Keys

| Key | Meaning |
|---|---|
| `format` | Always `"spm-slides-template-v1"`. **Required.** |
| `name`, `description` | Shown in the template list. |
| `size` | `"16:9"` (960 × 540 pt), `"4:3"` (960 × 720 pt) or `"16:10"` (960 × 600 pt). |
| `theme` | Colours are exactly `#RRGGBB`. `title_bar` draws a coloured band behind slide titles; `footer` is a text at the bottom left; `slide_numbers` shows the number at the bottom right; `background_image` is a path relative to the template folder. |
| `slides` | Optional list of starter slides. Without it a new presentation starts with one title slide. |

### Slides and items

A slide has `layout` (`title`, `title_content`, `two_columns`, `section`, `title_only`,
`image_caption`, `formula`, `blank`), optional `notes`, `background_color`, `background_image`,
`transition` (`none`, `fade`, `push`) and `items`. Coordinates are points from the top-left corner
of a slide that is **960 pt wide**.

| `type` | Keys |
|---|---|
| `text` | `html` (Qt rich text: `<p>`, `<b>`, `<i>`, `<ul><li>`, `style="font-size:…pt; color:…"`), `role` (`title`, `subtitle`, `body`, `caption`), `fill_color`, `line_color`, `line_width`, `valign` (`top`, `middle`, `bottom`). |
| `latex` | `source` (LaTeX text: words with `$…$` math, or `\[ … \]`), `size` (pt), `color`, `align`. It is compiled and displayed automatically. |
| `image`, `gif`, `video` | `src` (relative path), `fit` (`contain`, `cover`, `stretch`); videos also `autoplay`, `loop`, `muted`. |
| `shape` | `shape` (`rect`, `rounded`, `ellipse`, `line`, `arrow`, `triangle`), `fill_color`, `line_color`, `line_width`, `radius`, optional `html` text. |

Every item may also have `rotation` (degrees) and `opacity` (0–1). Item ids are created
automatically; do not write them.

## Rules

* Keep at least 48 pt of margin on every side, titles ≤ 8 words, ≤ 6 bullets per slide.
* `text_color` must be readable on `background_color` (contrast ≥ 4.5 : 1).
* Use fonts installed on every computer that will show the talk (Inter is bundled with
  SPM Studio).

## Check

```
python -m json.tool My_Template.json
```

Then *Slides › New presentation*, choose the template, and look at every starter slide.

## Other ways to add a template

* **Presentation editor › File › Save as template…** stores the theme (and, if you want, the
  slides and their pictures) of the open presentation here.
* **Settings › Library › Presentation templates › Import…**.

## Share

*Settings › Library › Presentation templates › Export…* writes one `.zip`; a colleague installs
it with *Import file…*.
