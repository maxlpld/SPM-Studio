"""Keyboard shortcut browser and profile editor, shared by every Studio action."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QFileSystemWatcher, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,
    QLineEdit,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,
    QHeaderView,QFileDialog,QInputDialog,QMessageBox,QKeySequenceEdit,QWidget)
from spm_studio.shared.dialogs import MessageDialog as QMessageBox, TextInputDialog as QInputDialog
from spm_studio.shared.ui_strings import ui_label, add_key_items, combo_key, set_combo_key
from ..core.shortcuts import (ACTIONS,DEFAULT_BINDINGS,ShortcutConfigError,
    load_profile,write_profile,validate_profile,default_profile,read_profiles)


def normalize_key(value:str)->str:
    """Reject unusable Qt sequences and store normalized portable names."""
    if not value.strip():return ''
    seq=QKeySequence.fromString(value,QKeySequence.SequenceFormat.PortableText)
    clean=seq.toString(QKeySequence.SequenceFormat.PortableText)
    if seq.isEmpty() or not clean or seq.count()!=1:
        raise ShortcutConfigError(f'Invalid or multi-stroke shortcut: {value!r}; use one key combination')
    return clean


class ShortcutOptions(QDialog):
    """Edits only JSON key bindings; action labels are generated from ACTIONS."""
    bindingsChanged=Signal(str,dict)

    def __init__(self,folder:Path,active:str,parent=None):
        super().__init__(parent)
        self.folder=Path(folder)
        self.setWindowTitle('Keyboard shortcuts')
        self.resize(860,680)
        self.setMinimumSize(660,460)
        self._profiles={}
        self._current=active
        self._loading=False
        root=QVBoxLayout(self)
        top=QHBoxLayout()
        top.addWidget(QLabel('Shortcut profile'))
        self.profile_choice=QComboBox()
        top.addWidget(self.profile_choice,1)
        self.new_profile=QPushButton('Save as…')
        self.import_button=QPushButton('Import…')
        self.export_button=QPushButton('Export…')
        self.reset_all_button=QPushButton('Restore defaults')
        for b in (self.new_profile,self.import_button,self.export_button,self.reset_all_button):top.addWidget(b)
        root.addLayout(top)
        self.search=QLineEdit()
        self.search.setPlaceholderText('Search action, category, shortcut or description…')
        root.addWidget(self.search)
        self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['Category','Action','Shortcut','Description'])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table,1)
        editor=QHBoxLayout()
        editor.addWidget(QLabel('Selected action:'))
        self.selected_label=QLabel('Select an action above')
        editor.addWidget(self.selected_label,1)
        self.key_editor=QKeySequenceEdit()
        self.key_editor.setToolTip('Click, then press a shortcut (e.g. Ctrl+Alt+J). A blank shortcut disables it.')
        editor.addWidget(self.key_editor)
        self.assign=QPushButton('Assign')
        self.clear_button=QPushButton('Unbind')
        self.reset_button=QPushButton('Default')
        for b in (self.assign,self.clear_button,self.reset_button):editor.addWidget(b)
        root.addLayout(editor)
        self.info=QLabel('Saved and applied immediately.')
        self.info.setObjectName('hint')
        self.info.setWordWrap(True)
        root.addWidget(self.info)
        bottom=QHBoxLayout()
        bottom.addStretch(1)
        self.close_button=QPushButton('Close')
        self.close_button.clicked.connect(self.accept)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)
        self.profile_choice.currentIndexChanged.connect(lambda _:self._choose_profile(combo_key(self.profile_choice)))
        self.search.textChanged.connect(self._filter)
        self.table.itemSelectionChanged.connect(self._selected)
        self.assign.clicked.connect(self._assign)
        self.clear_button.clicked.connect(lambda:self._set_selected_binding(''))
        self.reset_button.clicked.connect(self._reset_selected)
        self.reset_all_button.clicked.connect(self._reset_all)
        self.new_profile.clicked.connect(self._save_as)
        self.import_button.clicked.connect(self.import_file)
        self.export_button.clicked.connect(self.export_file)
        self.reload_profiles(active)
        self._watcher=QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule_external_reload)
        self._watcher.fileChanged.connect(self._schedule_external_reload)
        self._reload_timer=QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(220)
        self._reload_timer.timeout.connect(self._external_reload)
        self._watch_files()

    def _schedule_external_reload(self,*unused):
        self._reload_timer.start()

    def _watch_files(self):
        if not hasattr(self,'_watcher'):return
        wanted={str(self.folder)}
        wanted.update(str(file) for file in self.folder.glob('*.json'))
        existing=set(self._watcher.files()+self._watcher.directories())
        if existing-wanted:self._watcher.removePaths(sorted(existing-wanted))
        if wanted-existing:self._watcher.addPaths(sorted(wanted-existing))

    def _external_reload(self):
        self.reload_profiles(self._current)

    def reload_profiles(self,preferred=None):
        self._profiles=read_profiles(self.folder,canonicalize=normalize_key)
        choice=preferred or self._current
        if choice not in self._profiles:choice='default'
        self._loading=True
        self.profile_choice.clear()
        add_key_items(self.profile_choice,sorted(self._profiles))
        set_combo_key(self.profile_choice,choice)
        self._loading=False
        self._choose_profile(choice)
        self._watch_files()

    def _choose_profile(self,name):
        if self._loading or name not in self._profiles:return
        self._current=name
        self._update_table()
        self.bindingsChanged.emit(name,self._profiles[name]['bindings'].copy())

    def _update_table(self):
        old=self._current_id()
        bindings=self._profiles[self._current]['bindings']
        self.table.blockSignals(True)
        self.table.setRowCount(len(ACTIONS))
        for i,action in enumerate(ACTIONS):
            for col,text in enumerate((action.category,action.label,bindings[action.id] or '—',action.help)):
                item=QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole,action.id)
                self.table.setItem(i,col,item)
            self.table.setRowHidden(i,False)
        self.table.blockSignals(False)
        self._filter(self.search.text())
        if old:
            for r in range(self.table.rowCount()):
                if self.table.item(r,0).data(Qt.ItemDataRole.UserRole)==old:
                    self.table.selectRow(r);break
        self._selected()

    def _filter(self,query):
        s=query.casefold().strip()
        for r in range(self.table.rowCount()):
            matches=any(s in self.table.item(r,c).text().casefold() for c in range(4))
            self.table.setRowHidden(r,not matches)

    def _current_id(self):
        r=self.table.currentRow()
        if r<0 or not self.table.item(r,0):return None
        return self.table.item(r,0).data(Qt.ItemDataRole.UserRole)

    def _selected(self):
        action_id=self._current_id()
        enabled=action_id is not None
        for w in (self.key_editor,self.assign,self.clear_button,self.reset_button):w.setEnabled(enabled)
        if not enabled:
            self.selected_label.setText('Select an action above')
            return
        action=next(a for a in ACTIONS if a.id==action_id)
        self.selected_label.setText(action.label)
        self.key_editor.setKeySequence(QKeySequence(self._profiles[self._current]['bindings'][action_id]))

    def _set_selected_binding(self,value):
        action_id=self._current_id()
        if action_id is None:return
        new=self._profiles[self._current]['bindings'].copy()
        new[action_id]=value
        proposed={'schema_version':1,'name':self._current,'bindings':new}
        try:
            valid=write_profile(self.folder/f'{self._current}.json',proposed,canonicalize=normalize_key)
        except (ShortcutConfigError,OSError,ValueError) as exc:
            QMessageBox.warning(self,'Shortcut conflict or error',str(exc))
            self._selected()
            return
        self._profiles[self._current]=valid
        self._update_table()
        self.bindingsChanged.emit(self._current,valid['bindings'].copy())

    def _assign(self):
        self._set_selected_binding(self.key_editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def _reset_selected(self):
        action_id=self._current_id()
        if action_id:self._set_selected_binding(DEFAULT_BINDINGS[action_id])

    def _reset_all(self):
        reply=QMessageBox.question(self,'Restore default shortcuts?',
                    f'Replace all shortcuts in profile "{ui_label(self._current)}" with the defaults?',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
        if reply!=QMessageBox.StandardButton.Yes:return
        try:
            valid=write_profile(self.folder/f'{self._current}.json',
                                default_profile(self._current),canonicalize=normalize_key)
        except (ShortcutConfigError,OSError) as exc:
            QMessageBox.warning(self,'Cannot reset shortcuts',str(exc));return
        self._profiles[self._current]=valid
        self._update_table()
        self.bindingsChanged.emit(self._current,valid['bindings'].copy())

    def _save_as(self):
        name,ok=QInputDialog.getText(self,'New shortcut profile','Profile name:')
        if not ok:return
        new={'schema_version':1,'name':name.strip(),'bindings':self._profiles[self._current]['bindings'].copy()}
        dest=self.folder/f'{name.strip()}.json'
        if dest.exists():
            QMessageBox.warning(self,'Profile exists','Choose another profile name.');return
        try:write_profile(dest,new,canonicalize=normalize_key)
        except (ShortcutConfigError,OSError) as exc:
            QMessageBox.warning(self,'Invalid profile',str(exc));return
        self.reload_profiles(new['name'])

    def import_file(self):
        selected,_=QFileDialog.getOpenFileName(self,'Import shortcuts',str(Path.home()),'JSON (*.json)')
        if not selected:return
        try:
            loaded=load_profile(selected,canonicalize=normalize_key)
            target=self.folder/f'{loaded["name"]}.json'
            if target.exists():
                raise ShortcutConfigError(f'Profile {loaded["name"]} exists; rename the imported profile or use Save as')
            write_profile(target,loaded,canonicalize=normalize_key)
        except (ShortcutConfigError,OSError) as exc:
            QMessageBox.warning(self,'Cannot import shortcuts',str(exc));return
        self.reload_profiles(loaded['name'])

    def export_file(self):
        proposed=self._current+'.json'
        destination,_=QFileDialog.getSaveFileName(self,'Export shortcuts',str(Path.home()/proposed),'JSON (*.json)')
        if not destination:return
        try:
            write_profile(Path(destination),self._profiles[self._current],canonicalize=normalize_key)
        except (ShortcutConfigError,OSError) as exc:
            QMessageBox.warning(self,'Cannot export shortcuts',str(exc))
