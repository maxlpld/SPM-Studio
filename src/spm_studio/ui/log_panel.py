from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPlainTextEdit,QPushButton,QProgressBar,QListWidget,QLabel,QTabWidget
from PySide6.QtCore import Signal

class LogPanel(QWidget):
    cancelRequested=Signal()
    resultChosen=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(8,6,8,8)
        layout.setSpacing(6)
        header=QHBoxLayout()
        self.state=QLabel('Idle')
        self.state.setObjectName('muted')
        self.progress=QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setMaximumWidth(160)
        self.progress.setValue(0)
        self.cancel=QPushButton('Cancel')
        self.cancel.setProperty('destructive',True)
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancelRequested)
        header.addWidget(self.state)
        header.addStretch(1)
        header.addWidget(self.progress)
        header.addWidget(self.cancel)
        layout.addLayout(header)
        tabs=QTabWidget()
        self.logs=QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(3000)
        from PySide6.QtGui import QFontDatabase
        self.logs.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.outputs=QListWidget()
        self.outputs.itemDoubleClicked.connect(lambda item:self.resultChosen.emit(item.data(0x0100)))
        self.logs.setAccessibleName('Analysis logs')
        self.outputs.setAccessibleName('Analysis output files')
        self.outputs.setToolTip('Double-click a file to open it.')
        tabs.addTab(self.logs,'Logs')
        tabs.addTab(self.outputs,'Results')
        layout.addWidget(tabs)
        self.tabs=tabs

    def add_log(self,text):
        self.logs.appendPlainText(text.rstrip('\n'))
