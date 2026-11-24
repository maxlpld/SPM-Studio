from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QListWidget,QLineEdit,QTabWidget,QLabel,QPushButton,QMenu,QSizePolicy,QFrame,QToolButton
from PySide6.QtCore import Signal,Qt
from .metadata_panel import MetadataPanel

class BrowserPanel(QWidget):
    fileSelected=Signal(str)
    moduleSelected=Signal(str)
    removeRequested=Signal(str)
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
        self.file_search=QLineEdit()
        self.file_search.setPlaceholderText('Search scans')
        self.file_search.setClearButtonEnabled(True)
        self.files=QListWidget()
        self.files.setAlternatingRowColors(False)
        fl.addWidget(self.file_search)
        fl.addWidget(self.files)
        actions=QHBoxLayout()
        actions.setContentsMargins(0,0,0,0)
        self.file_count=QLabel('')
        self.file_count.setObjectName('hint')
        self.remove_file_button=QPushButton('Remove')
        self.remove_file_button.setToolTip('Remove from the current session only; the file on disk is never deleted (Delete key).')
        self.remove_file_button.clicked.connect(self.request_remove_selected)
        self.remove_file_button.setEnabled(False)
        self.export_selection_button=QPushButton('Copy to recap folder…')
        self.export_selection_button.setObjectName('ExportScanSelectionV26')
        self.export_selection_button.setToolTip('Copy every scan still listed here into a folder you choose (location and '
                                                'name; a new folder is created) and continue working in that folder '
                                                '(exports and script results are saved there). Nothing is deleted.')
        self.export_selection_button.clicked.connect(self.exportSelectionRequested.emit)
        self.export_selection_button.setEnabled(False)
        # Both commands also exist in File and in the right-click menu: one compact '…' here.
        self.file_menu=QMenu(self)
        self._remove_action=self.file_menu.addAction('Remove from list (file kept on disk)',self.request_remove_selected)
        self._recap_action=self.file_menu.addAction('Copy listed scans to a folder…',self.exportSelectionRequested.emit)
        self._recap_action.setToolTip('Choose the location and the name of the folder')
        self.more_button=QToolButton()
        self.more_button.setObjectName('FilesMoreV08')
        self.more_button.setProperty('flat',True);self.more_button.setProperty('iconOnly',True)
        self.more_button.setToolTip('More')
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_button.setMenu(self.file_menu)
        try:
            from spm_studio.shared.appearance import set_icon
            set_icon(self.more_button,'more')
        except Exception:
            self.more_button.setText('…')
        self.more_button.setStyleSheet('QToolButton::menu-indicator{image:none;width:0;}')
        actions.addWidget(self.file_count,1)
        actions.addWidget(self.more_button)
        self.remove_file_button.hide();self.export_selection_button.hide()
        self.remove_file_button.setParent(files);self.export_selection_button.setParent(files)
        fl.addLayout(actions)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._file_context_menu)
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

    def update_selection_actions(self):
        count=self.files.count()
        self.export_selection_button.setEnabled(count>0)
        self._recap_action.setEnabled(count>0)
        self._remove_action.setEnabled(self.files.currentItem() is not None)
        self.file_count.setText(f'{count} scan' + ('s' if count!=1 else '') if count else '')

    def _file_selection_changed(self,item,_previous):
        self.remove_file_button.setEnabled(item is not None)
        self.update_selection_actions()
        if item is not None:
            self.fileSelected.emit(item.data(Qt.ItemDataRole.UserRole))

    def request_remove_selected(self):
        item=self.files.currentItem()
        if item is not None:
            self.removeRequested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _file_context_menu(self,pos):
        item=self.files.itemAt(pos)
        if item is None:
            return
        menu=QMenu(self)
        action=menu.addAction('Remove from list (file kept on disk)')
        if menu.exec(self.files.viewport().mapToGlobal(pos))==action:
            self.removeRequested.emit(item.data(Qt.ItemDataRole.UserRole))

    def select_relative_file(self,offset:int)->bool:
        """Navigate visible scans in the current session, not hidden search results."""
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
        self.files.setCurrentItem(chosen)
        self.files.scrollToItem(chosen)
        return True
