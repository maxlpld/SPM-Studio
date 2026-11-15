"""Reusable compact controls for channel, non-destructive steps, and display style."""
from __future__ import annotations
from dataclasses import asdict
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,QGroupBox,QComboBox,
 QLineEdit,QCheckBox,QDoubleSpinBox,QSpinBox,QPushButton,QToolButton,QSizePolicy,QListWidget,QListWidgetItem,QTextEdit,QLabel, QGridLayout, QInputDialog)
from ..core.models import ImageStyle, ProcessingStep
from spm_studio.shared.ui_strings import ui_label, add_key_items, combo_key, set_combo_key

from ..core.processing import PROCESS_GROUPS, OPERATIONS, DEFAULT_PARAMETERS

# Compact, language-neutral pictograms for the existing processing operations.
# Only the buttons change: operation identifiers and numerical algorithms do not.
PROCESSING_PICTOGRAMS = {
    'plane': '▱',
    'row_median': '≋',
    'fix_zero': '⓪',
    'zero_mean': '⊖',
    'subtract_median': '−',
    'row_mean': '⇥',
    'column_median': '⋮',
    'column_mean': '⇣',
    'line_poly': '∿',
    'polynomial_2d': '▦',
    'median_scar': '≠',
    'median_difference': '⇄',
    'median_difference_columns': '⇅',
    'despike': '✦',
    'remove_stripes': '▤',
    'gaussian': '◌',
    'median_filter': '▥',
    'mean_filter': '▧',
    'minimum_filter': '▽',
    'maximum_filter': '△',
    'highpass': '⤴',
    'unsharp': '✧',
    'dog': '◎',
    'laplace': '∇',
    'sobel': '◇',
    'invert': '±',
    'absolute': '‖',
    'square': '²',
    'sqrt': '√',
    'multiply': '×',
    'add': '+',
    'clip': '⊣',
    'threshold': '◐',
}

