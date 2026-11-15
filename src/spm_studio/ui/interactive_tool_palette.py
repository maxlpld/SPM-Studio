"""Gwyddion-inspired native interactive tool palette + live numerical previews.

No Qt tool pretends to be a direct plug-in to the external Gwyddion program.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,
    QPushButton,QToolButton,QButtonGroup,QPlainTextEdit,QDoubleSpinBox,QFormLayout,QGroupBox)
from .live_analysis import LivePlot
from ..core.interactive_tools import TOOLS, TOOL_BY_ID


ACTIONS = {
    'three_point':'Apply 3-point level',
    'path_level':'Apply path level',
    'crop':'Crop selected region',
    'mask':'Add rectangle to mask',
    'grain_remove':'Remove mask grain',
    'spot_remove':'Repair selected spot',
    'color_range':'Apply selected contrast',
    'filter':'Apply Gaussian filter',
}


class InteractiveToolPalette(QWidget):
    toolSelected=Signal(str)
    actionRequested=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._id='navigate'
        self._ready=False
        layout=QVBoxLayout(self); layout.setContentsMargins(10,10,10,10);layout.setSpacing(8)
        # v0.8: no instruction paragraphs; each pictogram explains itself on hover.
        tool_box=QGroupBox('Tools')
        tool_box.setToolTip('Choose a tool, then click or drag on the scan; results update live.')
        grid=QGridLayout(tool_box);grid.setContentsMargins(10,8,10,10);grid.setSpacing(4)
        self.buttons={}
        self.group=QButtonGroup(self);self.group.setExclusive(True)
        for i,tool in enumerate(TOOLS):
            btn=QToolButton()
            # Only the pictogram is visible; the full operation name appears
            # when hovering or using accessibility navigation.
            btn.setText(tool.symbol)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setCheckable(True)
            btn.setMinimumSize(36,32)
            btn.setToolTip(f'{tool.label}\n{tool.instructions}')
            btn.setAccessibleName(tool.label)
            f=btn.font();f.setPointSize(15);btn.setFont(f)
            grid.addWidget(btn,i//6,i%6)
            self.group.addButton(btn)
            btn.clicked.connect(lambda checked=False, name=tool.identifier:self.select(name))
            self.buttons[tool.identifier]=btn
        self.buttons['navigate'].setChecked(True)
        layout.addWidget(tool_box)
        self.heading=QLabel('Navigate / move')
        self.heading.setObjectName('heading')
        layout.addWidget(self.heading)
        self.help=QLabel(TOOL_BY_ID[self._id].instructions);self.help.setWordWrap(True)
        self.help.setObjectName('hint')
        layout.addWidget(self.help)
        self.results=QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMinimumHeight(110)
        self.results.setMaximumHeight(145)
        self.results.setPlaceholderText('Measurements appear here')
        layout.addWidget(self.results)
        self.plot=LivePlot()
        self.plot.setMinimumHeight(190)
        self.plot.setMaximumHeight(190)
        self.plot.setVisible(False)
        layout.addWidget(self.plot)
        options=QFormLayout()
        self.filter_sigma=QDoubleSpinBox()
        self.filter_sigma.setRange(0.1,40.0)
        self.filter_sigma.setDecimals(2)
        self.filter_sigma.setSingleStep(0.25)
        self.filter_sigma.setValue(1.0)
        self.filter_sigma.setSuffix(' px')
        self.filter_sigma.valueChanged.connect(lambda *_:self.actionRequested.emit('preview'))
        self.filter_sigma_label=QLabel('Gaussian σ')
        options.addRow(self.filter_sigma_label,self.filter_sigma)
        layout.addLayout(options)
        self.apply=QPushButton('Apply')
        self.apply.setProperty('primary',True)
        self.apply.clicked.connect(lambda:self.actionRequested.emit('apply'))
        layout.addWidget(self.apply)
        self.crop_others=QPushButton('Crop all channels')
        self.crop_others.setToolTip('Crop other acquisition channels at the same physical position. Future channels inherit the crop automatically.')
        self.crop_others.clicked.connect(lambda:self.actionRequested.emit('crop_all'))
        layout.addWidget(self.crop_others)
        self.crop_reset=QPushButton('Reset crop')
        self.crop_reset.clicked.connect(lambda:self.actionRequested.emit('crop_reset'))
        layout.addWidget(self.crop_reset)
        self._crop_active=False
        more=QHBoxLayout()
        for label,key in [('Subtract mask','subtract_mask'),('Invert','invert_mask'),('Clear mask','clear_mask')]:
            b=QPushButton(label)
            b.clicked.connect(lambda checked=False, action=key:self.actionRequested.emit(action))
            more.addWidget(b)
            setattr(self,key,b)
        layout.addLayout(more)
        self.clear_selection=QPushButton('Clear selection')
        self.clear_selection.clicked.connect(lambda:self.actionRequested.emit('clear_selection'))
        layout.addWidget(self.clear_selection)
        layout.addStretch(1)
        self._refresh_controls()

    @property
    def current(self):
        return self._id

    def select(self, identifier):
        if identifier not in TOOL_BY_ID:raise ValueError('Unknown interactive tool')
        self._id=identifier
        self.buttons[identifier].setChecked(True)
        tool=TOOL_BY_ID[identifier]
        self.heading.setText(tool.label)
        self.help.setText(tool.instructions)
        self.results.setPlainText('')
        self.plot.setVisible(False)
        self._ready=False
        self._refresh_controls()
        self.toolSelected.emit(identifier)

    def set_crop_active(self, active: bool):
        self._crop_active=bool(active)
        self._refresh_controls()

    def _refresh_controls(self):
        self.filter_sigma.setVisible(self._id=='filter')
        self.filter_sigma_label.setVisible(self._id=='filter')
        self.apply.setVisible(self._id in ACTIONS)
        self.apply.setText(ACTIONS.get(self._id,'Apply'))
        self.apply.setEnabled(self._ready)
        # Crop all / Reset crop live once, in the image toolbar's Crop menu (v0.8).
        self.crop_others.setVisible(False)
        self.crop_others.setEnabled(self._crop_active)
        self.crop_reset.setVisible(False)
        self.crop_reset.setEnabled(self._crop_active)
        for key in ('subtract_mask','invert_mask','clear_mask'):
            getattr(self,key).setVisible(self._id in ('mask','grain_remove','grain_measure'))

    def show_results(self, result, *, ready=False):
        self._ready=bool(ready)
        self.apply.setEnabled(self._ready)
        self.results.setPlainText('\n'.join(result.get('lines',[])))
        series=result.get('series',[])
        self.plot.setVisible(bool(series))
        if series:
            # The existing lightweight chart is read-only here: the Gwyddion
            # selection itself is edited directly on the image preview.
            self.plot.profiles(series)
            self.plot.title=self.heading.text()+' · live preview'
