"""SPM Studio spectroscopy figure composer (scan images + spectra). Read-only postprocessing.

v0.0.10: one tool for every point-spectroscopy method. The *Measurement type* at the top
(Δf(V) KPFM / CPD, dI/dV STS, I(V), I(z) / Δf(z), generic X–Y) sets the X axis, its label,
the default Y channel, units, fits and processing. The figure layout is computed by
Matplotlib's constrained layout, so titles, labels, colourbars and the legend never overlap.
"""
from __future__ import annotations

import copy
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QSplitter, QScrollArea, QTabWidget,
    QFileDialog, QMessageBox, QColorDialog, QTextEdit, QGroupBox,
    QFrame, QSizePolicy,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.widgets import RectangleSelector

from ..core.bias_figure_analysis import read_spectrum, session_files
from ..core.bias_figure_render import create_figure, PALETTE
from ..core import spectroscopy_methods as sm
from ..core.io import read_scan
from ..core.display import PALETTES
from ..core import paths
from dataclasses import asdict

def list_available_colormaps():
    folder=paths.customization_dir()/'colormaps'
    extras=([p.name for p in folder.glob('*.csv')]+[p.name for p in folder.glob('*.txt')]) if folder.exists() else []
    return sorted(set(PALETTES)|set(extras),key=str.casefold)

PLUGIN_NAME = 'Spectroscopy • paper figure composer'
PLUGIN_TYPE = 'gui'
PLUGIN_DESCRIPTION = ('Compose SPM channels and spectra of any method (Δf(V) KPFM, dI/dV STS, I(V), I(z) …), '
                      'show where each spectrum was measured and export vector PDF.')


def _combo_set(box, value):
    for i in range(box.count()):
        if box.itemData(i) == value or box.itemText(i) == value:
            box.setCurrentIndex(i)
            return
    if box.count(): box.setCurrentIndex(0)


def _row(*parts):
    w=QWidget(); lay=QHBoxLayout(w);lay.setContentsMargins(0,0,0,0);lay.setSpacing(5)
    for item in parts:
        lay.addWidget(item)
    return w


def _push(label, action, tip=''):
    x=QPushButton(label);x.clicked.connect(action)
    if tip:x.setToolTip(tip)
    return x


def _line(placeholder=''):
    v=QLineEdit();v.setPlaceholderText(placeholder)
    return v


