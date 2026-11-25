from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QListWidget,QLineEdit,QTabWidget,QLabel,QPushButton,
                               QMenu,QSizePolicy,QFrame,QToolButton,QAbstractItemView)
from PySide6.QtCore import Signal,Qt,QItemSelectionModel
from .metadata_panel import MetadataPanel

class BrowserPanel(QWidget):
    fileSelected=Signal(str)
    moduleSelected=Signal(str)
    removeRequested=Signal(str)
    removeManyRequested=Signal(list)       # v0.0.20: several scans at once
    clearRequested=Signal()                # v0.0.20: empty the list
    exportSelectionRequested=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        outer=QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        # A narrow QTabBar silently hides its last tab behind scroll arrows.
        # Permanent, equal-width controls keep Metadata accessible even on a
        # small/saved sidebar width (the original v9 user-reported failure).
        outer.setSpacing(6)
        self.tabs=QTabWidget()
        # v0.8: one segmented control (equal widths, never hidden behind scroll arrows).
        segmented=QFrame();segmented.setObjectName('segmented')
        self.tab_navigation=QHBoxLayout(segmented)
        self.tab_navigation.setSpacing(2)
        self.tab_navigation.setContentsMargins(2,2,2,2)
        self.tab_buttons=[]
        for index,label in enumerate(('Files','Tools','Metadata')):
            button=QPushButton(label)
            button.setObjectName('Sidebar'+label+'Button')
            button.setCheckable(True)
            button.setProperty('segment',True)
            # v0.0.18: equal widths but never narrower than the label (no clipped "Metadata")
            bold=button.font();bold.setBold(True)
            from PySide6.QtGui import QFontMetrics
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(label)+30)   # v0.0.19: room for bold/pill
            button.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False,i=index:self.tabs.setCurrentIndex(i))
            self.tab_buttons.append(button)
            self.tab_navigation.addWidget(button,1)
        outer.addWidget(segmented)
        self.tabs.tabBar().hide()
        self.tabs.currentChanged.connect(self._update_navigation)
        outer.addWidget(self.tabs)
        files=QWidget()
        fl=QVBoxLayout(files)
        fl.setContentsMargins(0,0,0,0);fl.setSpacing(6)
        self.project_holder=QVBoxLayout()       # v0.0.20: the project tabs are placed here by the main window
        self.project_holder.setContentsMargins(0,0,0,0)
        fl.addLayout(self.project_holder)
        self.file_search=QLineEdit()
        self.file_search.setPlaceholderText('Search scans')
        self.file_search.setClearButtonEnabled(True)
        self.files=QListWidget()
        self.files.setObjectName('ScanFilesV0020')
        self.files.setAlternatingRowColors(False)
        # v0.0.20: several scans can be selected (Ctrl/Shift + click, or hold Shift, browse with ↑/↓ and press
        # Enter on each scan to pick it); the scan shown is the current one, in bold.
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setToolTip('↑/↓ browse the scans. To select several: hold Shift, browse with ↑/↓ and press '
                              'Enter on each scan you want (or Ctrl+click); release Shift, then Delete removes them '
                              'from the list. Files on disk are never deleted.')
        fl.addWidget(self.file_search)
        fl.addWidget(self.files)
        self.mark_hint=QLabel('')
        self.mark_hint.setObjectName('hint')
        self.mark_hint.setWordWrap(True)
        self.mark_hint.hide()
        fl.addWidget(self.mark_hint)
        actions=QHBoxLayout()
        actions.setContentsMargins(0,0,0,0)
        actions.setSpacing(2)
        self.file_count=QLabel('')
        self.file_count.setObjectName('hint')
        from spm_studio.shared.appearance import tool_button
        # v0.0.20: the commands are visible pictogram buttons (no "…" menu any more)
        self.export_selection_button=tool_button('','copy_to','Copy the selected scans (or all listed scans when '
                                                 'only one is shown) into a folder you choose and continue working '
                                                 'there. Originals are never moved.',icon_only=True)
        self.export_selection_button.setObjectName('ExportScanSelectionV26')
        self.export_selection_button.setAccessibleName('Copy scans to a folder')
        self.export_selection_button.clicked.connect(self.exportSelectionRequested.emit)
        self.export_selection_button.setEnabled(False)
        self.remove_file_button=tool_button('','trash','Remove the selected scan(s) from the list (Delete key). '
                                            'The files on disk are never deleted.',icon_only=True)
        self.remove_file_button.setObjectName('RemoveSelectedScansV0020')
        self.remove_file_button.setAccessibleName('Remove selected scans from the list')
        self.remove_file_button.clicked.connect(self.request_remove_selected)
        self.remove_file_button.setEnabled(False)
        self.clear_files_button=tool_button('','clear_list','Remove every scan from the list (files on disk are '
                                            'kept)',icon_only=True)
        self.clear_files_button.setObjectName('ClearScanListV0020')
        self.clear_files_button.setAccessibleName('Clear the scan list')
        self.clear_files_button.clicked.connect(self.clearRequested.emit)
        self.clear_files_button.setEnabled(False)
        actions.addWidget(self.file_count,1)
        actions.addWidget(self.export_selection_button)
        actions.addWidget(self.remove_file_button)
        actions.addWidget(self.clear_files_button)
        # Kept for the right-click menu and compatibility.
        self.file_menu=QMenu(self)
        self._remove_action=self.file_menu.addAction('Remove selected from list (files kept on disk)',
                                                     self.request_remove_selected)
        self._recap_action=self.file_menu.addAction('Copy scans to a folder…',self.exportSelectionRequested.emit)
        self._recap_action.setToolTip('Choose the location and the name of the folder')
        self._clear_action=self.file_menu.addAction('Clear the list',self.clearRequested.emit)
        fl.addLayout(actions)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._file_context_menu)
        self._marking=False                    # Shift held and scans picked with Enter
        self._explicit_marks=False
        self._bold_item=None
        self.tabs.addTab(files,'Files')
        tools=QWidget()
        tl=QVBoxLayout(tools)
        tl.setContentsMargins(0,0,0,0);tl.setSpacing(6)
        self.tool_search=QLineEdit()
        self.tool_search.setPlaceholderText('Search tools')
        self.tool_search.setClearButtonEnabled(True)
        self.tools=QListWidget()
        tl.addWidget(self.tool_search)
        tl.addWidget(self.tools)
        self.tabs.addTab(tools,'Tools')
        self.metadata_panel=MetadataPanel()
        self.tabs.addTab(self.metadata_panel,'Metadata')
        self._update_navigation(0)
        self.file_search.textChanged.connect(lambda s:self._filter(self.files,s))
        self.tool_search.textChanged.connect(lambda s:self._filter(self.tools,s))
        self.files.currentItemChanged.connect(self._file_selection_changed)
        self.files.itemSelectionChanged.connect(self._selection_changed)
        self.tools.currentItemChanged.connect(lambda item,_:self.moduleSelected.emit(item.data(Qt.ItemDataRole.UserRole)) if item else None)

    def _update_navigation(self,index):
        for position,button in enumerate(self.tab_buttons):
            button.setChecked(position==index)
        self.tab_buttons[2].setToolTip('Show ALL available instrument metadata for the selected scan')

    def show_metadata(self):
        self.tabs.setCurrentWidget(self.metadata_panel)

    @staticmethod
    def _filter(widget,text):
        for n in range(widget.count()):
            item=widget.item(n)
            item.setHidden(text.lower() not in item.text().lower())

    def set_project_tabs(self,tabs):
        self.project_holder.addWidget(tabs)

    # ------------------------------------------------------------------ selection (v0.0.20)
    def selected_paths(self)->list:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]

    def marked_paths(self)->list:
        """The scans picked for a group command: the selection, or the current scan."""
        chosen=self.selected_paths()
        if chosen:
            return chosen
        item=self.files.currentItem()
        return [item.data(Qt.ItemDataRole.UserRole)] if item is not None else []

    def update_selection_actions(self):
        count=self.files.count()
        chosen=len(self.files.selectedItems())
        self.export_selection_button.setEnabled(count>0)
        self.clear_files_button.setEnabled(count>0)
        self.remove_file_button.setEnabled(bool(chosen) or self.files.currentItem() is not None)
        self._recap_action.setEnabled(count>0)
        self._clear_action.setEnabled(count>0)
        self._remove_action.setEnabled(bool(chosen) or self.files.currentItem() is not None)
        text=f'{count} scan' + ('s' if count!=1 else '') if count else ''
        if chosen>1:
            text+=f' · {chosen} selected'
        self.file_count.setText(text)
        self.remove_file_button.setToolTip(
            (f'Remove the {chosen} selected scans from the list' if chosen>1 else
             'Remove the selected scan from the list')+' (Delete key). The files on disk are never deleted.')
        self._show_marks()

    def _show_marks(self):
        """A check mark on every selected scan when more than one is (or while picking with Shift)."""
        selected=self.files.selectedItems()
        many=self._marking or self._explicit_marks or len(selected)>1
        want=set(map(id,selected)) if many else set()
        have=getattr(self,'_iconed',{})
        if want or have:
            from PySide6.QtGui import QIcon
            if getattr(self,'_check_icon',None) is None:
                try:
                    from spm_studio.shared.appearance import icon
                    self._check_icon=icon('check')
                except Exception:
                    self._check_icon=QIcon()
            for key,item in list(have.items()):
                if key not in want:
                    try:item.setIcon(QIcon())
                    except RuntimeError:pass
                    have.pop(key,None)
            for item in selected:
                if id(item) in want and id(item) not in have:
                    item.setIcon(self._check_icon)
                    have[id(item)]=item
            self._iconed=have
        chosen=len(self.files.selectedItems())
        if self._marking:
            self.mark_hint.setText(f'Selecting: {chosen} scan(s). ↑/↓ browse, Enter adds or removes the scan, '
                                   'release Shift when done.')
            self.mark_hint.show()
        elif many and chosen>1:
            self.mark_hint.setText(f'{chosen} scans selected — Delete (or 🗑) removes them from the list, '
                                   'Esc clears the selection.')
            self.mark_hint.show()
        else:
            self.mark_hint.hide()

    def _selection_changed(self):
        if not self._marking and len(self.files.selectedItems())<=1:
            self._explicit_marks=False
        self.update_selection_actions()

    def begin_marking(self):
        if self._marking:
            return
        self._marking=True
        if not self._explicit_marks:
            blocked=self.files.blockSignals(True)
            self.files.clearSelection()           # only the scans picked with Enter count
            self.files.blockSignals(blocked)
        self._explicit_marks=True
        self.update_selection_actions()

    def toggle_mark_current(self):
        self.begin_marking()
        index=self.files.currentIndex()
        if index.isValid():
            self.files.selectionModel().select(index,QItemSelectionModel.SelectionFlag.Toggle)
        self.update_selection_actions()

    def end_marking(self):
        if not self._marking:
            return
        self._marking=False
        if not self.files.selectedItems():
            self._explicit_marks=False
        self.update_selection_actions()

    def clear_marks(self):
        self._marking=False
        self._explicit_marks=False
        current=self.files.currentItem()
        blocked=self.files.blockSignals(True)
        self.files.clearSelection()
        if current is not None:
            current.setSelected(True)
        self.files.blockSignals(blocked)
        self.update_selection_actions()

    def _set_bold(self,item):
        previous=self._bold_item
        if previous is not None:
            try:
                font=previous.font();font.setBold(False);previous.setFont(font)
            except RuntimeError:
                pass
        if item is not None:
            font=item.font();font.setBold(True);item.setFont(font)
        self._bold_item=item

    def _file_selection_changed(self,item,_previous):
        self._set_bold(item)
        self.update_selection_actions()
        if item is not None:
            self.fileSelected.emit(item.data(Qt.ItemDataRole.UserRole))

    def request_remove_selected(self):
        chosen=self.selected_paths()
        if len(chosen)>1:
            self.removeManyRequested.emit(chosen)
            return
        item=self.files.currentItem()
        if chosen:
            self.removeRequested.emit(chosen[0])
        elif item is not None:
            self.removeRequested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _file_context_menu(self,pos):
        item=self.files.itemAt(pos)
        if item is not None and not item.isSelected():
            self.files.setCurrentItem(item)
        self.update_selection_actions()
        self.file_menu.exec(self.files.viewport().mapToGlobal(pos))

    def select_relative_file(self,offset:int,keep_marks:bool=False)->bool:
        """Navigate visible scans in the current session, not hidden search results.

        ``keep_marks`` (Shift held, v0.0.20): move to the scan without changing the selection."""
        visible=[self.files.item(i) for i in range(self.files.count())
                 if not self.files.item(i).isHidden()]
        if not visible:
            return False
        current=self.files.currentItem()
        if current not in visible:
            chosen=visible[0 if offset>=0 else -1]
        else:
            idx=visible.index(current)+int(offset)
            if idx<0 or idx>=len(visible):
                return False
            chosen=visible[idx]
        if keep_marks:
            self.files.selectionModel().setCurrentIndex(self.files.indexFromItem(chosen),
                                                        QItemSelectionModel.SelectionFlag.NoUpdate)
        else:
            self.files.setCurrentItem(chosen)
        self.files.scrollToItem(chosen)
        return True
