"""Declarative inspector for manifest-based modules: no module-specific GUI edits."""
from __future__ import annotations
from PySide6.QtWidgets import (QWidget,QFormLayout,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,
 QCheckBox,QSpinBox,QDoubleSpinBox,QPushButton,QFileDialog,QScrollArea,
 QGroupBox,QListWidget,QColorDialog,QGridLayout,QPlainTextEdit,QSlider,QFrame,QProgressBar)
from PySide6.QtCore import Signal,Qt,QRectF
import json
from pathlib import Path
from PySide6.QtGui import QImage, QPixmap, QPainter
from .live_analysis import LivePlot
from spm_studio.shared.ui_strings import ui_label, add_key_items, combo_key, set_combo_key

class ModulePanel(QWidget):
    runRequested=Signal()
    runSelectionChanged=Signal(str)
    saveCommentRequested=Signal(str,str)
    preferRequested=Signal(str)
    changed=Signal()
    masksChanged=Signal()
    roiToolRequested=Signal(str)
    undoLineRequested=Signal()
    clearLinesRequested=Signal()
    deleteSelectionRequested=Signal(int)
    selectionChosen=Signal(int)
    gifExportRequested=Signal(dict)
    gifEstimateRequested=Signal(dict)
    channelTitleEdited=Signal(str)
    viewerDisplayToggled=Signal(bool)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.module=None
        self.widgets={}
        self.masks=[]
        self.mask_history=[]
        self._updating_mask=False
        layout=QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(10)
        self.heading=QLabel('Choose a tool in Tools')
        self.heading.setObjectName('heading')
        self.heading.setWordWrap(True)
        self.description=QLabel('')
        self.description.setWordWrap(True)
        self.description.setObjectName('hint')
        self.form=QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status=QLabel('')
        self.status.setWordWrap(True)
        self.run_button=QPushButton('Run analysis')
        self.run_button.setProperty('primary',True)
        try:
            from spm_studio.shared.appearance import set_icon
            set_icon(self.run_button,'run',color_token='accent_fg')
        except Exception:
            pass
        self.run_button.clicked.connect(self.runRequested)
        # v0.0.5: the tool's own README, one click away at the top of the panel.
        header=QHBoxLayout()
        header.setContentsMargins(0,0,0,0);header.setSpacing(8)
        header.addWidget(self.heading,1)
        self._readme_path=None
        self.readme_button=QPushButton('Read me')
        self.readme_button.setObjectName('ToolReadmeButtonV005')
        self.readme_button.setToolTip('Open the README of this tool: what it does, the method, its parameters and outputs')
        try:
            from spm_studio.shared.appearance import set_icon
            set_icon(self.readme_button,'book')
        except Exception:
            pass
        self.readme_button.clicked.connect(self.open_readme)
        self.readme_button.hide()
        header.addWidget(self.readme_button,0,Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addWidget(self.description)
        # v34: every tool can render its results with the display set up on the scan.
        self.display_group=QGroupBox('Figure')
        self.display_group.setObjectName('UseScanDisplayV34')
        dg=QFormLayout(self.display_group)
        self.use_scan_display=QCheckBox('Use the current scan display (colormap, contrast, colourbar title)')
        self.use_scan_display.setChecked(True)
        self.use_scan_display.setToolTip('The tool does its normal analysis, then draws its result images with exactly what you '
                                         'set on each channel in the viewer: colormap, colour range and title.')
        self.use_scan_display.toggled.connect(self.viewerDisplayToggled)
        # v0.8: figures always use the scan display (colormap, contrast); the switch is kept for API only.
        self.use_scan_display.setVisible(False)
        dg.addRow(self.use_scan_display)
        self.colorbar_title=QLineEdit()
        self.colorbar_title.setObjectName('ToolColorbarTitleV34')
        self.colorbar_title.setPlaceholderText('e.g. $V_{exc}$, $\\Delta f$, $Z$')
        self.colorbar_title.setToolTip('Title of the colourbar of the channel shown in the viewer (LaTeX between $ $). '
                                       'It is used on the scan, in the tool results and in exports.')
        self.colorbar_title.editingFinished.connect(lambda:self.channelTitleEdited.emit(self.colorbar_title.text().strip()))
        dg.addRow('Colourbar title',self.colorbar_title)
        dg.setContentsMargins(10,8,10,10)
        self.display_group.setVisible(False)
        layout.addWidget(self.display_group)
        # v14: show an actual SVG/PNG picker before the parameter form.  The
        # previous generic tiny '…' field was easy to miss in Tool settings.
        self.artwork_group=QGroupBox('Molecule artwork')
        art_layout=QVBoxLayout(self.artwork_group)
        self.molecule_artwork_help=QLabel('Choose the molecule drawing; then set its real X/Y size in nm below. No external image editor is needed.')
        self.molecule_artwork_help.setWordWrap(True)
        self.molecule_artwork_help.setObjectName('hint')
        self.molecule_artwork_help.setVisible(False)
        art_layout.addWidget(self.molecule_artwork_help)
        art_row=QHBoxLayout()
        self.molecule_file_path=QLineEdit()
        self.molecule_file_path.setObjectName('MoleculeSVGFilePath_v14')
        self.molecule_file_path.setPlaceholderText('Choose SVG or PNG…')
        self.molecule_file_path.setAccessibleName('Molecule SVG/PNG file path')
        self.molecule_file_path.textChanged.connect(self._update_molecule_artwork)
        self.molecule_file_path.textChanged.connect(self.changed)
        self.molecule_file_button=QPushButton('Load molecule SVG / PNG…')
        self.molecule_file_button.setObjectName('LoadMoleculeSVG_v14')
        self.molecule_file_button.setAccessibleName('Load molecule SVG or PNG file')
        self.molecule_file_button.clicked.connect(self._pick_molecule_artwork)
        art_row.addWidget(self.molecule_file_path,1)
        art_layout.addLayout(art_row)
        art_layout.addWidget(self.molecule_file_button)
        self.molecule_artwork_status=QLabel('No file selected')
        self.molecule_artwork_status.setObjectName('hint')
        self.molecule_artwork_status.setWordWrap(True)
        art_layout.addWidget(self.molecule_artwork_status)
        self.molecule_artwork_thumbnail=QLabel('Preview')
        self.molecule_artwork_thumbnail.setObjectName('card')
        self.molecule_artwork_thumbnail.setMinimumHeight(105)
        self.molecule_artwork_thumbnail.setMaximumHeight(160)
        self.molecule_artwork_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.molecule_artwork_thumbnail.setWordWrap(True)
        art_layout.addWidget(self.molecule_artwork_thumbnail)
        self.artwork_group.setVisible(False)
        layout.addWidget(self.artwork_group)
        layout.addLayout(self.form)
        self.preview=LivePlot()
        self.preview.setVisible(False)
        self.preview.rangeEdited.connect(self._range_dragged)
        self.preview.rangePreview.connect(self._preview_range)
        layout.addWidget(self.preview)
        self.molecule_preview=QLabel('Run Lattice measurements, then choose the artwork.')
        self.molecule_preview.setMinimumHeight(180)
        self.molecule_preview.setMaximumHeight(320)
        self.molecule_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.molecule_preview.setWordWrap(True)
        self.molecule_preview.setObjectName('card')
        self.molecule_preview.setVisible(False)
        layout.addWidget(self.molecule_preview)
        # v29: animated transparency sweep (base → layer 2 → … → top layer fully opaque)
        self.gif_group=QGroupBox('Animated overlay (GIF)')
        gif_form=QFormLayout(self.gif_group)
        gif_help=QLabel('Bottom layer = the channel shown in the viewer, unless that channel is also one of '
                        'your layers (then layer 2 is the bottom). The GIF starts with the bottom layer alone and '
                        'fades each higher layer from the start to the end opacity, in order (100 % = only the top '
                        'layer is visible at the end).')
        gif_help.setWordWrap(True);gif_help.setObjectName('hint')
        self.gif_group.setToolTip(gif_help.text())
        gif_help.setText('Fades each layer in, bottom to top.')
        gif_form.addRow(gif_help)
        self.gif_duration=QDoubleSpinBox();self.gif_duration.setRange(0.5,120.);self.gif_duration.setDecimals(1)
        self.gif_duration.setSingleStep(.5);self.gif_duration.setValue(6.);self.gif_duration.setSuffix(' s')
        self.gif_fps=QSpinBox();self.gif_fps.setRange(5,50);self.gif_fps.setValue(25);self.gif_fps.setSuffix(' fps')
        self.gif_size=QComboBox()
        for label,px in (('720 px (small file)',720),('1080 px (Full-HD slide)',1080),
                         ('1440 px (high quality)',1440),('2160 px (4K, very large file)',2160)):
            self.gif_size.addItem(label,px)
        self.gif_size.setCurrentIndex(2)
        self.gif_hold=QDoubleSpinBox();self.gif_hold.setRange(0.,40.);self.gif_hold.setValue(10.)
        self.gif_hold.setSuffix(' % at start & end');self.gif_hold.setDecimals(0)
        self.gif_alpha0=QSpinBox();self.gif_alpha0.setRange(0,100);self.gif_alpha0.setValue(0);self.gif_alpha0.setSuffix(' %')
        self.gif_alpha1=QSpinBox();self.gif_alpha1.setRange(0,100);self.gif_alpha1.setValue(100);self.gif_alpha1.setSuffix(' %')
        fade_row=QWidget();fr=QHBoxLayout(fade_row);fr.setContentsMargins(0,0,0,0)
        fr.addWidget(QLabel('from'));fr.addWidget(self.gif_alpha0);fr.addWidget(QLabel('to'));fr.addWidget(self.gif_alpha1);fr.addStretch(1)
        self.gif_scalebar=QCheckBox('Scale bar');self.gif_scalebar.setChecked(True)
        self.gif_labels=QCheckBox('Channel labels');self.gif_labels.setChecked(True)
        self.gif_ease=QCheckBox('Ease in / out');self.gif_ease.setChecked(True)
        self.gif_mp4=QCheckBox('Also MP4 (ffmpeg)');self.gif_mp4.setChecked(False)
        self.gif_button=QPushButton('Export GIF…')
        self.gif_button.clicked.connect(self._request_gif)
        gif_form.addRow('Total duration',self.gif_duration)
        gif_form.addRow('Frame rate',self.gif_fps)
        gif_form.addRow('Longest side',self.gif_size)
        gif_form.addRow('Hold',self.gif_hold)
        gif_form.addRow('Layer opacity',fade_row)
        gif_form.addRow('',self.gif_scalebar);gif_form.addRow('',self.gif_labels)
        gif_form.addRow('',self.gif_ease);gif_form.addRow('',self.gif_mp4)
        gif_form.addRow(self.gif_button)
        # v0.0.21: size of the GIF / MP4 these settings give, updated while they are changed.
        self.gif_size_estimate=QLabel('')
        self.gif_size_estimate.setObjectName('hint')
        self.gif_size_estimate.setWordWrap(True)
        self.gif_size_estimate.setToolTip('Estimated size of the file that Export GIF… will write: a few frames are '
                                          'rendered and encoded exactly like the export (same size, palette and '
                                          'dithering). Fewer fps, a shorter duration, a smaller longest side or a '
                                          'longer hold make the file smaller.')
        gif_form.addRow('File size',self.gif_size_estimate)
        from PySide6.QtCore import QTimer
        self._gif_estimate_timer=QTimer(self)
        self._gif_estimate_timer.setSingleShot(True)
        self._gif_estimate_timer.setInterval(600)
        self._gif_estimate_timer.timeout.connect(lambda:self.gifEstimateRequested.emit(self._gif_options()))
        for w in (self.gif_duration,self.gif_hold):w.valueChanged.connect(self.schedule_gif_estimate)
        for w in (self.gif_fps,self.gif_alpha0,self.gif_alpha1):w.valueChanged.connect(self.schedule_gif_estimate)
        self.gif_size.currentIndexChanged.connect(self.schedule_gif_estimate)
        for w in (self.gif_scalebar,self.gif_labels,self.gif_ease,self.gif_mp4):w.toggled.connect(self.schedule_gif_estimate)
        self.gif_group.setVisible(False)
        layout.addWidget(self.gif_group)
        self.mask_group=QGroupBox('Masks')
        mask_layout=QVBoxLayout(self.mask_group)
        self.mask_list=QListWidget()
        self.mask_list.setMaximumHeight(102)
        self.mask_list.currentRowChanged.connect(self._choose_mask)
        mask_layout.addWidget(self.mask_list)
        mask_buttons=QHBoxLayout()
        self.add_mask=QPushButton('+ New')
        self.delete_mask=QPushButton('Delete')
        self.undo_mask=QPushButton('Undo')
        self.reset_mask=QPushButton('Reset')
        self.mask_color=QPushButton('Colour…')
        self.add_mask.clicked.connect(self._new_mask)
        self.delete_mask.clicked.connect(self._remove_mask)
        self.undo_mask.clicked.connect(self._undo_mask)
        self.reset_mask.clicked.connect(self._reset_mask)
        self.mask_color.clicked.connect(self._pick_color)
        for b in (self.add_mask,self.delete_mask,self.undo_mask):mask_buttons.addWidget(b)
        extras=QHBoxLayout()
        for b in (self.reset_mask,self.mask_color):extras.addWidget(b)
        mask_layout.addLayout(mask_buttons)
        mask_layout.addLayout(extras)
        edits=QFormLayout()
        self.mask_name=QLineEdit()
        self.mask_min=QLineEdit()
        self.mask_max=QLineEdit()
        self.mask_gauss=QSpinBox();self.mask_gauss.setRange(0,8);self.mask_gauss.setValue(2)
        self.mask_peaks=QLineEdit()
        self.mask_peaks.setPlaceholderText('e.g. 0.24, 0.38 (SI)')
        for name,widget in [('Name',self.mask_name),('Min. (SI)',self.mask_min),
                            ('Max. (SI)',self.mask_max),('Gaussians',self.mask_gauss),('Initial μ (SI)',self.mask_peaks)]:
            edits.addRow(name,widget)
        mask_layout.addLayout(edits)
        for w in (self.mask_name,self.mask_min,self.mask_max):
            w.editingFinished.connect(self._save_mask_fields)
        self.mask_gauss.valueChanged.connect(self._save_mask_fields)
        self.mask_peaks.editingFinished.connect(self._save_mask_fields)
        self.mask_min.textChanged.connect(self._preview_mask_fields)
        self.mask_max.textChanged.connect(self._preview_mask_fields)
        file_buttons=QHBoxLayout()
        save=QPushButton('Save…');load=QPushButton('Load…')
        save.clicked.connect(self._save_masks)
        load.clicked.connect(self._load_masks)
        file_buttons.addWidget(save);file_buttons.addWidget(load)
        mask_layout.addLayout(file_buttons)
        layout.addWidget(self.mask_group)
        self.mask_group.hide()
        self.roi_group=QGroupBox('Selections')
        roi_buttons=QGridLayout(self.roi_group)
        self.draw_line=QPushButton('Line')
        self.undo_line=QPushButton('Undo')
        self.clear_lines=QPushButton('Clear')
        self.delete_selection=QPushButton('Delete')
        self.selection_list=QListWidget()
        self.selection_list.setMaximumHeight(90)
        self.selection_list.setToolTip('Click a selection to highlight it. Delete removes only that selection.')
        self.selection_list.currentRowChanged.connect(self.selectionChosen)
        self.selection_status=QLabel('Draw on the scan; drag handles to adjust.')
        self.selection_status.setObjectName('hint')
        self.selection_status.setWordWrap(True)
        self.draw_rect=QPushButton('Region')
        self.draw_point=QPushButton('Point')
        for i,b in enumerate((self.draw_line,self.draw_rect,self.draw_point,
                               self.delete_selection,self.undo_line,self.clear_lines)):
            roi_buttons.addWidget(b,i//3,i%3)
        self.draw_line.clicked.connect(lambda:self.roiToolRequested.emit('line'))
        self.draw_rect.clicked.connect(lambda:self.roiToolRequested.emit('rectangle'))
        self.draw_point.clicked.connect(lambda:self.roiToolRequested.emit('point'))
        self.undo_line.clicked.connect(self.undoLineRequested)
        self.clear_lines.clicked.connect(self.clearLinesRequested)
        self.delete_selection.clicked.connect(lambda:self.deleteSelectionRequested.emit(self.selection_list.currentRow()))
        layout.addWidget(self.roi_group)
        layout.addWidget(self.selection_status)
        layout.addWidget(self.selection_list)
        self.roi_group.hide()
        self.selection_status.hide()
        self.selection_list.hide()
        self.line_info=QLabel('Draw a line across the feature; drag an end to adjust.')
        self.line_info.setObjectName('hint')
        self.line_info.setWordWrap(True)
        self.line_info.hide()
        layout.addWidget(self.line_info)
        layout.addWidget(self.status)
        layout.addWidget(self.run_button)
        # v0.0.5: a readable progress bar right under Run (the small one in Logs was easy to miss).
        self.activity=QFrame()
        self.activity.setObjectName('activityStrip')
        activity_layout=QVBoxLayout(self.activity)
        activity_layout.setContentsMargins(10,8,10,10);activity_layout.setSpacing(6)
        self.activity_label=QLabel('')
        self.activity_label.setWordWrap(True)
        self.activity_bar=QProgressBar()
        self.activity_bar.setObjectName('ToolRunProgressV005')
        self.activity_bar.setProperty('role','activity')
        self.activity_bar.setRange(0,100)
        self.activity_bar.setTextVisible(True)
        self.activity_bar.setFormat('%p %')
        activity_layout.addWidget(self.activity_label)
        activity_layout.addWidget(self.activity_bar)
        self.activity.hide()
        layout.addWidget(self.activity)
        self._activity_token=0
        # Persisted scientific records, deliberately separate from widget settings.
        self.results_group=QGroupBox('Saved runs')
        results_layout=QVBoxLayout(self.results_group)
        self.run_selection=QComboBox()
        self.run_selection.currentIndexChanged.connect(lambda _:
            self.runSelectionChanged.emit(str(self.run_selection.currentData() or '')))
        self.result_text=QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(145)
        self.result_text.setMaximumHeight(250)
        self.result_text.setPlaceholderText('Past runs of this tool on this scan')
        self.comment_entry=QLineEdit()
        self.comment_entry.setPlaceholderText('Add a note…')
        self.comment_status=QComboBox()
        add_key_items(self.comment_status,['observation','interpretation','hypothesis','uncertainty','contradiction','confirmed_conclusion'])
        self.comment_status.setAccessibleName('Note classification')
        comment_buttons=QHBoxLayout()
        self.save_comment=QPushButton('Save note')
        self.save_comment.clicked.connect(lambda:
            self.saveCommentRequested.emit(self.comment_entry.text(),combo_key(self.comment_status)))
        self.prefer_run=QPushButton('Prefer')
        self.prefer_run.setToolTip('Mark this run as the preferred result')
        self.prefer_run.clicked.connect(lambda:
            self.preferRequested.emit(str(self.run_selection.currentData() or '')))
        comment_buttons.addWidget(self.save_comment)
        comment_buttons.addWidget(self.prefer_run)
        results_layout.addWidget(self.run_selection)
        results_layout.addWidget(self.result_text)
        results_layout.addWidget(self.comment_entry)
        results_layout.addWidget(self.comment_status)
        results_layout.addLayout(comment_buttons)
        layout.addWidget(self.results_group)
        layout.addStretch()
        self.run_button.setEnabled(False)

    # ---- v0.0.5: README button and run progress
    def open_readme(self):
        if self._readme_path is None:return
        from .settings_dialog import GuideDialog
        name=self.module.name if self.module is not None else self._readme_path.parent.name
        GuideDialog(self._readme_path,'Read me — '+name,self.window()).exec()

    def _update_readme(self,mod):
        from spm_studio.core import paths
        self._readme_path=None
        if mod is not None and getattr(mod,'mode','')!='legacy':
            try:self._readme_path=paths.module_readme(mod.path)
            except OSError:self._readme_path=None
        self.readme_button.setVisible(self._readme_path is not None)

    def set_run_state(self,state,text='',value=None):
        """``state``: preparing · running · progress · done · failed · idle."""
        from PySide6.QtCore import QTimer
        self._activity_token+=1
        token=self._activity_token
        if state=='idle':
            self.activity.hide();return
        self.activity.show()
        if text:self.activity_label.setText(text)
        if state in ('preparing','running'):
            self.activity_bar.setRange(0,0)            # busy until the tool reports a percentage
        elif state=='progress':
            self.activity_bar.setRange(0,100)
            self.activity_bar.setValue(max(0,min(100,int(round(float(value or 0))))))
        elif state in ('done','failed'):
            self.activity_bar.setRange(0,100)
            self.activity_bar.setValue(100 if state=='done' else 0)
            QTimer.singleShot(5000 if state=='done' else 12000,
                              lambda:self.activity.hide() if token==self._activity_token else None)

    def set_module(self,mod,channel_names=None,selected_channel=''):
        self.module=mod
        self._update_readme(mod)
        self.widgets={}
        self.masks=[]
        self.mask_history=[]
        interaction=mod.interaction if mod else 'none'
        selection=(mod.selection or {}) if mod else {}
        tools=selection.get('tools',[])
        self.mask_group.setVisible(interaction=='histogram_masks')
        preview=selection.get('preview','none')
        self.preview.setVisible(preview in ('histogram','profiles'))
        self.molecule_preview.setVisible(bool(mod and mod.id=='channel_overlay'))
        self.gif_group.setVisible(bool(mod and mod.id=='channel_overlay'))
        self.display_group.setVisible(mod is not None)
        if mod and mod.id=='channel_overlay':
            self.molecule_preview.setText('Select the second channel to show the live overlay here and on the scan.')
        self.artwork_group.setVisible(bool(mod and mod.id=='molecule_placement'))
        self.line_info.setVisible(preview=='profiles')
        self.roi_group.setVisible(bool(tools))
        self.selection_status.setVisible(bool(tools))
        self.selection_list.setVisible(bool(tools))
        self.draw_line.setVisible('line' in tools)
        self.draw_rect.setVisible('rectangle' in tools)
        self.draw_point.setVisible('point' in tools)
        self.undo_line.setVisible(bool(tools))
        self.clear_lines.setVisible(bool(tools))
        self.delete_selection.setVisible(bool(tools))
        self.set_selections([])
        while self.form.rowCount():
            self.form.removeRow(0)
        if mod is None:
            self.heading.setText('Select a tool in the sidebar')
            self.run_button.setEnabled(False)
            return
        self.heading.setText(f'{mod.name}  ·  v{mod.version}')
        self.description.setText(mod.description)
        for name,desc in mod.parameters.items():
            if mod.id=='molecule_placement' and name=='molecule_image':
                # Bind the visible dedicated file picker to the exact manifest
                # parameter consumed by both the preview worker and run_module.
                self.molecule_file_path.setText(str(desc.get('default','')))
                self.widgets[name]=self.molecule_file_path
                continue
            t=desc['type']
            default=desc.get('default','')
            if t=='bool':
                widget=QCheckBox()
                widget.setChecked(bool(default))
            elif t=='integer':
                widget=QSpinBox()
                widget.setRange(int(desc.get('min',-1000000)),int(desc.get('max',1000000)))
                widget.setValue(int(default or 0))
            elif t=='float' and name=='rotation_offset_deg' and mod.id=='molecule_placement':
                widget=QDoubleSpinBox()
                widget.setRange(-360.0,360.0)
                widget.setDecimals(2)
                widget.setSingleStep(1.0)
                widget.setSuffix('°')
                widget.setValue(float(default or 0))
                widget.setToolTip('Rotate molecular SVG relative to the lattice alignment. Changes update the live preview.')
            elif t=='float' and mod.id=='channel_overlay' and name.startswith('opacity_'):
                widget=QDoubleSpinBox()
                widget.setRange(0.0,1.0);widget.setDecimals(2)
                widget.setSingleStep(.05);widget.setValue(float(default or 0))
                slider=QSlider(Qt.Orientation.Horizontal)
                slider.setRange(0,100);slider.setValue(int(widget.value()*100))
                slider.valueChanged.connect(lambda v,w=widget:w.setValue(v/100.))
                widget.valueChanged.connect(lambda v,bar=slider:bar.setValue(round(v*100)))
                container=QWidget();line=QHBoxLayout(container)
                line.setContentsMargins(0,0,0,0)
                line.addWidget(slider,1);line.addWidget(widget)
                self.form.addRow(ui_label(desc.get('label',name)),container)
            elif t=='float':
                widget=QLineEdit(str(default if default is not None else 0))
                widget.setToolTip('Enter a decimal/scientific-notation value, in the declared unit')
            elif t in ('choice','channel','direction'):
                widget=QComboBox()
                choices=desc.get('choices',[])
                if t=='channel': choices=channel_names or []
                if t=='direction': choices=['forward','backward']
                if t=='channel':
                    if mod.id=='channel_overlay' and name!='channel_2':
                        widget.addItem('(none)','')
                    for v in choices:widget.addItem(str(v),str(v))
                    if mod.id=='channel_overlay' and name=='channel_2':
                        second=next((c for c in choices if c!=selected_channel), '')
                        set_combo_key(widget,second)
                    else:set_combo_key(widget,str(default))
                else:
                    add_key_items(widget,[str(v) for v in choices])
                    from ..core.plot_settings import is_colormap_parameter,all_colormap_choices
                    if is_colormap_parameter(name):
                        # v34: every colormap of the viewer (built-in, Gwyddion, custom files)
                        have={str(v) for v in choices}
                        for label,key in all_colormap_choices():
                            if key not in have:widget.addItem(ui_label(label),key)
                    set_combo_key(widget,str(default))
            elif t in ('file','folder','color'):
                container=QWidget()
                h=QHBoxLayout(container)
                h.setContentsMargins(0,0,0,0)
                field=QLineEdit(str(default))
                browse=QPushButton('Color…' if t=='color' else '…')
                browse.setAccessibleName('Choose '+ui_label(desc.get('label',name)).lower())
                browse.setToolTip('Choose arrow/legend color' if t=='color' else ('Choose a file' if t=='file' else 'Choose a folder'))
                if t=='file':
                    browse.clicked.connect(lambda _,f=field:self._pick_file(f))
                elif t=='color':
                    browse.clicked.connect(lambda _,f=field:self._pick_parameter_color(f))
                else:
                    browse.clicked.connect(lambda _,f=field:self._pick_folder(f))
                h.addWidget(field,1)
                h.addWidget(browse)
                if t=='color':
                    def _swatch(text,b=browse):
                        from PySide6.QtGui import QColor
                        c=QColor(text)
                        b.setStyleSheet(f"background-color:{c.name()};color:{'#000' if c.lightness()>140 else '#fff'};border:1px solid #666;padding:3px 8px;" if c.isValid() else '')
                    field.textChanged.connect(_swatch);_swatch(field.text())
                widget=field
                self.form.addRow(ui_label(desc.get('label',name)),container)
            else:
                widget=QLineEdit(str(default))
            self.widgets[name]=widget
            widget.setAccessibleName(ui_label(desc.get('label',name)))
            if name=='masks_json' and mod.interaction=='histogram_masks':
                continue
            if isinstance(widget,QComboBox):widget.currentTextChanged.connect(self.changed)
            elif isinstance(widget,QCheckBox):widget.toggled.connect(self.changed)
            elif isinstance(widget,(QSpinBox,QDoubleSpinBox)):widget.valueChanged.connect(self.changed)
            elif isinstance(widget,QLineEdit):widget.textChanged.connect(self.changed)
            if t not in ('file','folder','color') and not (mod.id=='channel_overlay' and name.startswith('opacity_')):
                self.form.addRow(ui_label(desc.get('label',name)),widget)
            if desc.get('description'):
                widget.setToolTip(str(desc['description']))
        missing=mod.missing_dependencies()
        disabled=mod.status not in ('operational','experimental')
        if disabled:
            self.status.setText(f'Unavailable: {ui_label(mod.status).lower()}. See the module documentation.')
        elif missing:
            self.status.setText('Missing optional package(s): '+', '.join(missing)+'\nInstall into the same venv: pip install '+' '.join(missing))
        else:
            self.status.setText('Experimental · validation required' if mod.status=='experimental' else 'Ready')
        self.run_button.setEnabled(not missing and not disabled)

    def show_runs(self,runs,selected=None,text=None):
        self.run_selection.blockSignals(True)
        self.run_selection.clear()
        for r in runs:
            label=('★ ' if r.get('preferred') else '')+r['created_at'][:19].replace('T',' ')+ ' · '+ui_label(r['status'])
            self.run_selection.addItem(label,r['result_id'])
        if selected:
            index=self.run_selection.findData(selected)
            if index>=0:self.run_selection.setCurrentIndex(index)
        self.run_selection.blockSignals(False)
        self.result_text.setPlainText(text or 'No saved analysis for this scan/tool.')
        self.comment_entry.clear()
        enabled=bool(runs)
        self.save_comment.setEnabled(enabled)
        self.prefer_run.setEnabled(enabled)

    def restore_values(self,values):
        # Silent restoration avoids false recalculation and preview cascades.
        for key,val in values.items():
            widget=self.widgets.get(key)
            if widget is None:continue
            widget.blockSignals(True)
            if isinstance(widget,QComboBox):set_combo_key(widget,str(val))
            elif isinstance(widget,QCheckBox):widget.setChecked(bool(val))
            elif isinstance(widget,(QSpinBox,QDoubleSpinBox)):widget.setValue(val)
            elif isinstance(widget,QLineEdit):widget.setText(str(val))
            widget.blockSignals(False)

    def set_channel_title(self,text):
        self.colorbar_title.blockSignals(True)
        self.colorbar_title.setText(str(text or ''))
        self.colorbar_title.blockSignals(False)

    @staticmethod
    def _pick_parameter_color(field):
        from PySide6.QtGui import QColor
        picked=QColorDialog.getColor(QColor(field.text()),None,'Choose vector/legend color')
        if picked.isValid():field.setText(picked.name())

    def _pick_molecule_artwork(self):
        current=Path(self.molecule_file_path.text()).expanduser()
        initial=str(current if current.is_file() else current.parent if current.parent.is_dir() else Path.home())
        chosen,_=QFileDialog.getOpenFileName(
            self,'Load molecule SVG or PNG',initial,
            'Molecule artwork (*.svg *.png *.webp *.jpg *.jpeg);;SVG vector images (*.svg);;PNG images (*.png);;All files (*)')
        if chosen:
            self.molecule_file_path.setText(chosen)

    def _update_molecule_artwork(self, value):
        """Immediate feedback proves artwork was selected, even before FFT exists."""
        path=Path(str(value).strip()).expanduser()
        self.molecule_artwork_thumbnail.clear()
        if not str(value).strip():
            self.molecule_artwork_status.setText('No molecule file selected. Click Load molecule SVG / PNG…')
            self.molecule_artwork_thumbnail.setText('Artwork preview')
            return
        if not path.is_file():
            self.molecule_artwork_status.setText('File not found: '+str(path))
            self.molecule_artwork_thumbnail.setText('Check the file path')
            return
        if path.suffix.lower() not in ('.svg','.png','.webp','.jpg','.jpeg'):
            self.molecule_artwork_status.setText('Unsupported image: please choose SVG or PNG')
            self.molecule_artwork_thumbnail.setText('Choose an image file')
            return
        try:
            if path.suffix.lower()=='.svg':
                from PySide6.QtSvg import QSvgRenderer
                renderer=QSvgRenderer(str(path))
                if not renderer.isValid():raise ValueError('Invalid SVG contents')
                size=renderer.defaultSize()
                w=max(1,size.width());h=max(1,size.height())
                scale=min(225/w,135/h)
                width=max(1,round(w*scale));height=max(1,round(h*scale))
                canvas=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
                canvas.fill(Qt.GlobalColor.transparent)
                painter=QPainter(canvas)
                try:renderer.render(painter,QRectF(0,0,width,height))
                finally:painter.end()
                pixmap=QPixmap.fromImage(canvas)
            else:
                pixmap=QPixmap(str(path))
                if pixmap.isNull():raise ValueError('Image cannot be decoded')
            self.molecule_artwork_thumbnail.setPixmap(pixmap.scaled(
                240,140,Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            self.molecule_artwork_status.setText('✓ Loaded: '+path.name+' — set physical width / height (nm) and angle below')
        except (OSError,RuntimeError,ValueError,ImportError) as exc:
            self.molecule_artwork_status.setText('Could not preview '+path.name+': '+str(exc))
            self.molecule_artwork_thumbnail.setText('The file may still work with CairoSVG')

    @staticmethod
    def _pick_file(field):
        chosen,_=QFileDialog.getOpenFileName(None,'Select file',field.text())
        if chosen:field.setText(chosen)

    @staticmethod
    def _pick_folder(field):
        chosen=QFileDialog.getExistingDirectory(None,'Select directory',field.text())
        if chosen:field.setText(chosen)

    def set_selections(self, rois, selected=-1):
        self.selection_list.blockSignals(True)
        self.selection_list.clear()
        for i,roi in enumerate(rois):
            coordinates=', '.join('('+', '.join(f'{n:.1f}' for n in p)+')' for p in roi.points_px)
            self.selection_list.addItem(f'{i+1}. {roi.kind}: {coordinates}')
        if rois:
            self.selection_list.setCurrentRow(selected if 0<=selected<len(rois) else len(rois)-1)
        self.selection_list.blockSignals(False)
        self.delete_selection.setEnabled(bool(rois))
        self.undo_line.setEnabled(bool(rois))
        self.clear_lines.setEnabled(bool(rois))

    def _gif_options(self):
        return {'duration_s':self.gif_duration.value(),
            'fps':self.gif_fps.value(),'max_px':int(self.gif_size.currentData()),
            'hold_fraction':self.gif_hold.value()/100.,'scale_bar':self.gif_scalebar.isChecked(),
            'labels':self.gif_labels.isChecked(),'ease':self.gif_ease.isChecked(),
            'also_mp4':self.gif_mp4.isChecked(),
            'start_opacity':self.gif_alpha0.value()/100.,'end_opacity':self.gif_alpha1.value()/100.}

    def _request_gif(self):
        self.gifExportRequested.emit(self._gif_options())

    def schedule_gif_estimate(self,*_):
        """Recompute the GIF file size shortly after the last change (only while the GIF box is shown)."""
        timer=getattr(self,'_gif_estimate_timer',None)
        if timer is not None and self.module is not None and self.module.id=='channel_overlay':
            timer.start()

    def set_gif_estimate(self,text):
        try:self.gif_size_estimate.setText(str(text or ''))
        except RuntimeError:pass

    def values(self):
        result={}
        for k,w in self.widgets.items():
            if isinstance(w,QComboBox): v=combo_key(w)
            elif isinstance(w,QCheckBox): v=w.isChecked()
            elif isinstance(w,(QSpinBox,QDoubleSpinBox)): v=w.value()
            else:v=w.text()
            result[k]=v
        if self.module and self.module.interaction=='histogram_masks':
            result['masks_json']=json.dumps(self.masks)
        return result

    def _remember_masks(self):
        snapshot=json.dumps(self.masks,sort_keys=True)
        if not self.mask_history or self.mask_history[-1]!=snapshot:
            self.mask_history.append(snapshot)
            self.mask_history=self.mask_history[-35:]

    def _undo_mask(self):
        if self.mask_history:
            old=json.loads(self.mask_history.pop())
            self.set_masks(old)

    def _reset_mask(self):
        row=self.mask_list.currentRow()
        if row<0:return
        self._remember_masks()
        self.masks[row]['low']=float(self.preview.low)
        self.masks[row]['high']=float(self.preview.high)
        self._refresh_masks()

    def set_masks(self,masks):
        self.masks=[dict(m) for m in masks]
        self._refresh_masks()

    def _refresh_masks(self):
        selected=self.mask_list.currentRow()
        self.mask_list.blockSignals(True)
        self.mask_list.clear()
        for mask in self.masks:
            self.mask_list.addItem(f'{mask["name"]}  [{mask["low"]:.4g}, {mask["high"]:.4g}]')
        row=min(max(0,selected),len(self.masks)-1)
        self.mask_list.setCurrentRow(row)
        self.mask_list.blockSignals(False)
        self._choose_mask(row)

    def _choose_mask(self,index):
        self._updating_mask=True
        if 0<=index<len(self.masks):
            mask=self.masks[index]
            self.mask_name.setText(mask['name'])
            self.mask_min.setText(f'{mask["low"]:.12g}')
            self.mask_max.setText(f'{mask["high"]:.12g}')
            self.mask_gauss.setValue(int(mask.get('populations',2)))
            self.mask_peaks.setText(', '.join(f'{float(n):.12g}' for n in mask.get('peaks',[])))
        else:
            self.mask_name.clear();self.mask_min.clear();self.mask_max.clear();self.mask_peaks.clear()
        self._updating_mask=False
        self.masksChanged.emit()

    def _new_mask(self):
        lo,hi=self.preview.low,self.preview.high
        if not self.preview.series:lo,hi=0.,1.
        if len(self.masks)>=16:return
        self._remember_masks()
        self.masks.append({'name':f'Mask {len(self.masks)+1}','low':lo,'high':hi,
                           'populations':int(self.widgets['populations'].value()) if 'populations' in self.widgets else 2,
                           'peaks':[],
                           'color':['#f0bb6e','#7ad7a6','#cb9af1','#6bb7e8','#ef8282'][len(self.masks)%5]})
        self._refresh_masks()
        self.mask_list.setCurrentRow(len(self.masks)-1)

    def _remove_mask(self):
        index=self.mask_list.currentRow()
        if 0<=index<len(self.masks):
            self._remember_masks()
            self.masks.pop(index)
            self._refresh_masks()

    def _preview_mask_fields(self,*args):
        if self._updating_mask:return
        index=self.mask_list.currentRow()
        if not 0<=index<len(self.masks):return
        try:
            import math
            low,high=float(self.mask_min.text()),float(self.mask_max.text())
            if not (math.isfinite(low) and math.isfinite(high) and low<high):return
        except ValueError:return
        mask=self.masks[index]
        if (mask['low'],mask['high'])!=(low,high):
            self._remember_masks()
            mask['low'],mask['high']=low,high
            self.masksChanged.emit()

    def _save_mask_fields(self):
        if self._updating_mask:return
        index=self.mask_list.currentRow()
        if not 0<=index<len(self.masks):return
        try:
            lo,hi=float(self.mask_min.text()),float(self.mask_max.text())
            if not (lo<=hi and all(map(__import__('math').isfinite,(lo,hi)))):
                raise ValueError('Mask limits must be finite and ordered')
            name=self.mask_name.text().strip()
            if not name:raise ValueError('Mask needs a name')
            mask=self.masks[index]
            peaks=[float(v.strip()) for v in self.mask_peaks.text().split(',') if v.strip()]
            import math
            if len(peaks)>self.mask_gauss.value() or any(not math.isfinite(v) for v in peaks):
                raise ValueError('Initial peak count exceeds number of Gaussians or is non-finite')
            if (mask.get('peaks',[])!=peaks):self._remember_masks()
            if (mask['name'],mask['low'],mask['high'],mask['populations'])!=(name,lo,hi,self.mask_gauss.value()):
                self._remember_masks()
            mask.update(name=name,low=lo,high=hi,populations=self.mask_gauss.value(),peaks=peaks)
            self._refresh_masks()
        except ValueError:
            self._choose_mask(index)

    def _preview_range(self,lo,hi):
        # Do not modify saved mask fields until release.
        self.masksChanged.emit()

    def _range_dragged(self,lo,hi):
        row=self.mask_list.currentRow()
        if row<0:return
        self._remember_masks()
        self.masks[row]['low']=float(lo)
        self.masks[row]['high']=float(hi)
        self._refresh_masks()

    def _pick_color(self):
        row=self.mask_list.currentRow()
        if row<0:return
        from PySide6.QtGui import QColor
        color=QColorDialog.getColor(QColor(self.masks[row]['color']),self)
        if color.isValid():
            self._remember_masks()
            self.masks[row]['color']=color.name()
            self.masksChanged.emit()

    def _save_masks(self):
        path,_=QFileDialog.getSaveFileName(self,'Save named masks','','JSON (*.json)')
        if path:
            from pathlib import Path
            Path(path).write_text(json.dumps(self.masks,indent=2)+'\n',encoding='utf8')

    def _load_masks(self):
        path,_=QFileDialog.getOpenFileName(self,'Load named masks','','JSON (*.json)')
        if path:
            from pathlib import Path
            try:
                masks=json.loads(Path(path).read_text(encoding='utf8'))
                if not isinstance(masks,list) or len(masks)>16:raise ValueError('Expected up to 16 masks')
                valid=[]
                import math
                for i,m in enumerate(masks):
                    lo,hi=float(m['low']),float(m['high'])
                    if not (math.isfinite(lo) and math.isfinite(hi) and hi>lo):
                        raise ValueError(f'Mask {i+1} has invalid limits')
                    valid.append({'name':str(m.get('name',f'Mask {i+1}'))[:100],
                                  'low':lo,'high':hi,'color':str(m.get('color','#efbb64')),
                                  'populations':int(m.get('populations',2)),
                                  'peaks':[float(v) for v in m.get('peaks',[])]})
                self._remember_masks()
                self.set_masks(valid)
            except (OSError,ValueError,TypeError,KeyError) as exc:
                from spm_studio.shared.dialogs import MessageDialog as QMessageBox
                QMessageBox.warning(self,'Invalid masks',str(exc))
