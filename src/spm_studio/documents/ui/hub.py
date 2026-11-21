"""The link between the scan window, the LaTeX editor, the presentation editor and the assistant.

One :class:`DocumentHub` per application (:func:`hub`). It knows every open editor window,
which one the user used last, delivers exported figures to them (and to Overleaf), and runs the
``<spm-doc>`` requests of the assistant on the right window.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from spm_studio.documents import settings as doc_settings, latex_project, deck as deck_model, overleaf
from spm_studio.shared.dialogs import MessageDialog
from .common import run_in_thread

_HUB = None


def hub() -> 'DocumentHub':
    global _HUB
    if _HUB is None:
        _HUB = DocumentHub()
    return _HUB


class DocumentHub(QObject):
    windowsChanged = Signal()
    message = Signal(str)            # short status text for the main window's log

    def __init__(self):
        super().__init__()
        self.main_window = None
        self._windows = []
        self._last_doc = None
        self._last_was_doc = False
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._focus_changed)

    # ---------------------------------------------------------------- registry
    def set_main_window(self, window):
        self.main_window = window
        self.message.connect(lambda text: self._log(text))

    def _log(self, text):
        try:
            self.main_window._log(text, important=True)
        except Exception:
            pass

    def windows(self, kind=None):
        alive = []
        for win in self._windows:
            try:
                win.isVisible()
            except RuntimeError:
                continue
            alive.append(win)
        self._windows = alive
        if kind is None:
            return list(alive)
        return [w for w in alive if self.kind_of(w) == kind]

    @staticmethod
    def kind_of(window) -> str:
        from .latex_editor import LatexEditorWindow
        from .todo_window import TodoWindow
        if isinstance(window, TodoWindow):
            return 'todo'
        return 'latex' if isinstance(window, LatexEditorWindow) else 'slides'

    def register(self, window):
        if window not in self._windows:
            self._windows.append(window)
        self.note_active(window)
        self.windowsChanged.emit()

    def unregister(self, window):
        if window in self._windows:
            self._windows.remove(window)
        if self._last_doc is window:
            self._last_doc = None
            self._last_was_doc = False
        self.windowsChanged.emit()

    def note_active(self, window):
        self._last_doc = window
        self._last_was_doc = True

    def _focus_changed(self, _old, new):
        if new is None:
            return
        try:
            top = new.window()
            dock = self._dock()
            if dock is not None and (dock is new or dock.isAncestorOf(new)):
                return                      # typing in the assistant keeps the document it is about
        except RuntimeError:
            return
        if top is self.main_window:
            self._last_was_doc = False
        elif top in self._windows:
            self.note_active(top)

    def active(self, kind=None):
        """The editor window the user worked in last (of ``kind``), else any open one."""
        if self._last_doc is not None and self._last_doc in self.windows(kind) :
            return self._last_doc
        found = self.windows(kind)
        return found[-1] if found else None

    def close_all(self) -> bool:
        for win in self.windows():
            win.close()
            try:
                if win.isVisible():
                    return False
            except RuntimeError:
                continue
        return True

    def open_settings(self):
        if self.main_window is not None:
            self.main_window.open_settings('documents')

    # ---------------------------------------------------------------- opening
    def open_latex(self, folder):
        from .latex_editor import LatexEditorWindow
        folder = Path(folder)
        for win in self.windows('latex'):
            if Path(win.project).resolve() == folder.resolve():
                win.show()
                win.raise_()
                win.activateWindow()
                return win
        win = LatexEditorWindow(folder, self)
        self.register(win)
        win.show()
        return win

    def open_slides(self, path):
        from .slides_editor import PresentationWindow
        file = deck_model.deck_file(path)
        for win in self.windows('slides'):
            if Path(win.deck_path).resolve() == file.resolve():
                win.show()
                win.raise_()
                win.activateWindow()
                return win
        try:
            win = PresentationWindow(file, self)
        except deck_model.DeckError as exc:
            MessageDialog.warning(self.main_window, 'Presentation', str(exc))
            return None
        self.register(win)
        win.show()
        return win

    def open_todo(self):
        """The to-do list & notes window (one per application; the list is saved on disk)."""
        from .todo_window import TodoWindow
        for win in self.windows('todo'):
            win.show()
            win.raise_()
            win.activateWindow()
            return win
        win = TodoWindow(self)
        self.register(win)
        win.show()
        return win

    def launch(self, kind, parent=None):
        from .launcher import Launcher
        dialog = Launcher(kind, self, parent or self.main_window)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.result_path:
            return self.open_latex(dialog.result_path) if kind == 'latex' else self.open_slides(dialog.result_path)
        return None

    def import_from_overleaf(self, parent=None):
        from .send_dialog import choose_overleaf_project
        parent = parent or self.main_window
        if not overleaf.get_token():
            MessageDialog.information(parent, 'Overleaf', 'Add your Overleaf Git token in Settings › Documents first.')
            self.open_settings()
            return
        project_id = choose_overleaf_project(parent)
        if not project_id:
            return
        conf = doc_settings.load()
        entry = next((p for p in conf['overleaf_projects'] if p['id'] == project_id), {})
        target = latex_project.unique_folder(doc_settings.latex_root(conf), entry.get('name') or project_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.message.emit(f'Overleaf: downloading {entry.get("name") or project_id}…')

        def done(result, error):
            if error:
                MessageDialog.warning(parent, 'Overleaf', error)
                return
            if not latex_project.is_project(result):
                MessageDialog.warning(parent, 'Overleaf', 'The project was downloaded, but it has no .tex file '
                                                         'with \\documentclass yet.')
            self.open_latex(result)
        run_in_thread(lambda: overleaf.OverleafClient(conf).clone_project(project_id, target), done, parent)

    # ---------------------------------------------------------------- delivery
    def send_files_dialog(self, files, parent=None, only=None):
        from .send_dialog import SendDialog
        dialog = SendDialog(self, parent or self.main_window, files=files, allow_folder=False, only=only)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.deliver(files, dialog.targets())

    def _resolve(self, kind, target):
        """A window for a target given as window, path or ``None`` (→ ask)."""
        if target is None:
            if kind == 'latex':
                folder = QFileDialog.getExistingDirectory(self.main_window, 'LaTeX project folder',
                                                          str(doc_settings.latex_root()))
                return self.open_latex(folder) if folder else None
            file, _ = QFileDialog.getOpenFileName(self.main_window, 'Presentation', str(doc_settings.slides_root()),
                                                  f'Presentations (*{deck_model.SUFFIX})')
            return self.open_slides(file) if file else None
        if isinstance(target, (str, Path)):
            return self.open_latex(target) if kind == 'latex' else self.open_slides(target)
        try:
            target.isVisible()
        except RuntimeError:
            return None
        return target

    def deliver(self, files, targets: dict, caption: str = '') -> list[str]:
        """Send exported ``files`` (the formats of one figure) to the chosen destinations."""
        files = [Path(f) for f in files if Path(f).is_file() and not str(f).endswith('.provenance.json')]
        notes = []
        if not files:
            return notes
        caption = targets.get('latex_caption') or caption
        if 'latex' in targets:
            win = self._resolve('latex', targets.get('latex'))
            if win is not None:
                try:
                    rel = win.insert_figure(files, caption)
                    notes.append(f'LaTeX: inserted {rel} in {win.project.name}')
                except Exception as exc:
                    MessageDialog.warning(self.main_window, 'LaTeX', f'Could not insert the figure: {exc}')
        if 'slides' in targets:
            win = self._resolve('slides', targets.get('slides'))
            if win is not None:
                try:
                    where = win.add_figure(files, new_slide=targets.get('slides_mode', 'new') == 'new',
                                           title=caption)
                    notes.append(f'Presentation: figure added to {where}')
                except Exception as exc:
                    MessageDialog.warning(self.main_window, 'Presentation', f'Could not add the figure: {exc}')
        if targets.get('overleaf'):
            spec = targets['overleaf']
            upload = self._overleaf_files(files)
            conf = doc_settings.load()
            name = next((p.get('name') for p in conf['overleaf_projects'] if p['id'] == spec['project']), spec['project'])
            self.message.emit(f'Overleaf: uploading {", ".join(f.name for f in upload)} to {name}/{spec["folder"]}…')

            def done(result, error):
                if error:
                    MessageDialog.warning(self.main_window, 'Overleaf', error)
                    self.message.emit('Overleaf upload failed: ' + error)
                else:
                    self.message.emit(f'Overleaf: uploaded {", ".join(result)} to “{name}”')
            run_in_thread(lambda: overleaf.OverleafClient(conf).upload(spec['project'], upload, spec['folder']),
                          done, self.main_window)
            notes.append(f'Overleaf: upload to {name} started')
        for note in notes:
            self.message.emit(note)
        return notes

    def _overleaf_files(self, files):
        """What Overleaf gets: the exported formats, plus a vector PDF when only an SVG exists."""
        out = [f for f in files if f.suffix.lower() in ('.pdf', '.png', '.jpg', '.jpeg', '.svg', '.eps', '.gif')]
        if out and not any(f.suffix.lower() in ('.pdf', '.png', '.jpg', '.jpeg') for f in out):
            from spm_studio.core import paths
            from .common import svg_to_pdf
            svg = next(f for f in out if f.suffix.lower() == '.svg')
            folder = paths.cache_dir() / 'overleaf_converted'
            folder.mkdir(parents=True, exist_ok=True)
            out.append(svg_to_pdf(svg, folder / (svg.stem + '.pdf')))
        return out or files

    # ---------------------------------------------------------------- assistant
    def _dock(self):
        return getattr(self.main_window, 'ai_dock', None) if self.main_window is not None else None

    def show_assistant(self, source=None):
        """Open the assistant for an editor window, in a window of its own beside it.

        The SPM Studio window is not brought forward, and the assistant window is only placed
        the first time: afterwards it stays wherever the user moved it (any screen or desktop).
        """
        dock = self._dock()
        if dock is None:
            return None
        if source is not None:
            self.note_active(source)
        if not dock.conf.get('configured'):
            dock.setup()
        was_open = dock.is_open()
        placed = bool(self.main_window.settings.value('ai_window_geometry')) if self.main_window else False
        if source is not None and not dock.detached():
            dock.undock_panel(show=False)
        window = dock.panel_window()
        if source is not None and dock.detached() and not was_open and not placed:
            geo = source.frameGeometry()
            screen = (source.screen() or QApplication.primaryScreen()).availableGeometry()
            width = max(420, window.width())
            height = max(560, min(geo.height(), screen.height() - 40))
            x = geo.right() + 8 if geo.right() + 8 + width <= screen.right() else screen.right() - width
            window.resize(width, height)
            window.move(max(screen.left(), x), max(screen.top(), geo.top()))
        dock.open_panel()
        return window

    def ask_assistant(self, text, send=False, source=None):
        if self.show_assistant(source) is None:
            return
        dock = self._dock()
        dock.input.setPlainText(text)
        cursor = dock.input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        dock.input.setTextCursor(cursor)
        dock.input.setFocus()
        if send:
            QTimer.singleShot(0, dock.send_prompt)

    def ai_context_line(self) -> str:
        """One line telling the assistant which document the user is working on (empty if none)."""
        if not self._last_was_doc:
            return ''
        win = self.active()
        if win is None:
            return ''
        try:
            return win.ai_state()
        except Exception:
            return ''

    def ai_execute(self, requests) -> list:
        results = []
        for request in requests:
            try:
                results.append((request, self._ai_one(request)))
            except Exception as exc:
                results.append((request, f'ERROR: {exc}'))
        return results

    def _ai_one(self, r) -> str:
        app, action = r['app'], r['action']
        conf = doc_settings.load()
        if app == 'todo':
            from .todo_window import ai_action
            found = self.windows('todo')
            return ai_action(r, found[0] if found else None)
        if app == 'latex':
            if action == 'new_project':
                from spm_studio.documents import templates
                found = templates.find('latex', r.get('template') or conf.get('latex_default_template', 'Article'))
                folder = latex_project.create_project(doc_settings.latex_root(conf), r.get('name') or 'Untitled',
                                                      found.path if found else None)
                self.open_latex(folder)
                return f'Created and opened {folder}'
            win = self.active('latex')
            if win is None:
                raise ValueError('No LaTeX project is open (ask the user to open one, or use new_project)')
            if action == 'read':
                return win.ai_read()
            if action == 'read_file':
                return win.ai_read_file(r.get('path', ''))
            if action == 'insert':
                return win.ai_insert(r.get('text', ''), r.get('at', 'cursor'))
            if action == 'replace':
                return win.ai_replace(r.get('find', ''), r.get('replace', ''), r.get('all', False), r.get('path', ''))
            if action == 'write_file':
                return win.ai_write_file(r.get('path', ''), r.get('text', ''))
            if action == 'open_file':
                return win.ai_open_file(r.get('path', ''))
            if action == 'compile':
                return win.ai_compile()
        else:
            if action == 'new_presentation':
                from spm_studio.documents import templates
                name = r.get('template') or conf.get('slides_default_template', 'Clean_Light')
                try:
                    template = templates.load_slides_template(name)
                except templates.TemplateError:
                    template = None
                file = deck_model.create_project(doc_settings.slides_root(conf), r.get('name') or 'Presentation',
                                                 size=conf.get('slides_size', '16:9'), template=template)
                self.open_slides(file)
                return f'Created and opened {file}'
            win = self.active('slides')
            if win is None:
                raise ValueError('No presentation is open (ask the user to open one, or use new_presentation)')
            return win.ai_action(r)
        raise ValueError(f'Unknown action {action}')
