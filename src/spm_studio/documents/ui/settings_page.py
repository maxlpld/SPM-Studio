"""Settings › Documents: LaTeX editor, presentation editor, Overleaf, export destinations."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QCheckBox, QLineEdit, QPushButton, QComboBox,
                               QFileDialog, QListWidget, QListWidgetItem, QLabel, QWidget, QSpinBox, QPlainTextEdit)

from spm_studio.documents import settings as doc_settings, tex, overleaf
from spm_studio.shared.dialogs import MessageDialog
from .common import run_in_thread


def build_page(dialog):
    """Return the page widget; ``dialog`` is the SettingsDialog (for its helpers and main window)."""
    window = dialog.window_
    conf = doc_settings.load()
    page, layout = dialog._page('Documents', 'Write papers and talks next to your scans. The LaTeX and presentation '
                                             'editors open in their own windows and receive figures directly from '
                                             'Export. Both are optional: switch them on here.')

    def changed(**values):
        doc_settings.save(values)
        try:
            window.refresh_document_buttons()
        except Exception:
            pass
        # v0.1.0: the assistant reads the editors' instructions with every new message (nothing to restart)

    def folder_row(box_layout, title, hint, key, root_fn):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(root_fn(doc_settings.load())))
        edit.setReadOnly(True)
        change = QPushButton('Change…')

        def pick():
            folder = QFileDialog.getExistingDirectory(dialog, title, edit.text())
            if folder:
                edit.setText(folder)
                changed(**{key: folder})
        change.clicked.connect(pick)
        h.addWidget(edit, 1)
        h.addWidget(change)
        dialog._action_row(box_layout, title, hint, row)

    # ---------------------------------------------------------------- LaTeX
    box = QGroupBox('LaTeX editor')
    v = QVBoxLayout(box)
    latex_on = QCheckBox('Show the LaTeX button in the main window')
    latex_on.setObjectName('DocumentsLatexEnabledV008')
    latex_on.setChecked(bool(conf['latex_enabled']))
    latex_on.toggled.connect(lambda on: changed(latex_enabled=bool(on)))
    dialog._action_row(v, 'LaTeX editor', 'An Overleaf-like editor: project files, live PDF, logs, auto-compile, '
                                          'templates, Overleaf sync.', latex_on)
    folder_row(v, 'Default folder for projects', 'Every new project is a folder with its name, created here (you can '
               'choose another place for each project).', 'latex_root', doc_settings.latex_root)
    engine = QComboBox()
    found = tex.available_engines()
    for name, label in doc_settings.ENGINE_LABELS.items():
        engine.addItem(label + ('' if name in found else '  — not installed'), name)
    engine.setCurrentIndex(max(0, engine.findData(conf['latex_engine'])))
    engine.currentIndexChanged.connect(lambda _i: changed(latex_engine=engine.currentData()))
    dialog._action_row(v, 'Compiler', 'Used by new projects (each project can choose its own).', engine)
    auto = QCheckBox('On')
    auto.setChecked(bool(conf['latex_autocompile']))
    auto.toggled.connect(lambda on: changed(latex_autocompile=bool(on)))
    dialog._action_row(v, 'Auto-compile', 'Recompile while you type (the editor also has an Auto-compile button).', auto)
    delay = QSpinBox()
    delay.setRange(300, 10000)
    delay.setSingleStep(100)
    delay.setSuffix(' ms')
    delay.setValue(int(conf['latex_autocompile_delay_ms']))
    delay.valueChanged.connect(lambda value: changed(latex_autocompile_delay_ms=int(value)))
    dialog._action_row(v, 'Auto-compile delay', 'Pause in typing after which the PDF is rebuilt.', delay)
    autosave = QCheckBox('On')
    autosave.setChecked(bool(conf['latex_autosave']))
    autosave.toggled.connect(lambda on: changed(latex_autosave=bool(on)))
    dialog._action_row(v, 'Save automatically', 'Like Overleaf: files are saved while you type. Recompile always '
                                                'saves first.', autosave)
    figures = QLineEdit(conf['latex_figures_folder'])
    figures.editingFinished.connect(lambda: changed(latex_figures_folder=figures.text().strip().strip('/') or 'figures'))
    dialog._action_row(v, 'Figures folder', 'Folder of the project where exported figures are copied.', figures)
    author = QLineEdit(conf.get('author', ''))
    author.setPlaceholderText('Your name')
    author.editingFinished.connect(lambda: changed(author=author.text().strip()))
    dialog._action_row(v, 'Author', 'Written into new projects ({{author}} of the templates).', author)
    status = 'Found: ' + ', '.join(found) if found else 'No TeX installation found. ' + tex.install_hint()
    label = QLabel(status)
    label.setObjectName('hint')
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    v.addWidget(label)
    layout.addWidget(box)

    # ---------------------------------------------------------------- presentations
    box = QGroupBox('Presentation editor')
    v = QVBoxLayout(box)
    slides_on = QCheckBox('Show the Slides button in the main window')
    slides_on.setObjectName('DocumentsSlidesEnabledV008')
    slides_on.setChecked(bool(conf['slides_enabled']))
    slides_on.toggled.connect(lambda on: changed(slides_enabled=bool(on)))
    dialog._action_row(v, 'Presentation editor', 'PowerPoint-like slides with text, LaTeX boxes, pictures, GIFs and '
                                                 'videos; slide show, PDF and PowerPoint export.', slides_on)
    folder_row(v, 'Default folder for presentations', 'Every new presentation is a folder with its name, created here.',
               'slides_root', doc_settings.slides_root)
    size = QComboBox()
    for key in doc_settings.SLIDE_SIZES:
        size.addItem(key, key)
    size.setCurrentIndex(max(0, size.findData(conf['slides_size'])))
    size.currentIndexChanged.connect(lambda _i: changed(slides_size=size.currentData()))
    dialog._action_row(v, 'Slide size', 'Of new presentations.', size)
    autosave_slides = QCheckBox('On')
    autosave_slides.setChecked(bool(conf['slides_autosave']))
    autosave_slides.toggled.connect(lambda on: changed(slides_autosave=bool(on)))
    dialog._action_row(v, 'Save automatically', 'Save the presentation a moment after each change.', autosave_slides)
    preamble = QPlainTextEdit(conf['formula_preamble'])
    preamble.setMaximumHeight(70)
    save_preamble = QPushButton('Save packages')
    save_preamble.clicked.connect(lambda: changed(formula_preamble=preamble.toPlainText()))
    holder = QWidget()
    hv = QVBoxLayout(holder)
    hv.setContentsMargins(0, 0, 0, 0)
    hv.addWidget(preamble)
    hv.addWidget(save_preamble, 0, Qt.AlignmentFlag.AlignRight)
    dialog._action_row(v, 'Packages of LaTeX boxes', 'Default \\usepackage lines of new presentations.', holder)
    layout.addWidget(box)

    # ---------------------------------------------------------------- to-do (v0.0.12)
    box = QGroupBox('To-do list & notes')
    v = QVBoxLayout(box)
    todo_on = QCheckBox('Show the To-do button in the main window')
    todo_on.setObjectName('DocumentsTodoEnabledV0012')
    todo_on.setChecked(bool(conf['todo_enabled']))
    todo_on.toggled.connect(lambda on: changed(todo_enabled=bool(on)))
    dialog._action_row(v, 'To-do list', 'Tasks (scan analyses, scripts, writing) and notes in their own window. The '
                                         'assistant can read them, do a task and tick it, or write a report, a paper '
                                         'or a presentation from your notes. Saved automatically.', todo_on)
    done_style = QComboBox()
    for label, key in (('Struck through', 'strike'), ('Normal', 'plain'), ('Hidden', 'hide')):
        done_style.addItem(label, key)
    done_style.setCurrentIndex(max(0, done_style.findData(conf['todo_done_style'])))
    done_style.currentIndexChanged.connect(lambda _i: changed(todo_done_style=done_style.currentData()))
    dialog._action_row(v, 'Finished tasks', 'How ticked tasks are shown in the list.', done_style)
    from spm_studio.documents import todo as _todo
    where = QLabel(str(_todo.file()))
    where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    where.setWordWrap(True)
    dialog._action_row(v, 'Saved in', 'Kept across restarts and updates; “Erase everything” keeps a copy here.', where)
    layout.addWidget(box)

    # ---------------------------------------------------------------- Overleaf
    box = QGroupBox('Overleaf')
    v = QVBoxLayout(box)
    intro = QLabel('SPM Studio sends figures to Overleaf and syncs whole projects through Overleaf\'s Git '
                   'integration. Create a token on Overleaf: Account Settings › Git integration › Generate token '
                   '(needs an Overleaf plan with Git integration — many universities provide one — or Overleaf '
                   'Server Pro). Git must be installed' + ('' if overleaf.git_executable() else
                                                          ' (not found on this computer: https://git-scm.com)') + '.')
    intro.setObjectName('hint')
    intro.setWordWrap(True)
    v.addWidget(intro)
    server = QLineEdit(conf['overleaf_server'])
    server.editingFinished.connect(lambda: changed(overleaf_server=server.text().strip() or overleaf.DEFAULT_SERVER))
    dialog._action_row(v, 'Server', 'https://www.overleaf.com, or the address of your institution\'s Overleaf.', server)
    token_row = QWidget()
    th = QHBoxLayout(token_row)
    th.setContentsMargins(0, 0, 0, 0)
    token = QLineEdit()
    token.setEchoMode(QLineEdit.EchoMode.Password)
    token.setPlaceholderText('olp_…' if not overleaf.get_token() else 'saved — paste a new one to replace it')
    save_token = QPushButton('Save')
    forget = QPushButton('Remove')
    forget.setProperty('destructive', True)
    th.addWidget(token, 1)
    th.addWidget(save_token)
    th.addWidget(forget)
    dialog._action_row(v, 'Git token', 'Kept in the system keyring (or a private file of your account).', token_row)
    state = QLabel('Token saved.' if overleaf.get_token() else 'No token yet.')
    state.setObjectName('hint')
    state.setWordWrap(True)
    v.addWidget(state)

    def store():
        if not token.text().strip():
            return
        where = overleaf.set_token(token.text().strip())
        token.clear()
        token.setPlaceholderText('saved — paste a new one to replace it')
        state.setText('Token ' + where + '.')

    def remove():
        overleaf.set_token('')
        state.setText('Token removed.')
        token.setPlaceholderText('olp_…')
    save_token.clicked.connect(store)
    forget.clicked.connect(remove)

    projects = QListWidget()
    projects.setObjectName('OverleafProjectsV008')
    projects.setMaximumHeight(140)

    def fill():
        projects.clear()
        for entry in doc_settings.load()['overleaf_projects']:
            item = QListWidgetItem(f"{entry.get('name') or entry['id']}   —   {entry.get('url', entry['id'])}")
            item.setData(Qt.ItemDataRole.UserRole, entry['id'])
            projects.addItem(item)
    fill()
    v.addWidget(QLabel('Projects'))
    v.addWidget(projects)
    row = QHBoxLayout()
    add = QPushButton('Add project…')
    rem = QPushButton('Remove')
    test = QPushButton('Test connection')
    row.addWidget(add)
    row.addWidget(rem)
    row.addStretch(1)
    row.addWidget(test)
    v.addLayout(row)

    def add_project():
        from .send_dialog import add_overleaf_project
        if add_overleaf_project(dialog):
            fill()
            try:
                window.refresh_document_buttons()
            except Exception:
                pass

    def remove_project():
        item = projects.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        doc_settings.save({'overleaf_projects': [p for p in doc_settings.load()['overleaf_projects'] if p['id'] != key]})
        fill()

    def test_connection():
        item = projects.currentItem() or (projects.item(0) if projects.count() else None)
        if item is None:
            state.setText('Add a project first.')
            return
        if not overleaf.get_token():
            state.setText('Save a Git token first.')
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        state.setText('Testing…')
        test.setEnabled(False)

        def done(result, error):
            test.setEnabled(True)
            state.setText(('✓ ' + result) if not error else ('✗ ' + error))
        run_in_thread(lambda: overleaf.OverleafClient().test(key), done, dialog)
    add.clicked.connect(add_project)
    rem.clicked.connect(remove_project)
    test.clicked.connect(test_connection)
    layout.addWidget(box)

    # ---------------------------------------------------------------- guides
    box = QGroupBox('Templates')
    v = QVBoxLayout(box)
    b = QPushButton('LaTeX templates…')
    b.clicked.connect(lambda: (dialog.show_page('library'), _select_kind(dialog, 'latex_templates')))
    dialog._action_row(v, 'LaTeX templates', 'Import, create, edit and share — Settings › Library.', b)
    b = QPushButton('Presentation templates…')
    b.clicked.connect(lambda: (dialog.show_page('library'), _select_kind(dialog, 'slide_templates')))
    dialog._action_row(v, 'Presentation templates', 'Import, create, edit and share — Settings › Library.', b)
    layout.addWidget(box)
    layout.addStretch(1)
    return page


def _select_kind(dialog, kind):
    index = dialog.kind_combo.findData(kind)
    if index >= 0:
        dialog.kind_combo.setCurrentIndex(index)