class Composer(QDialog):
    def __init__(self, main_window: Any, context: dict):
        super().__init__(main_window)
        self.main_window=main_window
        self.context=context
        self.setWindowTitle('SPM Studio — Spectroscopy figure composer')
        self.resize(1550,970)
        self.setMinimumSize(960,650)
        self.scans=({str(main_window.scan.path.resolve()):main_window.scan} if getattr(main_window,'scan',None) is not None else {})
        self.spectra={}
        self.project={'version':3,'options':{'title':'', 'font':8., 'width':11.,'method':sm.DEFAULT_METHOD,
                      'share_bias':True,'share_signal':True,'panel_labels':True,'bias_min':'','bias_max':'',
                      'signal_min':'','signal_max':'','didv_source':'Lock-in channel','normalize':False,
                      'smooth':0,'average':False,'offset':'','log_y':False,'x_channel':''},
                      'images':[],'graphs':[]}
        self._updating=False
        self._figure=None
        self._diagnostics=[]
        self._warnings=[]
        self._region_selector=None
        self._inset_drag=None
        self._setup_ui()
        self.redraw_timer=QTimer(self);self.redraw_timer.setSingleShot(True)
        self.redraw_timer.timeout.connect(self.redraw)
        self._load_defaults()
        self.schedule()

    def _setup_ui(self):
        outer=QVBoxLayout(self)
        bar=QHBoxLayout();outer.addLayout(bar)
        for label,func in [('Open setup…',self.open_project),('Save setup…',self.save_project),
                           ('Export PDF…',lambda:self.export('pdf')),
                           ('Export SVG…',lambda:self.export('svg')),
                           ('Export PNG…',lambda:self.export('png'))]:
            bar.addWidget(_push(label,func))
        bar.addStretch(1)
        bar.addWidget(_push('Refresh figure',self.redraw))
        self.status=QLabel('Ready');bar.addWidget(self.status)

        split=QSplitter(Qt.Horizontal);outer.addWidget(split,1)
        scroll=QScrollArea();scroll.setWidgetResizable(True);split.addWidget(scroll)
        side=QWidget();scroll.setWidget(side)
        side_l=QVBoxLayout(side);side_l.setContentsMargins(7,7,7,7)
        method_box=QGroupBox('Measurement type');side_l.addWidget(method_box)
        mf=QFormLayout(method_box)
        self.method=QComboBox();self.method.setObjectName('SpectroscopyMethodV0010')
        for key,m in sm.METHODS.items():self.method.addItem(m.label,key)
        self.method.setToolTip('What was measured: sets the X axis, labels, default channel, units and fits')
        self.method.currentIndexChanged.connect(self.change_method)
        self.method_hint=QLabel('');self.method_hint.setWordWrap(True);self.method_hint.setObjectName('hint')
        self.didv_source=QComboBox();self.didv_source.addItems(['Lock-in channel','Numerical d(Current)/dV'])
        self.didv_source.setToolTip('Lock-in: plot the demodulated channel. Numerical: derivative of the current (smoothed).')
        self.normalize=QCheckBox('Normalised (dI/dV)/(I/V)')
        self.smooth=QDoubleSpinBox();self.smooth.setRange(0,101);self.smooth.setDecimals(0);self.smooth.setSingleStep(2)
        self.smooth.setSuffix(' points');self.smooth.setSpecialValueText('No smoothing')
        self.smooth.setToolTip('Savitzky–Golay smoothing window (odd number of points); the files are unchanged')
        self.average=QCheckBox('Average forward and backward sweeps')
        self.offset=_line('0 = none (display unit)')
        self.offset.setToolTip('Waterfall: shift each spectrum of a graph by this amount')
        self.log_y=QCheckBox('Logarithmic Y axis (|signal|)')
        self.x_channel=QComboBox();self.x_channel.setEditable(True)
        self.x_channel.setToolTip('Channel of the spectroscopy file used as X axis')
        for w in (self.didv_source,self.x_channel):w.currentIndexChanged.connect(self.update_global)
        self.x_channel.currentTextChanged.connect(self.update_global)
        for w in (self.normalize,self.average,self.log_y):w.stateChanged.connect(self.update_global)
        self.smooth.valueChanged.connect(self.update_global);self.offset.textEdited.connect(self.update_global)
        mf.addRow('Method',self.method);mf.addRow('',self.method_hint)
        self._method_rows={}
        for key,label,widget in (('didv_source','dI/dV from',self.didv_source),('normalize','',self.normalize),
                                 ('x_channel','X channel',self.x_channel),('smooth','Smoothing',self.smooth),
                                 ('average','',self.average),('offset','Waterfall offset',self.offset),
                                 ('log_y','',self.log_y)):
            mf.addRow(label,widget);self._method_rows[key]=(mf,widget)
        box=QGroupBox('Figure settings');side_l.addWidget(box)
        f=QFormLayout(box)
        self.figure_title=_line('Optional overall title');self.figure_title.textEdited.connect(self.update_global)
        self.figure_width=QDoubleSpinBox();self.figure_width.setRange(6,22);self.figure_width.setDecimals(1)
        self.figure_width.setSingleStep(.5);self.figure_width.setSuffix(' in')
        self.figure_width.valueChanged.connect(self.update_global)
        self.font_size=QDoubleSpinBox();self.font_size.setRange(5,15);self.font_size.setDecimals(1)
        self.font_size.valueChanged.connect(self.update_global)
        f.addRow('Title',self.figure_title);f.addRow('Page width',self.figure_width);f.addRow('Font size',self.font_size)
        axes_box=QGroupBox('Paper axes · multi-site comparison');side_l.addWidget(axes_box)
        af=QFormLayout(axes_box)
        self.share_bias=QCheckBox('Same X range in every plot')
        self.share_bias.setChecked(True);self.share_bias.stateChanged.connect(self.update_global)
        self.share_signal=QCheckBox('Same Y range for matching channels / units')
        self.share_signal.setChecked(True);self.share_signal.stateChanged.connect(self.update_global)
        self.bias_min=_line('Auto');self.bias_max=_line('Auto')
        self.signal_min=_line('Auto');self.signal_max=_line('Auto')
        for field in (self.bias_min,self.bias_max,self.signal_min,self.signal_max):
            field.textEdited.connect(self.update_global)
        self.panel_labels=QCheckBox('Label panels a, b, c … (journal style)')
        self.panel_labels.setChecked(True);self.panel_labels.stateChanged.connect(self.update_global)
        self.transparent_export=QCheckBox('Transparent background')
        try:self.transparent_export.setChecked(bool(self.main_window.export_transparent()))
        except Exception:self.transparent_export.setChecked(False)
        af.addRow('',self.share_bias);af.addRow('',self.share_signal);af.addRow('',self.panel_labels)
        af.addRow('',self.transparent_export)
        self.x_range_label=QLabel('X min / max (V)')
        af.addRow(self.x_range_label,_row(self.bias_min,self.bias_max))
        af.addRow('Y min / max (display unit)',_row(self.signal_min,self.signal_max))
        af.addRow(QLabel('Blank = automatic. X is absolute (bias in V, Z in nm), never re-centred per curve.'))

        self.tabs=QTabWidget();side_l.addWidget(self.tabs,1)
        self._image_tab();self._graph_tab()
        info=QLabel('Preview updates automatically. All spectroscopic data are read only. '
                    'A saved session.json supplies Follow Me XY; for converted scans confirm marker alignment.')
        info.setWordWrap(True);side_l.addWidget(info)
        self.diagnostics=QTextEdit();self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumHeight(116);self.diagnostics.setPlaceholderText('Fit diagnostics and coordinate warnings…')
        side_l.addWidget(self.diagnostics)
        right=QWidget();right_l=QVBoxLayout(right);right_l.setContentsMargins(3,3,3,3)
        self.canvas_holder=QScrollArea();self.canvas_holder.setWidgetResizable(False)
        self.canvas_holder.setAlignment(Qt.AlignHCenter|Qt.AlignTop)
        right_l.addWidget(self.canvas_holder,1)
        self.right_layout=right_l
        self.canvas=None;self.toolbar=None
        split.addWidget(right);split.setSizes([465,1080])

    def _image_tab(self):
        tab=QWidget();self.tabs.addTab(tab,'Image channels')
        lay=QVBoxLayout(tab);lay.setContentsMargins(4,5,4,4)
        lay.addWidget(_row(_push('Add image',self.add_image), _push('Add scan…',self.open_scan)))
        self.image_list=QListWidget();self.image_list.setMaximumHeight(148)
        self.image_list.currentRowChanged.connect(self.on_image_select)
        lay.addWidget(self.image_list)
        lay.addWidget(_row(_push('↑',lambda:self.move_image(-1)),_push('↓',lambda:self.move_image(1)),
                           _push('Remove image',self.remove_image)))
        group=QGroupBox('Selected image');lay.addWidget(group)
        form=QFormLayout(group)
        self.i_title=_line('e.g. Topography');self.i_title.textEdited.connect(self.update_image)
        self.i_scan=QComboBox();self.i_scan.currentIndexChanged.connect(self.change_image_scan)
        self.i_channel=QComboBox();self.i_channel.currentIndexChanged.connect(self.update_image)
        self.i_direction=QComboBox();self.i_direction.addItems(['forward','backward'])
        self.i_direction.currentIndexChanged.connect(self.update_image)
        self.i_colormap=QComboBox();self.i_colormap.addItems(list_available_colormaps())
        self.i_colormap.currentIndexChanged.connect(self.update_image)
        self.i_colorbar=QComboBox();self.i_colorbar.addItems(['Bottom','Right'])
        self.i_colorbar.currentIndexChanged.connect(self.update_image)
        self.i_unit=QComboBox();self.i_unit.addItems(['Auto','pm','nm','mV','V','pA','Raw'])
        self.i_unit.currentIndexChanged.connect(self.update_image)
        self.i_vmin=_line('Auto, lower 2nd percentile');self.i_vmax=_line('Auto, upper 98th percentile')
        self.i_vmin.textEdited.connect(self.update_image);self.i_vmax.textEdited.connect(self.update_image)
        self.i_processed=QCheckBox('Use SPM Studio processing');self.i_processed.stateChanged.connect(self.update_image)
        self.i_scale=QCheckBox('Scale bar');self.i_scale.stateChanged.connect(self.update_image)
        self.i_markers=QCheckBox('Spectroscopy markers');self.i_markers.stateChanged.connect(self.update_image)
        self.i_flipx=QCheckBox('Flip marker X');self.i_flipx.stateChanged.connect(self.update_image)
        self.i_flipy=QCheckBox('Flip marker Y');self.i_flipy.stateChanged.connect(self.update_image)
        self.i_params=QComboBox();self.i_params.addItems(['None','Top left','Top right','Bottom left','Bottom right'])
        self.i_params.setToolTip('Write the measurement parameters (bias, setpoint; for Multipass the pass of the '
                                 'channel: bias, setpoint, Δz) in a corner of the image')
        self.i_params.currentIndexChanged.connect(self.update_image)
        self.i_driftx=_line('0');self.i_drifty=_line('0')
        self.i_driftx.textEdited.connect(self.update_image);self.i_drifty.textEdited.connect(self.update_image)
        form.addRow('Panel title',self.i_title);form.addRow('Scan file',self.i_scan)
        form.addRow('Channel',self.i_channel);form.addRow('Direction',self.i_direction)
        form.addRow('Colourmap',self.i_colormap);form.addRow('Colourbar position',self.i_colorbar)
        form.addRow('Display unit',self.i_unit)
        form.addRow('Colour minimum',self.i_vmin);form.addRow('Colour maximum',self.i_vmax)
        form.addRow('',self.i_processed);form.addRow('',_row(self.i_scale,self.i_markers))
        form.addRow('Parameters on image',self.i_params)
        form.addRow('Coordinate convention',_row(self.i_flipx,self.i_flipy))
        form.addRow('Manual drift X/Y (nm)',_row(self.i_driftx,self.i_drifty))
        lay.addStretch(1)

    def _graph_tab(self):
        tab=QWidget();self.tabs.addTab(tab,'Spectra plots & sweeps')
        lay=QVBoxLayout(tab);lay.setContentsMargins(4,5,4,4)
        lay.addWidget(_row(_push('Add graph',self.add_graph),_push('Remove graph',self.remove_graph),
                           _push('↑',lambda:self.move_graph(-1)),_push('↓',lambda:self.move_graph(1))))
        self.graph_list=QListWidget();self.graph_list.setMaximumHeight(116)
        self.graph_list.currentRowChanged.connect(self.on_graph_select);lay.addWidget(self.graph_list)
        group=QGroupBox('Selected graph');form=QFormLayout(group);lay.addWidget(group)
        self.g_title=_line('e.g. Charged molecule');self.g_title.textEdited.connect(self.update_graph)
        self.g_channel=QComboBox();self.g_channel.currentIndexChanged.connect(self.update_graph)
        self.g_unit=QComboBox();self.g_unit.addItems(['Auto','Raw','pm','nm','µV','mV','V','fA','pA','nA',
                                                      'pS','nS','µS','Hz','kHz'])
        self.g_unit.currentIndexChanged.connect(self.update_graph)
        self.g_trend=QComboBox();self.g_trend.addItems(['None','Kink vs height','CPD vs height'])
        self.g_trend.currentIndexChanged.connect(self.update_graph)
        self.g_branch=QComboBox();self.g_branch.addItems(['Forward','Backward'])
        self.g_branch.currentIndexChanged.connect(self.update_graph)
        self.g_minbic=QDoubleSpinBox();self.g_minbic.setRange(0,100);self.g_minbic.setValue(14)
        self.g_minbic.setDecimals(1);self.g_minbic.valueChanged.connect(self.update_graph)
        self.g_sigma=QDoubleSpinBox();self.g_sigma.setRange(1,20);self.g_sigma.setValue(4)
        self.g_sigma.setDecimals(1);self.g_sigma.valueChanged.connect(self.update_graph)
        self.g_annotate=QCheckBox('Mark detected kink / CPD on curves')
        self.g_annotate.stateChanged.connect(self.update_graph)
        form.addRow('Graph title',self.g_title);form.addRow('Y channel',self.g_channel)
        self.g_trend_label=QLabel('Height analysis')
        form.addRow('Y unit',self.g_unit);form.addRow(self.g_trend_label,self.g_trend)
        form.addRow('Fit using sweep',self.g_branch)
        form.addRow('Min. kink BIC gain',self.g_minbic);form.addRow('Min. kink SNR',self.g_sigma)
        form.addRow('',self.g_annotate)
        inset_group=QGroupBox('Zoom inset · selected graph');il=QFormLayout(inset_group)
        lay.addWidget(inset_group)
        self.g_inset=QCheckBox('Show magnified inset in paper figure')
        self.g_inset.stateChanged.connect(self.update_inset)
        self.g_region_fields=[]
        for _ in range(4):
            field=_line('Auto')
            field.textEdited.connect(self.update_inset)
            self.g_region_fields.append(field)
        self.g_inset_preset=QComboBox()
        self.g_inset_preset.addItems(['Upper right','Upper left','Lower right','Lower left','Custom'])
        self.g_inset_preset.currentIndexChanged.connect(self.change_inset_preset)
        self.g_inset_pos=[]
        for value in (57.,53.,40.,40.):
            spin=QDoubleSpinBox();spin.setRange(0.,100.);spin.setDecimals(1)
            spin.setSuffix(' %');spin.setSingleStep(2.);spin.setValue(value)
            spin.valueChanged.connect(self.update_inset)
            self.g_inset_pos.append(spin)
        il.addRow('',self.g_inset)
        il.addRow('X region min/max',_row(*self.g_region_fields[:2]))
        il.addRow('Signal region min/max',_row(*self.g_region_fields[2:]))
        il.addRow('Inset location',self.g_inset_preset)
        il.addRow('Position X / Y',_row(*self.g_inset_pos[:2]))
        il.addRow('Width / Height',_row(*self.g_inset_pos[2:]))
        il.addRow(_row(_push('Select region on plot…',self.select_inset_region,
                              'Drag a rectangle in the selected graph preview'),
                        _push('Reset auto region',self.reset_inset_region)))
        caption=QLabel('Drag on the main graph to choose the region; drag the inset to move it.')
        caption.setObjectName('hint')
        caption.setWordWrap(True);il.addRow(caption)
        lay.addWidget(QLabel('Sweeps in selected graph (add many for CPD comparison):'))
        lay.addWidget(_row(_push('Add session folder…',self.add_session),
                            _push('Add spectra files…',self.add_spectra),
                            _push('Remove sweep',self.remove_trace)))
        self.trace_list=QListWidget();self.trace_list.setMaximumHeight(150)
        self.trace_list.currentRowChanged.connect(self.on_trace_select)
        lay.addWidget(self.trace_list)
        trace_group=QGroupBox('Selected spectrum / sweep');tf=QFormLayout(trace_group)
        lay.addWidget(trace_group)
        self.t_label=_line();self.t_label.textEdited.connect(self.update_trace)
        self.t_mode=QComboBox();self.t_mode.addItems(['Both','Forward','Backward'])
        self.t_mode.currentIndexChanged.connect(self.update_trace)
        self.t_color=_push('Choose colour…',self.choose_color)
        self.t_scan=QComboBox();self.t_scan.currentIndexChanged.connect(self.update_trace)
        self.t_manualx=_line('blank = use session Follow Me X')
        self.t_manualy=_line('blank = use session Follow Me Y')
        self.t_manualx.textEdited.connect(self.update_trace);self.t_manualy.textEdited.connect(self.update_trace)
        self.t_enabled=QCheckBox('Show this sweep and its marker');self.t_enabled.stateChanged.connect(self.update_trace)
        self.t_fit_enabled=QCheckBox('Include this spectrum in feature detection / Z fit');self.t_fit_enabled.stateChanged.connect(self.update_trace)
        tf.addRow('Legend name',self.t_label);tf.addRow('Sweep direction',self.t_mode)
        tf.addRow('Trace colour',self.t_color);tf.addRow('Marker on scan',self.t_scan)
        tf.addRow('Override X local (nm)',self.t_manualx);tf.addRow('Override Y local (nm)',self.t_manualy)
        tf.addRow('',self.t_enabled);tf.addRow('',self.t_fit_enabled)
        lay.addStretch(1)

    def _load_defaults(self):
        active=getattr(self.main_window,'scan',None)
        scan=str(active.path.resolve()) if active is not None else None
        if not scan and self.scans:scan=next(iter(self.scans))
        if scan:
            for title,terms,cmap in [('Topography',('z','topo','height'),'gray'),
                                      ('Excitation',('excitation','dissipation'),'inferno')]:
                sf=self.scans[scan]
                ch=self._best_channel(sf,terms)
                self.project['images'].append(self._new_image(scan,ch,title,cmap))
        self.project['graphs'].append(self._new_graph('Ag(111)'))
        self.project['graphs'].append(self._new_graph('Charged molecule'))
        self.project['graphs'].append(self._new_graph('Non-charged molecule'))
        self._sync_all()
        self._apply_method_ui()
        self.image_list.setCurrentRow(0);self.graph_list.setCurrentRow(0)
        self.figure_width.setValue(11);self.font_size.setValue(8.)

    def _best_channel(self,sf,terms):
        names=list(sf.channels)
        for term in terms:
            matches=[n for n in names if (n.casefold()=='z' if term=='z' else term in n.casefold())]
            if matches:return matches[0]
        return names[0] if names else ''

    def _style_dict(self,scan,ch,direction='forward'):
        try:
            sf=self.scans[scan]
            if direction not in sf.channels[ch].traces:
                direction='forward' if 'forward' in sf.channels[ch].traces else next(iter(sf.channels[ch].traces))
            key=(str(sf.path),ch,direction)
            style=self.main_window.styles.get(key)
            steps=self.main_window.pipelines.get(key,[])
            if self.main_window.scan is not None and str(self.main_window.scan.path)==str(sf.path):
                active=self.main_window.inspector.channel.currentText()
                if ch==active and self.main_window.inspector.selected_trace()==direction:
                    style=self.main_window.inspector.get_style()
                    steps=self.main_window.inspector.steps()
            snapshot=asdict(style) if style is not None else {}
            snapshot['processing_steps']=[asdict(step) for step in steps]
            return snapshot
        except Exception:
            return {'processing_steps':[]}

    def _new_image(self,scan,channel,title,cmap):
        return {'scan':scan,'channel':channel,'title':title,'direction':'forward',
                'cmap':cmap,'colorbar':'Bottom','unit':'Auto','vmin':'','vmax':'','processed':True,
                'style':self._style_dict(scan,channel),'scalebar':True,'markers':True,
                'flip_x':False,'flip_y':False,'drift_x':0.,'drift_y':0.}

    def _method(self):
        return sm.method(self.project.get('options',{}).get('method'))

    def _default_channel(self):
        m=self._method()
        for spec in self.spectra.values():
            ch=sm.preferred_channel(spec,m)
            if ch:return ch
        return {'bias_kpfm':'OC M1 Freq. Shift (Hz)','didv':'LI Demod 1 X (V)','iv':'Current (A)',
                'iz':'Current (A)'}.get(m.key,'')

    def change_method(self,*_):
        if self._updating:return
        old=self._method()
        self.project['options']['method']=self.method.currentData() or sm.DEFAULT_METHOD
        m=self._method()
        if m.key!=old.key:
            for graph in self.project['graphs']:
                # The Y channel follows the method: dI/dV → lock-in, I(V) → current, KPFM → Δf …
                spec=next((self.spectra[t['path']] for t in graph.get('traces',[]) if t.get('path') in self.spectra),None)
                graph['channel']=(sm.preferred_channel(spec,m) if spec is not None else None) or self._default_channel()
                if graph.get('trend','None') not in m.fits:graph['trend']='None'
                title=graph.get('title','')
                if title.startswith(old.graph_title):graph['title']=m.graph_title+title[len(old.graph_title):]
        self._apply_method_ui()
        row=self.graph_list.currentRow()
        self._sync_all()
        self.graph_list.setCurrentRow(row)
        self.on_graph_select(row)
        self.schedule()

    def _apply_method_ui(self):
        m=self._method();o=self.project.get('options',{})
        self._updating=True
        _combo_set(self.method,m.key)
        self.method_hint.setText(m.hints or '')
        self.method_hint.setVisible(bool(m.hints))
        for key,(form,widget) in self._method_rows.items():
            visible=key in m.options
            widget.setVisible(visible)
            label=form.labelForField(widget)
            if label is not None:label.setVisible(visible)
        self.didv_source.setCurrentText(str(o.get('didv_source','Lock-in channel')))
        self.normalize.setChecked(bool(o.get('normalize',False)))
        self.smooth.setValue(float(o.get('smooth',0) or 0))
        self.average.setChecked(bool(o.get('average',False)))
        self.offset.setText(str(o.get('offset','') or ''))
        self.log_y.setChecked(bool(o.get('log_y',False)))
        names=sorted({n for spec in self.spectra.values() for n in sm.x_channels(spec)},key=str.casefold)
        self.x_channel.clear();self.x_channel.addItems(names)
        self.x_channel.setCurrentText(str(o.get('x_channel','') or (names[0] if names else '')))
        self.g_trend.clear();self.g_trend.addItems(list(m.fits))
        self.g_trend.setEnabled(len(m.fits)>1);self.g_trend_label.setEnabled(len(m.fits)>1)
        for w in (self.g_branch,self.g_minbic,self.g_sigma,self.g_annotate):w.setEnabled(m.key=='bias_kpfm')
        unit={'bias':'V','z':'nm'}.get(m.sweep,'')
        self.x_range_label.setText(f'X min / max ({unit})' if unit else 'X min / max')
        self._updating=False

    def _new_graph(self,title=None):
        title=title or self._method().graph_title
        return {'title':title,'channel':self._default_channel(),'unit':'Auto',
                'trend':'None','trend_direction':'Forward','min_bic':14.0,
                'min_sigma':4.,'annotate':False,'traces':[],
                'inset':{'enabled':False,'bounds':None,'position':[.57,.53,.40,.40]}}

    def schedule(self):
        if not self._updating:self.redraw_timer.start(380)

    def _sync_all(self):
        self._updating=True
        self.image_list.clear();self.graph_list.clear()
        for im in self.project['images']:
            self.image_list.addItem(f"{im.get('title','Image')} — {Path(im.get('scan','?')).name}")
        for graph in self.project['graphs']:
            self.graph_list.addItem(graph.get('title','Spectra'))
        self._updating=False

    def _set_scan_combo(self,combo,selected,none_option=False):
        combo.clear()
        if none_option:combo.addItem('No linked scan / no marker','')
        for path in self.scans:
            sf=self.scans[path]
            combo.addItem(f'{Path(path).name}  ({len(sf.channels)} channels)',path)
        _combo_set(combo,selected)

    def _current_image(self):
        i=self.image_list.currentRow()
        return self.project['images'][i] if 0<=i<len(self.project['images']) else None

    def _current_graph(self):
        i=self.graph_list.currentRow()
        return self.project['graphs'][i] if 0<=i<len(self.project['graphs']) else None

    def _current_trace(self):
        graph=self._current_graph();i=self.trace_list.currentRow()
        return graph['traces'][i] if graph and 0<=i<len(graph['traces']) else None

    def on_image_select(self,_index):
        if self._updating:return
        im=self._current_image()
        self._updating=True
        if im:
            self.i_title.setText(im.get('title',''))
            self._set_scan_combo(self.i_scan,im.get('scan',''))
            self._fill_channels(self.i_channel,im.get('scan',''),im.get('channel',''))
            _combo_set(self.i_direction,im.get('direction','forward'))
            _combo_set(self.i_colormap,im.get('cmap','gray'))
            _combo_set(self.i_colorbar,im.get('colorbar','Bottom'))
            _combo_set(self.i_unit,im.get('unit','Auto'))
            self.i_vmin.setText(str(im.get('vmin','')));self.i_vmax.setText(str(im.get('vmax','')))
            self.i_processed.setChecked(im.get('processed',True))
            self.i_scale.setChecked(im.get('scalebar',True))
            self.i_markers.setChecked(im.get('markers',True))
            self.i_flipx.setChecked(im.get('flip_x',False))
            self.i_flipy.setChecked(im.get('flip_y',False))
            _combo_set(self.i_params,im.get('parameters','None'))
            self.i_driftx.setText(str(im.get('drift_x',0)))
            self.i_drifty.setText(str(im.get('drift_y',0)))
        self._updating=False

    def _fill_channels(self,combo,scan,ch):
        combo.clear();sf=self.scans.get(scan)
        if sf:
            for n in sf.channels: combo.addItem(n,n)
        _combo_set(combo,ch)

    def change_image_scan(self):
        if self._updating:return
        im=self._current_image()
        if not im:return
        current_idx=self.image_list.currentRow()
        im['scan']=self.i_scan.currentData() or ''
        self._updating=True
        self._fill_channels(self.i_channel,im['scan'],im.get('channel'))
        self._updating=False
        im['channel']=self.i_channel.currentData() or ''
        im['style']=self._style_dict(im['scan'],im['channel'],im.get('direction','forward'))
        self._sync_all();self.image_list.setCurrentRow(current_idx)
        self.schedule()

    def update_image(self,*_):
        if self._updating:return
        im=self._current_image()
        if not im:return
        old_ch=im.get('channel')
        old_direction=im.get('direction')
        im.update({'title':self.i_title.text().strip(),'scan':self.i_scan.currentData() or '',
             'channel':self.i_channel.currentData() or '',
             'direction':self.i_direction.currentText(), 'cmap':self.i_colormap.currentText(),
             'colorbar':self.i_colorbar.currentText(),
             'unit':self.i_unit.currentText(), 'vmin':self.i_vmin.text().strip(),
             'vmax':self.i_vmax.text().strip(), 'processed':self.i_processed.isChecked(),
             'scalebar':self.i_scale.isChecked(),'markers':self.i_markers.isChecked(),
             'flip_x':self.i_flipx.isChecked(),'flip_y':self.i_flipy.isChecked(),
             'parameters':self.i_params.currentText()})
        for field,widget in (('drift_x',self.i_driftx),('drift_y',self.i_drifty)):
            try:im[field]=float(widget.text())
            except ValueError:im[field]=0.
        if im['channel']!=old_ch or im['direction']!=old_direction:
            im['style']=self._style_dict(im['scan'],im['channel'],im['direction'])
        row=self.image_list.currentRow()
        if row>=0:self.image_list.item(row).setText(f"{im['title']} — {Path(im['scan']).name}")
        self.schedule()

    def open_scan(self):
        path,_=QFileDialog.getOpenFileName(self,'Open SPM scan',str(self.context.get('root',Path.home())),
               'SPM scans (*.sxm *.gwy);;All files (*)')
        if not path:return
        path=str(Path(path).resolve())
        if path in self.scans:return
        try:
            self.scans[path]=read_scan(path)
            self.status.setText(f'Loaded scan: {Path(path).name}')
            self.add_image(scan_override=path)
        except Exception as exc:QMessageBox.warning(self,'Cannot load scan',str(exc))

    def add_image(self,*,scan_override=None):
        path=scan_override or (self._current_image() or {}).get('scan') or next(iter(self.scans),'')
        if not path:
            QMessageBox.information(self,'No scan','First open an SPM scan using “Add scan…”.')
            return
        sf=self.scans[path];ch=self._best_channel(sf,('z','height','topo'))
        self.project['images'].append(self._new_image(path,ch,f'Image {len(self.project["images"])+1}','gray'))
        self._sync_all();self.image_list.setCurrentRow(len(self.project['images'])-1)
        self.schedule()

    def remove_image(self):
        i=self.image_list.currentRow()
        if i<0:return
        self.project['images'].pop(i);self._sync_all()
        self.image_list.setCurrentRow(min(i,len(self.project['images'])-1));self.schedule()

    def move_image(self,delta):
        i=self.image_list.currentRow();j=i+delta
        a=self.project['images']
        if i<0 or not (0<=j<len(a)):return
        a[i],a[j]=a[j],a[i];self._sync_all();self.image_list.setCurrentRow(j);self.schedule()

    def on_graph_select(self,_index):
        if self._updating:return
        g=self._current_graph()
        self._updating=True
        self.trace_list.clear()
        if g:
            self.g_title.setText(g.get('title',''))
            old=self.g_channel.currentText()
            self.g_channel.clear()
            channels=set()
            for t in g['traces']:
                s=self.spectra.get(t['path'])
                if s:channels.update(sm.y_channels(s,self._method()))
            if g.get('channel'):channels.add(g['channel'])
            self.g_channel.addItems(sorted(channels,key=str.lower))
            _combo_set(self.g_channel,g.get('channel',''))
            _combo_set(self.g_unit,g.get('unit','Auto'))
            _combo_set(self.g_trend,g.get('trend','None'))
            _combo_set(self.g_branch,g.get('trend_direction','Forward'))
            self.g_minbic.setValue(float(g.get('min_bic',14)))
            self.g_sigma.setValue(float(g.get('min_sigma',4)))
            self.g_annotate.setChecked(bool(g.get('annotate',False)))
            inset=g.get('inset') or {}
            self.g_inset.setChecked(bool(inset.get('enabled',False)))
            bounds=inset.get('bounds')
            for k,widget in enumerate(self.g_region_fields):
                widget.setText(f'{float(bounds[k]):.6g}' if isinstance(bounds,(list,tuple)) and len(bounds)==4 else '')
            position=inset.get('position',[.57,.53,.40,.40])
            for widget,val in zip(self.g_inset_pos,position):widget.setValue(float(val)*100.)
            preset=self._inset_position_preset(position)
            _combo_set(self.g_inset_preset,preset)
            for tr in g['traces']:
                spec=self.spectra.get(tr.get('path'))
                height=f"+{spec.z_nm:.3f} nm" if spec and math.isfinite(spec.z_nm) else 'Z ?'
                self.trace_list.addItem(f"{tr.get('label','Sweep')}  |  {height}")
        self._updating=False
        if g and g['traces']:self.trace_list.setCurrentRow(0)

    def add_graph(self):
        self.project['graphs'].append(self._new_graph(f'{self._method().graph_title} {len(self.project["graphs"])+1}'))
        self._sync_all();self.graph_list.setCurrentRow(len(self.project['graphs'])-1)
        self.tabs.setCurrentIndex(1);self.schedule()

    def remove_graph(self):
        i=self.graph_list.currentRow()
        if i<0:return
        self.project['graphs'].pop(i);self._sync_all()
        self.graph_list.setCurrentRow(min(i,len(self.project['graphs'])-1));self.schedule()

    def move_graph(self,delta):
        i=self.graph_list.currentRow();j=i+delta;a=self.project['graphs']
        if i<0 or not (0<=j<len(a)):return
        a[i],a[j]=a[j],a[i];self._sync_all();self.graph_list.setCurrentRow(j);self.schedule()

    def update_graph(self,*_):
        if self._updating:return
        g=self._current_graph()
        if not g:return
        g.update({'title':self.g_title.text().strip(),'channel':self.g_channel.currentText(),
                  'unit':self.g_unit.currentText(),'trend':self.g_trend.currentText(),
                  'trend_direction':self.g_branch.currentText(),
                  'min_bic':self.g_minbic.value(),'min_sigma':self.g_sigma.value(),
                  'annotate':self.g_annotate.isChecked()})
        i=self.graph_list.currentRow()
        if i>=0:self.graph_list.item(i).setText(g['title'])
        self.schedule()

    @staticmethod
    def _inset_position_preset(position):
        x,y,w,h=[float(v) for v in position]
        presets={'Upper right':(.57,.53),'Upper left':(.03,.53),
                 'Lower right':(.57,.04),'Lower left':(.03,.04)}
        for name,(xx,yy) in presets.items():
            if abs(x-xx)<.001 and abs(y-yy)<.001 and abs(w-.40)<.001 and abs(h-.40)<.001:
                return name
        return 'Custom'

    def change_inset_preset(self,*_):
        if self._updating:return
        pos={'Upper right':(.57,.53,.40,.40),'Upper left':(.03,.53,.40,.40),
             'Lower right':(.57,.04,.40,.40),'Lower left':(.03,.04,.40,.40)}.get(
                 self.g_inset_preset.currentText())
        if pos is None:return
        self._updating=True
        for spin,num in zip(self.g_inset_pos,pos):spin.setValue(num*100.)
        self._updating=False
        self.update_inset()

    def update_inset(self,*_):
        if self._updating:return
        graph=self._current_graph()
        if graph is None:return
        region=[w.text().strip() for w in self.g_region_fields]
        bounds=None
        if any(region):
            try:
                if len([v for v in region if v]) != 4:
                    raise ValueError('Enter all four inset bounds, or leave all blank')
                bounds=list(map(float,region))
                if not all(math.isfinite(v) for v in bounds) or bounds[0]>=bounds[1] or bounds[2]>=bounds[3]:
                    raise ValueError('Minima must be smaller than maxima')
            except ValueError as exc:
                self.status.setText(f'Inset bounds: {exc}')
                return
        position=[w.value()/100. for w in self.g_inset_pos]
        # A valid inset must remain inside its graph panel.
        position[2]=max(.16,position[2]);position[3]=max(.16,position[3])
        position[0]=max(0,min(position[0],1-position[2]))
        position[1]=max(0,min(position[1],1-position[3]))
        graph['inset']={'enabled':self.g_inset.isChecked(), 'bounds':bounds,'position':position}
        self.schedule()

    def reset_inset_region(self):
        self._updating=True
        for widget in self.g_region_fields:widget.setText('')
        self._updating=False
        self.update_inset()

    def select_inset_region(self):
        graph_index=self.graph_list.currentRow()
        if graph_index<0:return
        self.redraw_timer.stop()
        if self.canvas is None or self._figure is None:self.redraw()
        graph_axes=[ax for ax in self._figure.axes
                    if getattr(ax,'_spm_plot_main',False) and getattr(ax,'_spm_graph_index',None)==graph_index]
        if not graph_axes:
            QMessageBox.information(self,'No graph','Load a sweep in this graph before selecting a region.')
            return
        if self.toolbar is not None and self.toolbar.mode:
            QMessageBox.information(self,'Switch off toolbar zoom/pan',
                                    'Deactivate the Matplotlib zoom/pan tool before selecting an inset region.')
            return
        if self._region_selector is not None:
            self._region_selector.set_active(False)
        def selected(click,release):
            if None in (click.xdata,click.ydata,release.xdata,release.ydata):return
            x0,x1=sorted((float(click.xdata),float(release.xdata)))
            y0,y1=sorted((float(click.ydata),float(release.ydata)))
            if x1-x0<=0 or y1-y0<=0:return
            g=self.project['graphs'][graph_index]
            g.setdefault('inset',{})['bounds']=[x0,x1,y0,y1]
            g['inset']['enabled']=True
            if self._region_selector is not None:
                self._region_selector.set_active(False)
                self._region_selector=None
            if self.graph_list.currentRow()==graph_index:
                self._updating=True
                for widget,value in zip(self.g_region_fields,(x0,x1,y0,y1)):
                    widget.setText(f'{value:.6g}')
                self.g_inset.setChecked(True)
                self._updating=False
            self.schedule()
        self._region_selector=RectangleSelector(graph_axes[0], selected,
            useblit=False,button=[1],minspanx=0,minspany=0,spancoords='pixels',interactive=False)
        self.status.setText('Drag a rectangle on the selected bias graph to define the zoom inset')

    def _inset_drag_start(self,event):
        if self._region_selector is not None or event.button!=1:return
        if self.toolbar is not None and self.toolbar.mode:return
        ax=event.inaxes
        if ax is None or not getattr(ax,'_spm_inset',False):return
        index=getattr(ax,'_spm_graph_index',None)
        if index is None or not (0<=index<len(self.project['graphs'])):return
        parent=getattr(ax,'_spm_inset_parent',None)
        if parent is None:return
        pos=list(self.project['graphs'][index].get('inset',{}).get('position',[.57,.53,.40,.40]))
        self._inset_drag=(index,event.x,event.y,pos,parent.bbox.width,parent.bbox.height)

    def _inset_drag_end(self,event):
        state=self._inset_drag;self._inset_drag=None
        if state is None or event.x is None or event.y is None:return
        index,old_x,old_y,position,width,height=state
        if width<=0 or height<=0:return
        dx=(event.x-old_x)/width;dy=(event.y-old_y)/height
        if abs(dx)+abs(dy)<.004:return
        position[0]=max(0,min(1-position[2],position[0]+dx))
        position[1]=max(0,min(1-position[3],position[1]+dy))
        self.project['graphs'][index].setdefault('inset',{})['position']=position
        if self.graph_list.currentRow()==index:
            self._updating=True
            for widget,value in zip(self.g_inset_pos,position):widget.setValue(value*100.)
            _combo_set(self.g_inset_preset,'Custom')
            self._updating=False
        self.schedule()

    def add_session(self):
        if not self._current_graph():self.add_graph()
        directory=QFileDialog.getExistingDirectory(self,'Select spectroscopy session (contains session.json / height_*.npz)',
                        str(self.context.get('root',Path.home())))
        if not directory:return
        try: paths=session_files(Path(directory))
        except Exception as exc:QMessageBox.warning(self,'Session error',str(exc));return
        if not paths:
            QMessageBox.warning(self,'No spectra found','No height_*.npz, height_*.csv or .dat files.');return
        self._add_paths(paths)

    def add_spectra(self):
        if not self._current_graph():self.add_graph()
        paths,_=QFileDialog.getOpenFileNames(self,'Choose spectra files',str(self.context.get('root',Path.home())),
                  'Spectroscopy (*.npz *.csv *.dat *.txt);;All files (*)')
        if paths:self._add_paths([Path(p) for p in paths])

    def _add_paths(self,paths):
        g=self._current_graph()
        if g is None:return
        errors=[];new=[]
        for p in paths:
            p=str(Path(p).resolve())
            try:
                if p not in self.spectra:self.spectra[p]=read_spectrum(Path(p))
                spec=self.spectra[p]
                if any(tr['path']==p for tr in g['traces']):continue
                # Attach to the image's active scan by default; can be changed per trace.
                scan=(self._current_image() or {}).get('scan') or next(iter(self.scans),'')
                new.append({'path':p,'label':Path(p).stem,'color':PALETTE[len(g['traces'])%len(PALETTE)],
                            'direction':'Both','scan':scan,'manual_nm':None,'enabled':True,'fit_enabled':True})
                g['traces'].append(new[-1])
            except Exception as exc:errors.append(f'{Path(p).name}: {exc}')
        if new and len(g['traces'])==len(new):
            preferred=sm.preferred_channel(self.spectra[new[0]['path']],self._method())
            if preferred:g['channel']=preferred
        if new:self._apply_method_ui()
        index=self.graph_list.currentRow()
        self.on_graph_select(index)
        if g['traces']:self.trace_list.setCurrentRow(len(g['traces'])-1)
        self.schedule()
        if errors:
            QMessageBox.warning(self,'Some files could not be loaded','\n'.join(errors[:15]))
        else:self.status.setText(f'Loaded {len(new)} spectrum files')

    def on_trace_select(self,_index):
        if self._updating:return
        tr=self._current_trace()
        self._updating=True
        if tr:
            self.t_label.setText(tr.get('label',''))
            _combo_set(self.t_mode,tr.get('direction','Both'))
            self.t_color.setStyleSheet(f"background-color: {tr.get('color','#C8102E')}; color: white;")
            self._set_scan_combo(self.t_scan,tr.get('scan',''),True)
            manual=tr.get('manual_nm')
            self.t_manualx.setText(str(manual[0]) if manual is not None else '')
            self.t_manualy.setText(str(manual[1]) if manual is not None else '')
            self.t_enabled.setChecked(tr.get('enabled',True))
            self.t_fit_enabled.setChecked(tr.get('fit_enabled',True))
        self._updating=False

    def update_trace(self,*_):
        if self._updating:return
        tr=self._current_trace()
        if tr is None:return
        tr.update({'label':self.t_label.text().strip(), 'direction':self.t_mode.currentText(),
                   'scan':self.t_scan.currentData() or '', 'enabled':self.t_enabled.isChecked(),
                   'fit_enabled':self.t_fit_enabled.isChecked()})
        try:
            mx=self.t_manualx.text().strip();my=self.t_manualy.text().strip()
            tr['manual_nm']=[float(mx),float(my)] if mx and my else None
        except ValueError:
            tr['manual_nm']=None
        i=self.trace_list.currentRow()
        if i>=0:
            spec=self.spectra.get(tr['path'])
            h=f"+{spec.z_nm:.3f} nm" if spec and math.isfinite(spec.z_nm) else 'Z ?'
            self.trace_list.item(i).setText(f"{tr['label']}  |  {h}")
        self.schedule()

    def choose_color(self):
        tr=self._current_trace()
        if not tr:return
        chosen=QColorDialog.getColor(QColor(tr.get('color','#C8102E')),self,'Spectrum forward colour')
        if chosen.isValid():
            tr['color']=chosen.name();self.t_color.setStyleSheet(f'background: {tr["color"]};color:white;')
            self.schedule()

    def remove_trace(self):
        g=self._current_graph();i=self.trace_list.currentRow()
        if not g or i<0:return
        g['traces'].pop(i);self.on_graph_select(self.graph_list.currentRow())
        self.trace_list.setCurrentRow(min(i,len(g['traces'])-1));self.schedule()

    def update_global(self,*_):
        if self._updating:return
        self.project['options'].update({'title':self.figure_title.text().strip(),
                 'font':self.font_size.value(),'width':self.figure_width.value(),
                 'share_bias':self.share_bias.isChecked(),'share_signal':self.share_signal.isChecked(),
                 'panel_labels':self.panel_labels.isChecked(),
                 'bias_min':self.bias_min.text().strip(),'bias_max':self.bias_max.text().strip(),
                 'signal_min':self.signal_min.text().strip(),'signal_max':self.signal_max.text().strip(),
                 'didv_source':self.didv_source.currentText(),'normalize':self.normalize.isChecked(),
                 'smooth':int(self.smooth.value()),'average':self.average.isChecked(),
                 'offset':self.offset.text().strip(),'log_y':self.log_y.isChecked(),
                 'x_channel':self.x_channel.currentText().strip()})
        self.schedule()

    def _load_required_scans(self):
        for item in self.project.get('images',[]):
            path=item.get('scan','')
            if path and path not in self.scans and Path(path).is_file():
                self.scans[path]=read_scan(path)
        for g in self.project.get('graphs',[]):
            for tr in g.get('traces',[]):
                path=tr.get('scan','')
                if path and path not in self.scans and Path(path).is_file():
                    self.scans[path]=read_scan(path)

    def _load_required_spectra(self):
        for g in self.project.get('graphs',[]):
            for tr in g.get('traces',[]):
                p=tr.get('path','')
                if p and p not in self.spectra and Path(p).is_file():
                    self.spectra[p]=read_spectrum(Path(p))

    def redraw(self):
        # Old figure event selectors must not retain references to stale axes.
        if self._region_selector is not None:
            self._region_selector.set_active(False)
            self._region_selector=None
        self._inset_drag=None
        try:
            self._load_required_scans();self._load_required_spectra()
            fig,rows,warnings=create_figure(self.project,self.scans,self.spectra)
            self._diagnostics=rows;self._warnings=warnings
            if self.canvas is not None:
                self.canvas_holder.takeWidget()
                self.canvas.setParent(None)
                self.canvas.deleteLater()
            if self.toolbar is not None:
                self.right_layout.removeWidget(self.toolbar)
                self.toolbar.setParent(None)
                self.toolbar.deleteLater()
                self.toolbar=None
            self._figure=fig
            self.canvas=FigureCanvasQTAgg(fig)
            self.canvas.mpl_connect('button_press_event',self._inset_drag_start)
            self.canvas.mpl_connect('button_release_event',self._inset_drag_end)
            self.canvas.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)
            # A pixel-sized scrollable preview, no loss of image aspect ratio.
            size=fig.get_size_inches();self.canvas.setFixedSize(int(size[0]*105),int(size[1]*105))
            self.canvas_holder.setWidget(self.canvas)
            self.toolbar=NavigationToolbar2QT(self.canvas,self)
            self.right_layout.insertWidget(0,self.toolbar)
            self.canvas.draw_idle()
            self.status.setText(f'{len(self.project["images"])} images • '
                                f'{len(self.project["graphs"])} graphs • {len(warnings)} warnings')
            lines=['W A R N I N G S']+[f'• {s}' for s in warnings[:50]] if warnings else []
            accepted=[r for r in rows if r.get('accepted')]
            lines += [f'{len(accepted)} accepted feature candidates / {len(rows)} diagnostic entries']
            for r in accepted[:25]:
                lines.append(f"• {r.get('trace','')}: {r.get('direction','')} "
                             f"Z={r.get('z_offset_nm',float('nan')):.3g} nm "
                             f"V={r.get('voltage_V',float('nan')):.4g} V")
            self.diagnostics.setPlainText('\n'.join(lines))
        except Exception as exc:
            self._figure=None  # never export an outdated preview on render failure
            self.status.setText('Preview error')
            self.diagnostics.setPlainText(f'Figure construction failed:\n{type(exc).__name__}: {exc}')

    def export(self,fmt):
        self.redraw_timer.stop();self.redraw()
        if self._figure is None:return
        home=Path(self.context.get('output_dir') or Path.home())
        suggested=home / f'{self._method().key}_spectroscopy_figure.{fmt}'
        filename,_=QFileDialog.getSaveFileName(self,f'Export paper figure ({fmt})',str(suggested),
                                              f'{fmt.upper()} (*.{fmt})')
        if not filename:return
        path=Path(filename);path=path if path.suffix.lower()=='.'+fmt else path.with_suffix('.'+fmt)
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            from ..core.plots import savefig_maybe_transparent
            transparent=self.transparent_export.isChecked()
            try:self.main_window.set_export_transparent(transparent)
            except Exception:pass
            savefig_maybe_transparent(self._figure,path,transparent=transparent,format=fmt,dpi=600,
                                      bbox_inches='tight',pad_inches=.01)
            # Always accompany publication figures with exact settings and feature diagnostics.
            self._write_project(path.with_suffix('.figure.json'))
            self._write_diagnostics(path.with_suffix('.fits.csv'))
            QMessageBox.information(self,'Figure exported',f'Saved:\n{path}\n'
                         f'{path.with_suffix(".figure.json")}\n{path.with_suffix(".fits.csv")}')
        except Exception as exc:QMessageBox.critical(self,'Export failed',str(exc))

    def _write_project(self,path):
        path.write_text(json.dumps(self.project,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

    def _write_diagnostics(self,path):
        fields=['graph','trace','source','channel','direction','z_offset_nm','kind',
                'accepted','voltage_V','voltage_uncertainty_V','BIC_gain','reason','regression']
        with path.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
            writer.writeheader()
            writer.writerows([{**r,'regression':json.dumps(r.get('regression',{}))} for r in self._diagnostics])

    def save_project(self):
        filename,_=QFileDialog.getSaveFileName(self,'Save figure setup',
             str(Path(self.context.get('output_dir',Path.home()))/'spectroscopy_figure.figure.json'),
             'Figure setup (*.json)')
        if filename:
            try:self._write_project(Path(filename))
            except Exception as exc:QMessageBox.critical(self,'Save error',str(exc))

    def open_project(self):
        filename,_=QFileDialog.getOpenFileName(self,'Load figure setup',
             str(self.context.get('root',Path.home())),'Figure setup (*.json)')
        if not filename:return
        try:
            data=json.loads(Path(filename).read_text(encoding='utf-8'))
            if not isinstance(data.get('images'),list) or not isinstance(data.get('graphs'),list):
                raise ValueError('Not a valid figure setup (missing images or graphs)')
            self.project=data
            self._load_required_scans();self._load_required_spectra()
            self._sync_all()
            options=data.get('options',{})
            self._updating=True
            self.figure_title.setText(options.get('title',''))
            self.figure_width.setValue(float(options.get('width',11)))
            self.font_size.setValue(float(options.get('font',8)))
            self.share_bias.setChecked(bool(options.get('share_bias',True)))
            self.share_signal.setChecked(bool(options.get('share_signal',True)))
            self.panel_labels.setChecked(bool(options.get('panel_labels',True)))
            for field,key in ((self.bias_min,'bias_min'),(self.bias_max,'bias_max'),
                              (self.signal_min,'signal_min'),(self.signal_max,'signal_max')):
                field.setText(str(options.get(key,'')))
            options.setdefault('method',sm.DEFAULT_METHOD)   # setups saved before v0.0.10 are Δf(V)
            self._updating=False
            self._apply_method_ui()
            self.image_list.setCurrentRow(0);self.graph_list.setCurrentRow(0)
            self.schedule()
        except Exception as exc:QMessageBox.critical(self,'Load error',str(exc))


def create_tool(main_window: Any, context: dict):
    return Composer(main_window,context)
