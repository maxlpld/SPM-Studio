# LaTeX templates — how to build one for SPM Studio

**Read this before creating or changing anything in this folder** (person or AI assistant).

A LaTeX template is the starting point of a new project of the **LaTeX editor**
(*LaTeX* button of the main window › *New project*; the button appears once *Settings ›
Documents › LaTeX editor* is switched on). Everything placed here appears in the template list at
once — no restart.

A template is **either**

* a **folder** containing `template.json` and the project files (`main.tex`, `references.bib`,
  `chapters/…`, `figures/`, a `.sty` or `.cls`, images…), **or**
* a **single `.tex` file** (for one-file documents).

## Folder template — complete example

```
My_Group_Paper/
├── template.json
├── main.tex
├── references.bib
└── figures/            (may be empty; SPM Studio puts exported figures here)
```

`template.json`:

```json
{
  "name": "My group's paper",
  "description": "Two-column paper with our affiliations and macros.",
  "main": "main.tex",
  "category": "Documents"
}
```

| Key | Meaning |
|---|---|
| `name` | Shown in the template list. |
| `description` | One line under the name. |
| `main` | The root document (the file with `\documentclass`). Default `main.tex`. |
| `category` | Optional grouping (`Documents`, `Presentations`, `My templates`…). |

`template.json`, `README.md` and `preview.png` are **not** copied into new projects; every other
file is.

## Placeholders

Text files (`.tex`, `.bib`, `.sty`, `.cls`, `.md`, `.txt`) may contain placeholders that are
replaced when a project is created:

| Placeholder | Replaced by |
|---|---|
| `{{title}}` | The project name typed by the user. |
| `{{author}}` | The author name of *Settings › Documents* (empty if not set). |
| `{{date}}` | Today, `YYYY-MM-DD`. |
| `{{project}}` | The project folder name. |

Write `\title{ {{title}} }` (with spaces) so that the braces of LaTeX and of the placeholder do not
touch. `\graphicspath{{figures/}}` is not a placeholder and is kept as it is.

## Rules

1. The root file must contain a `\documentclass` line, and must compile with **pdfLaTeX**
   unless the description says otherwise (XeLaTeX / LuaLaTeX can be chosen in the editor).
2. Use only packages of a standard TeX Live / MiKTeX installation, or ship the `.sty` in the folder.
3. Keep `\usepackage{graphicx}` and `\graphicspath{{figures/}}`: figures sent from SPM Studio are
   copied to `figures/` and inserted with `\includegraphics`.
4. No absolute paths, no build files (`*.aux`, `*.log`, `*.pdf` of the document, `.spm_build/`).
5. Folder and file names: letters, digits, `_` and `-` (no spaces) so that every TeX engine
   accepts them.

## Check

Create a project from the template in the LaTeX editor and press **Recompile**: the PDF must
appear with no error in *Logs*. From a terminal:

```
cd My_Group_Paper && latexmk -pdf -interaction=nonstopmode main.tex
```

## Other ways to add a template

* **LaTeX editor › Menu › Save as template…** stores the open project here (figures optional).
* **Settings › Library › LaTeX templates › Import file… / Import folder…** accepts a `.tex` file,
  a LaTeX project folder (a `template.json` is written for it) or an Overleaf *Download source*
  `.zip`.

## Share

*Settings › Library › LaTeX templates › Export…* writes one `.zip`; a colleague installs it with
*Import file…*.
