"""v0.0.8 — Documents: LaTeX editor, presentation editor and Overleaf (optional, off by default).

Qt-free modules (importable without a display, unit-tested):

* :mod:`settings`       — preferences (``<config>/documents.json``)
* :mod:`tex`            — finding TeX engines, compile commands, log parsing
* :mod:`latex_project`  — LaTeX projects: create from template, open, import, figure insertion
* :mod:`templates`      — LaTeX and presentation templates (customization folders)
* :mod:`deck`           — presentation model (``.spmdeck`` JSON + media folder)
* :mod:`overleaf`       — Overleaf through its Git integration (clone, list folders, upload, push)
* :mod:`protocol`       — what the assistant can ask the editors to do (``<spm-doc>`` requests)

Qt modules live in :mod:`spm_studio.documents.ui`.
"""