class InspectorPanel(QWidget):
    selectionChanged=Signal()
    styleChanged=Signal()
    processingChanged=Signal()
    applyAll=Signal()
    visibleChannelsChanged=Signal()
    openGwyddion=Signal()
    fixZeroRequested=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self._quiet=False
        self._steps=[]
        self.result_channels = {}
        self._physical_channel_names = []
        root=QVBoxLayout(self)
        root.setContentsMargins(10,10,10,10)
        root.setSpacing(10)
        # v0.8: most-used first (channel → display → processing → previews), no help paragraphs.
        group=QGroupBox('Channel')
        form=QFormLayout(group)
        form.setContentsMargins(10,8,10,10)
        self.channel=QComboBox()
        self.trace=QComboBox()
        form.addRow('Channel',self.channel)
        form.addRow('Trace',self.trace)
        self.channel.currentIndexChanged.connect(lambda *_: self._change_selection())
        self.trace.currentIndexChanged.connect(lambda *_: self.selectionChanged.emit() if not self._quiet else None)
        root.addWidget(group)
        display=QGroupBox('Display')
        dv=QFormLayout(display)
        dv.setContentsMargins(10,8,10,10)
        self.palette=QComboBox()
        add_key_items(self.palette,['gray','gray-inverted','viridis','magma','copper'])
        self.mode=QComboBox()
        for label,key in [('Percentile','percentile'),('Full range','full'),('Manual','manual'),('Std. deviation','sigma'),('Median abs. deviation','mad')]:
            self.mode.addItem(label,key)
        self.low=QLineEdit('1')
        self.high=QLineEdit('99')
        self.low.setToolTip('Percentile %, sigma multiple, or raw SI data value (manual)')
        self.high.setToolTip(self.low.toolTip())
        self.low.setPlaceholderText('low');self.high.setPlaceholderText('high')
        self.gamma=QDoubleSpinBox()
        self.gamma.setRange(.1,5)
        self.gamma.setDecimals(2)
        self.gamma.setSingleStep(.1)
        self.gamma.setValue(1.)
        self.scale_bar=QCheckBox('Scale bar')
        self.scale_bar.setToolTip('Physical scale bar on the scan')
        self.scale_bar.setChecked(True)
        self.colorbar=QCheckBox('Colourbar')
        self.colorbar.setChecked(True)
        range_row=QHBoxLayout();range_row.setSpacing(6)
        range_row.addWidget(self.low,1);range_row.addWidget(QLabel('–'));range_row.addWidget(self.high,1)
        toggles=QHBoxLayout();toggles.setSpacing(14)
        toggles.addWidget(self.scale_bar);toggles.addWidget(self.colorbar);toggles.addStretch(1)
        dv.addRow('Colormap',self.palette)
        dv.addRow('Contrast',self.mode)
        dv.addRow('Range',range_row)
        dv.addRow('Gamma',self.gamma)
        dv.addRow(toggles)
        for ctrl,signal in [(self.palette.currentIndexChanged,None),(self.mode.currentIndexChanged,None),
                            (self.low.editingFinished,None),(self.high.editingFinished,None),
                            (self.gamma.valueChanged,None),(self.scale_bar.toggled,None),(self.colorbar.toggled,None)]:
            ctrl.connect(lambda *_:self.styleChanged.emit() if not self._quiet else None)
        self.apply_all=QPushButton('Apply to all channels')
        self.apply_all.setToolTip('Copy these display settings to every channel of this scan; data unchanged')
        self.apply_all.clicked.connect(self.applyAll)
        dv.addRow(self.apply_all)
        root.addWidget(display)
        steps=QGroupBox('Processing')
        steps.setToolTip('Non-destructive. Click a pictogram to append a step; double-click a step to edit it. '
                         'Fix Zero only changes the colourbar labels.')
        sv=QVBoxLayout(steps)
        sv.setContentsMargins(10,8,10,10)
        sv.setSpacing(8)
        self.processing_buttons={}
        for category, commands in PROCESS_GROUPS.items():
            caption=QLabel(category)
            caption.setObjectName('sectionTitle')
            sv.addWidget(caption)
            section=QWidget(steps)
            grid=QGridLayout(section)
            grid.setContentsMargins(0,0,0,0)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(4)
            for column in range(6):
                grid.setColumnStretch(column,1)
            for i,(name, operation) in enumerate(commands):
                button=QToolButton(section)
                button.setText(PROCESSING_PICTOGRAMS[operation])
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                button.setMinimumSize(34,30)
                button.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
                font=button.font();font.setPointSize(14);button.setFont(font)
                button.setToolTip(name)
                button.setAccessibleName(name)
                button.setObjectName(f'ProcessingIcon_{operation}')
                button.clicked.connect(lambda _=False, op=operation:self._add_operation(op))
                grid.addWidget(button,i//6,i%6)
                self.processing_buttons[operation]=button
            sv.addWidget(section)
        self.step_list=QListWidget()
        self.step_list.setMaximumHeight(125)
        self.step_list.setToolTip('Steps run top to bottom. Untick to disable, double-click to edit.')
        self.step_list.itemChanged.connect(self._toggle_step)
        self.step_list.itemDoubleClicked.connect(self._edit_step)
        caption=QLabel('Pipeline');caption.setObjectName('sectionTitle')
        sv.addWidget(caption)
        sv.addWidget(self.step_list)
        row=QHBoxLayout();row.setSpacing(4)
        try:
            from spm_studio.shared.appearance import tool_button
        except Exception:
            tool_button=None
        for icon_name,label,method in [('chevron-up','Move step up',lambda:self._move_step(-1)),
                                       ('chevron-down','Move step down',lambda:self._move_step(1)),
                                       ('trash','Remove step',self._remove_step)]:
            if tool_button is not None:
                b=tool_button('',icon_name,label,icon_only=True)
            else:
                b=QPushButton({'chevron-up':'↑','chevron-down':'↓'}.get(icon_name,'Remove'))
                b.setToolTip(label)
            b.setAccessibleName(label)
            b.clicked.connect(method)
            row.addWidget(b)
        row.addStretch(1)
        full=QPushButton('Gwyddion…')
        full.setProperty('flat',True)
        full.setToolTip('Open this scan in Gwyddion for operations that are not native to Studio (changes are not imported).')
        full.clicked.connect(self.openGwyddion.emit)
        row.addWidget(full)
        sv.addLayout(row)
        root.addWidget(steps)
        multi=QGroupBox('Previews')
        multi.setToolTip('Channels shown side by side. ←/→ scroll the previews.')
        multi_layout=QVBoxLayout(multi)
        multi_layout.setContentsMargins(10,8,10,10)
        self.visible_channels=QListWidget()
        self.visible_channels.setMaximumHeight(195)
        self.visible_channels.itemChanged.connect(self._visible_changed)
        multi_layout.addWidget(self.visible_channels)
        root.addWidget(multi)
        self.metadata=QLabel('No scan loaded')
        self.metadata.setObjectName('hint')
        self.metadata.setWordWrap(True)
        self.metadata.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.metadata)
        root.addStretch(1)

    def _change_selection(self):
        if self._quiet:
            return
        self.selectionChanged.emit()

    def set_channels(self,scan,selected=None,trace=None):
        self._quiet=True
        self.channel.clear()
        self._physical_channel_names = list(scan.channels)
        self.result_channels = {}
        self.channel.addItems(self._physical_channel_names)
        if selected in scan.channels:
            self.channel.setCurrentText(selected)
        self._set_traces(scan,trace)
        self.set_visible_channels([selected] if selected else [])
        self._quiet=False

    def set_result_channels(self, mapping):
        """Virtual, read-only PDF report channels grouped with scan channels."""
        old_selection=self.channel.currentText()
        old_checked=self.visible_channel_names()
        self._quiet=True
        for i in range(self.channel.count()-1, -1, -1):
            if self.channel.itemText(i) not in self._physical_channel_names:
                self.channel.removeItem(i)
        self.result_channels=dict(mapping)
        for label, module_id in mapping.items():
            self.channel.addItem(label, ('result', module_id))
        if old_selection in self.channel_names():
            self.channel.setCurrentText(old_selection)
        self.set_visible_channels([name for name in old_checked if name in self.channel_names()],notify=False)
        self._quiet=False

    def set_visible_channels(self,names,*,notify=True):
        was_quiet=self._quiet
        self._quiet=True
        selected=set(names)
        self.visible_channels.clear()
        for name in self.channel_names():
            item=QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked)
            self.visible_channels.addItem(item)
        self._quiet=was_quiet
        if not was_quiet and notify:self.visibleChannelsChanged.emit()

    def channel_names(self):
        return [self.channel.itemText(i) for i in range(self.channel.count())]

    def visible_channel_names(self):
        return [self.visible_channels.item(i).text() for i in range(self.visible_channels.count())
                if self.visible_channels.item(i).checkState()==Qt.CheckState.Checked]

    def ensure_visible(self,name):
        if name in self.visible_channel_names():return
        target=self.channel_names()
        if name not in target:return
        self.set_visible_channels(self.visible_channel_names()+[name])

    def _visible_changed(self,item):
        if self._quiet:return
        if item.text() in self.result_channels:
            self.visibleChannelsChanged.emit()
            return
        selected=self.visible_channel_names()
        active=self.channel.currentText()
        if active and active not in selected:
            # Always show the editable channel, even if unchecked by mistake.
            self._quiet=True
            for i in range(self.visible_channels.count()):
                it=self.visible_channels.item(i)
                if it.text()==active:it.setCheckState(Qt.CheckState.Checked)
            self._quiet=False
            return
        self.visibleChannelsChanged.emit()

    def clear_scan(self):
        """Leave the Inspector in a neutral state when the last scan is removed."""
        self._quiet=True
        self.result_channels={}
        self._physical_channel_names=[]
        self.channel.clear()
        self.trace.clear()
        self.visible_channels.clear()
        self._steps=[]
        self.step_list.clear()
        self.metadata.setText('No scan loaded')
        self._quiet=False

    def _set_traces(self,scan,requested=None):
        name=self.channel.currentText()
        available=list(scan.channels[name].traces) if name in scan.channels else []
        current=self.trace.currentText()
        self.trace.clear()
        for direction in available:
            self.trace.addItem(direction.upper(),direction)
        chosen=requested or current
        for i in range(self.trace.count()):
            if self.trace.itemData(i)==chosen:
                self.trace.setCurrentIndex(i)
                break

    def update_traces(self,scan):
        self._quiet=True
        self._set_traces(scan)
        self._quiet=False

    def selected_trace(self):
        return self.trace.currentData() or 'forward'

    def get_style(self):
        return ImageStyle(combo_key(self.palette),combo_key(self.mode),float(self.low.text()),
                          float(self.high.text()),self.gamma.value(),self.scale_bar.isChecked(),
                          self.colorbar.isChecked())

    def set_style(self,style):
        self._quiet=True
        set_combo_key(self.palette,style.colormap)
        set_combo_key(self.mode,style.range_mode)
        self.low.setText(f'{style.low:.12g}')
        self.high.setText(f'{style.high:.12g}')
        self.gamma.setValue(style.gamma)
        self.scale_bar.setChecked(style.scale_bar)
        self.colorbar.setChecked(style.colorbar)
        self._quiet=False

    def steps(self):
        return list(self._steps)

    def set_steps(self,steps):
        self._steps=list(steps)
        self._update_steps()

    def _update_steps(self):
        self._quiet=True
        self.step_list.clear()
        for step in self._steps:
            label=next((k for k,v in OPERATIONS.items() if v==step.operation),ui_label(step.operation))
            item=QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if step.enabled else Qt.CheckState.Unchecked)
            self.step_list.addItem(item)
        self._quiet=False
        self.processingChanged.emit()

    def _toggle_step(self,item):
        if self._quiet:
            return
        i=self.step_list.row(item)
        old=self._steps[i]
        self._steps[i]=ProcessingStep(old.operation,old.params,item.checkState()==Qt.CheckState.Checked)
        self.processingChanged.emit()

    def _add_operation(self, op):
        if op == 'fix_zero':
            # Presentation-only zero is a toggleable step, never stacked twice.
            for i,step in enumerate(self._steps):
                if step.operation == 'fix_zero':
                    if not step.enabled:
                        self._steps[i]=ProcessingStep('fix_zero',{},True)
                        self._update_steps()
                    self.step_list.setCurrentRow(i)
                    self.fixZeroRequested.emit()
                    return
        self._steps.append(ProcessingStep(op, dict(DEFAULT_PARAMETERS.get(op, {}))))
        self._update_steps()
        self.step_list.setCurrentRow(len(self._steps)-1)
        if op == 'fix_zero':
            self.fixZeroRequested.emit()

    def _edit_step(self, item):
        i=self.step_list.row(item)
        if i<0:return
        step=self._steps[i]
        if not step.params:return
        import json
        text,ok=QInputDialog.getMultiLineText(self,'Processing parameters',
            f'Edit {step.operation} parameters (JSON numbers):',json.dumps(step.params,indent=2))
        if not ok:return
        try:
            params=json.loads(text)
            if not isinstance(params,dict) or any(not isinstance(v,(int,float)) for v in params.values()):
                raise ValueError('Parameters must be a JSON object containing numbers')
        except (ValueError,TypeError) as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self,'Invalid parameters',str(exc));return
        self._steps[i]=ProcessingStep(step.operation,params,step.enabled)
        self._update_steps()
        self.step_list.setCurrentRow(i)

    def _remove_step(self):
        i=self.step_list.currentRow()
        if i>=0:
            self._steps.pop(i)
            self._update_steps()

    def _move_step(self,direction):
        i=self.step_list.currentRow()
        j=i+direction
        if 0<=i<len(self._steps) and 0<=j<len(self._steps):
            self._steps[i],self._steps[j]=self._steps[j],self._steps[i]
            self._update_steps()
            self.step_list.setCurrentRow(j)
