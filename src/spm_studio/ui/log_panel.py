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
        # v0.0.5: wide and tall enough to read at a glance (was a 160 px hairline).
        self.progress.setObjectName('LogRunProgressV005')
        self.progress.setProperty('role','activity')
        self.progress.setMinimumWidth(220)
        self.progress.setMaximumWidth(420)
        self.progress.setTextVisible(True)
        self.progress.setFormat('%p %')
        self.progress.setValue(0)
        self.cancel=QPushButton('Cancel')
        self.cancel.setProperty('destructive',True)
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancelRequested)
        header.addWidget(self.state,1)
        header.addWidget(self.progress,2)
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
