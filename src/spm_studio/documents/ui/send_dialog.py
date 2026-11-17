"""Where an export goes: a folder, a LaTeX document, a presentation and/or Overleaf (any combination)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox, QLineEdit,
                               QDialogButtonBox, QPushButton, QListWidget, QListWidgetItem, QFormLayout,
                               QFileDialog)

from spm_studio.documents import settings as doc_settings, overleaf, latex_project, deck as deck_model
from spm_studio.shared.dialogs import MessageDialog
from .common import run_in_thread


def _hint(text):
    label = QLabel(text)
    label.setObjectName('hint')
    label.setWordWrap(True)
    return label


class SendDialog(QDialog):
    """Choose the destinations of a figure; ``targets()`` returns them."""

    def __init__(self, hub, parent=None, *, files=None, allow_folder=True, preset=None, only=None,
                 title='Send the figure to…'):
        super().__init__(parent)
        self.hub = hub
        self.conf = doc_settings.load()
        self.preset = preset or {}
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        if files:
            layout.addWidget(_hint('Files: ' + ', '.join(Path(f).name for f in files)))
        remembered = set(self.conf.get('export_targets', ['folder']))
        if self.preset:
            remembered = {k for k in ('latex', 'slides', 'overleaf') if self.preset.get(k)} | (
                {'folder'} if self.preset.get('folder') else set())
        self.folder_box = self.latex_box = self.slides_box = self.overleaf_box = None
        if allow_folder and only in (None, 'folder'):
            self.folder_box = QGroupBox('Save in a folder')
            self.folder_box.setCheckable(True)
            self.folder_box.setChecked('folder' in remembered or not self.preset)
            v = QVBoxLayout(self.folder_box)
            v.addWidget(_hint('You choose the folder and the file name next (as before).'))
            layout.addWidget(self.folder_box)
        if (self.conf.get('latex_enabled') or self.preset.get('latex')) and only in (None, 'latex'):
            self.latex_box = QGroupBox('Insert in a LaTeX document')
            self.latex_box.setCheckable(True)
            self.latex_box.setChecked('latex' in remembered)
            form = QFormLayout(self.latex_box)
            self.latex_target = QComboBox()
            self._fill_targets(self.latex_target, 'latex', self.preset.get('latex'))
            self.latex_caption = QLineEdit()
            self.latex_caption.setPlaceholderText('Caption (optional — the file name is used otherwise)')
            form.addRow('Project', self.latex_target)
            form.addRow('Caption', self.latex_caption)
            form.addRow(_hint('The figure is copied into figures/ (PDF; an SVG is converted to vector PDF) and '
                              'inserted at the cursor with \\includegraphics.'))
            layout.addWidget(self.latex_box)
        if (self.conf.get('slides_enabled') or self.preset.get('slides')) and only in (None, 'slides'):
            self.slides_box = QGroupBox('Add to a presentation')
            self.slides_box.setCheckable(True)
            self.slides_box.setChecked('slides' in remembered)
            form = QFormLayout(self.slides_box)
            self.slides_target = QComboBox()
            self._fill_targets(self.slides_target, 'slides', self.preset.get('slides'))
            self.slides_mode = QComboBox()
            self.slides_mode.addItem('On a new slide (title + figure)', 'new')
            self.slides_mode.addItem('On the current slide', 'current')
            if self.preset.get('slides_mode'):
                self.slides_mode.setCurrentIndex(self.slides_mode.findData(self.preset['slides_mode']))
            form.addRow('Presentation', self.slides_target)
            form.addRow('Place', self.slides_mode)
            layout.addWidget(self.slides_box)
        projects = self.conf.get('overleaf_projects') or []
        if only in (None, 'overleaf') and (projects or only == 'overleaf'):
            self.overleaf_box = QGroupBox('Upload to Overleaf')
            self.overleaf_box.setCheckable(True)
            self.overleaf_box.setChecked('overleaf' in remembered or only == 'overleaf')
            form = QFormLayout(self.overleaf_box)
            row = QHBoxLayout()
            self.overleaf_project = QComboBox()
            for entry in projects:
                self.overleaf_project.addItem(entry.get('name') or entry['id'], entry['id'])
            last = self.conf.get('overleaf_last_project')
            if last and self.overleaf_project.findData(last) >= 0:
                self.overleaf_project.setCurrentIndex(self.overleaf_project.findData(last))
            add = QPushButton('Add…')
            add.clicked.connect(self._add_project)
            row.addWidget(self.overleaf_project, 1)
            row.addWidget(add)
            form.addRow('Project', row)
            row = QHBoxLayout()
            self.overleaf_folder = QComboBox()
            self.overleaf_folder.setEditable(True)
            self.overleaf_folder.addItem(self.conf.get('overleaf_last_folder', 'figures') or '')
            self.refresh = QPushButton('List folders')
            self.refresh.setToolTip('Read the folders of the Overleaf project')
            self.refresh.clicked.connect(self._list_folders)
            row.addWidget(self.overleaf_folder, 1)
            row.addWidget(self.refresh)
            form.addRow('Folder', row)
            self.overleaf_status = _hint('Type a folder (it is created if needed) or list the existing ones.')
            form.addRow(self.overleaf_status)
            layout.addWidget(self.overleaf_box)
        if not any((self.folder_box, self.latex_box, self.slides_box, self.overleaf_box)):
            layout.addWidget(_hint('Nothing to send to: switch on the LaTeX editor, the presentation editor or '
                                   'add an Overleaf project in Settings › Documents.'))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText('Continue')
        box.button(QDialogButtonBox.StandardButton.Ok).setProperty('primary', True)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _fill_targets(self, combo, kind, preset):
        windows = self.hub.windows(kind) if self.hub else []
        seen = set()
        for win in windows:
            label = (win.project.name if kind == 'latex' else win.title()) + '  (open)'
            combo.addItem(label, ('window', win))
            seen.add(str(win.project if kind == 'latex' else win.deck_path))
        for path in doc_settings.recent(kind):
            if str(path) not in seen:
                combo.addItem(path.parent.name if path.suffix == deck_model.SUFFIX else path.name, ('path', path))
        combo.addItem('Choose another…', ('choose', None))
        if preset is not None:
            for i in range(combo.count()):
                data = combo.itemData(i)
                if data and data[1] is preset:
                    combo.setCurrentIndex(i)
                    break
        combo.activated.connect(lambda i, c=combo, k=kind: self._choose(c, k) if c.itemData(i)[0] == 'choose' else None)

    def _choose(self, combo, kind):
        if kind == 'latex':
            folder = QFileDialog.getExistingDirectory(self, 'LaTeX project folder', str(doc_settings.latex_root()))
            if folder and latex_project.is_project(folder):
                combo.insertItem(0, Path(folder).name, ('path', Path(folder)))
                combo.setCurrentIndex(0)
        else:
            file, _ = QFileDialog.getOpenFileName(self, 'Presentation', str(doc_settings.slides_root()),
                                                  f'Presentations (*{deck_model.SUFFIX})')
            if file:
                combo.insertItem(0, Path(file).parent.name, ('path', Path(file)))
                combo.setCurrentIndex(0)

    def _add_project(self):
        project_id = add_overleaf_project(self)
        if project_id:
            self.conf = doc_settings.load()
            entry = next((p for p in self.conf['overleaf_projects'] if p['id'] == project_id), None)
            if self.overleaf_project.findData(project_id) < 0:
                self.overleaf_project.addItem((entry or {}).get('name') or project_id, project_id)
            self.overleaf_project.setCurrentIndex(self.overleaf_project.findData(project_id))

    def _list_folders(self):
        project_id = self.overleaf_project.currentData()
        if not project_id:
            return
        self.refresh.setEnabled(False)
        self.overleaf_status.setText('Reading the Overleaf project…')

        def done(folders, error):
            self.refresh.setEnabled(True)
            if error:
                self.overleaf_status.setText(error)
                return
            current = self.overleaf_folder.currentText()
            self.overleaf_folder.clear()
            for folder in folders:
                self.overleaf_folder.addItem(folder or '(project root)', folder)
            index = self.overleaf_folder.findText(current)
            self.overleaf_folder.setCurrentIndex(index if index >= 0 else 0)
            self.overleaf_status.setText(f'{len(folders)} folder(s). Type a new name to create one.')
        run_in_thread(lambda: overleaf.OverleafClient().folders(project_id), done, self)

    def _accept(self):
        chosen = self.targets()
        if not any(chosen.get(k) for k in ('folder', 'latex', 'slides', 'overleaf')):
            MessageDialog.information(self, 'Send to', 'Choose at least one destination.')
            return
        if self.overleaf_box is not None and self.overleaf_box.isChecked() and not overleaf.get_token():
            MessageDialog.warning(self, 'Overleaf', 'Add your Overleaf Git token in Settings › Documents first.')
            return
        keep = [k for k in ('folder', 'latex', 'slides', 'overleaf') if chosen.get(k)]
        changes = {'export_targets': keep}
        if chosen.get('overleaf'):
            changes['overleaf_last_project'] = chosen['overleaf']['project']
            changes['overleaf_last_folder'] = chosen['overleaf']['folder']
        doc_settings.save(changes)
        self.accept()

    def targets(self) -> dict:
        out = {'folder': bool(self.folder_box is not None and self.folder_box.isChecked())}
        if self.latex_box is not None and self.latex_box.isChecked():
            kind, value = self.latex_target.currentData() or ('choose', None)
            out['latex'] = value if kind != 'choose' else None
            out['latex_caption'] = self.latex_caption.text().strip()
        if self.slides_box is not None and self.slides_box.isChecked():
            kind, value = self.slides_target.currentData() or ('choose', None)
            out['slides'] = value if kind != 'choose' else None
            out['slides_mode'] = self.slides_mode.currentData()
        if self.overleaf_box is not None and self.overleaf_box.isChecked() and self.overleaf_project.currentData():
            folder = self.overleaf_folder.currentData()
            if folder is None or self.overleaf_folder.currentText() not in (folder, '(project root)'):
                folder = self.overleaf_folder.currentText().strip()
                if folder == '(project root)':
                    folder = ''
            out['overleaf'] = {'project': self.overleaf_project.currentData(), 'folder': folder}
        return out


# ---------------------------------------------------------------------------- Overleaf
def add_overleaf_project(parent) -> str | None:
    """Ask for a project address and a name; store it in the settings. Returns its id."""
    dialog = QDialog(parent)
    dialog.setWindowTitle('Add an Overleaf project')
    form = QFormLayout(dialog)
    url = QLineEdit()
    url.setPlaceholderText('https://www.overleaf.com/project/…')
    name = QLineEdit()
    name.setPlaceholderText('Name shown in SPM Studio')
    form.addRow(_hint('Open the project on Overleaf and copy the address from the browser.'))
    form.addRow('Address', url)
    form.addRow('Name', name)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    form.addRow(box)
    while dialog.exec() == QDialog.DialogCode.Accepted:
        try:
            project_id = overleaf.project_id_from_url(url.text())
        except overleaf.OverleafError as exc:
            MessageDialog.warning(parent, 'Overleaf', str(exc))
            continue
        conf = doc_settings.load()
        projects = [p for p in conf['overleaf_projects'] if p.get('id') != project_id]
        projects.append({'id': project_id, 'name': name.text().strip() or project_id,
                         'url': overleaf.project_page(project_id, conf)})
        doc_settings.save({'overleaf_projects': projects})
        return project_id
    return None


def choose_overleaf_project(parent) -> str | None:
    conf = doc_settings.load()
    dialog = QDialog(parent)
    dialog.setWindowTitle('Overleaf project')
    dialog.setMinimumWidth(460)
    layout = QVBoxLayout(dialog)
    layout.addWidget(_hint('Choose the Overleaf project, or add one by its address.'))
    items = QListWidget()
    for entry in conf['overleaf_projects']:
        item = QListWidgetItem(f"{entry.get('name') or entry['id']}   —   {entry['id']}")
        item.setData(Qt.ItemDataRole.UserRole, entry['id'])
        items.addItem(item)
    if items.count():
        items.setCurrentRow(0)
    layout.addWidget(items, 1)
    add = QPushButton('Add a project…')
    layout.addWidget(add)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    chosen = {}

    def added():
        project_id = add_overleaf_project(dialog)
        if project_id:
            chosen['id'] = project_id
            dialog.accept()
    add.clicked.connect(added)
    items.itemDoubleClicked.connect(lambda _i: dialog.accept())
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    if chosen.get('id'):
        return chosen['id']
    item = items.currentItem()
    return item.data(Qt.ItemDataRole.UserRole) if item else None
