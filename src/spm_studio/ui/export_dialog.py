"""Choose publication panels, including script-generated lattice PDF results.

v0.0.5 — *Custom* is fully customisable: 1 to 12 images in a row, a triangle or a grid with a
chosen number of columns; every image can be a channel of the open scan, a channel of another
listed scan, or an analysis result / plot, with its own title, unit, colourbar and scale bar.
**Save as export profile…** stores the whole figure under a name; it is in the figure list at
once (no restart) and can be exported to a colleague from Settings › Library.
"""
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QGroupBox,QComboBox,
    QLineEdit,QLabel,QDialogButtonBox,QFormLayout,QCheckBox,QHBoxLayout,QPushButton,QDoubleSpinBox,QSpinBox,
    QButtonGroup,QWidget,QGridLayout,QScrollArea,QFrame,QApplication)
from ..core.export_layout import panel_defaults, grid_shape, MAX_PANELS
from .color_field import ColorField

BUILTIN_MODES=('single_column','double_column','triple','square')
COUNT_LABELS={1:'One image',2:'Two images',3:'Three images'}


class PublicationDialog(QDialog):
    profileSaved=Signal(str)

    def __init__(self, scan, report_files=(), *, two_columns=False, selected_channel='',
                 selected_trace='forward', channel_titles=None, preset=None, layout_name=None, parent=None,
                 transparent=False, arrangement='triangle', formats=('svg',), other_scans=(), scan_loader=None,
                 save_folder=None):
        super().__init__(parent)
        self.setWindowTitle('Export figure')
        self.setMinimumWidth(980)
        self.scan=scan
        self.preset=dict(preset or {})
        self.preset_name=str(layout_name or self.preset.get('name','single_column'))
        self.selected_trace=selected_trace
        self.selected_channel=selected_channel
        self.channel_titles=channel_titles or {}
        # Other scans of the current list: [(label, path)], opened only when one is chosen.
        self.other_scans=[(str(label),str(path)) for label,path in other_scans
                          if str(Path(path))!=str(Path(scan.path))]
        self._scan_loader=scan_loader
        self._loaded_scans={}
        self.save_folder=Path(save_folder) if save_folder else None
        self.choices=[({'kind':'channel','channel':name},f'Scan channel · {name}') for name in scan.channels]
        # High-quality lossless PNG results must be exportable just like PDFs.
        supported={'.svg','.png','.jpg','.jpeg','.pdf'}
        # One entry per figure: the SVG master wins over PDF / PNG siblings.
        rank={'.svg':0,'.pdf':1,'.png':2,'.jpg':3,'.jpeg':3}
        best={}
        for f in dict.fromkeys(map(str,report_files)):
            path=Path(f)
            if not path.is_file() or path.suffix.lower() not in supported:continue
            key=(str(path.parent),path.stem)
            if key not in best or rank[path.suffix.lower()]<rank[best[key].suffix.lower()]:best[key]=path
        self.choices.extend(({'kind':'report','path':str(f)},'Result · '+f.name) for f in best.values())
        root=QVBoxLayout(self)
        root.setSpacing(10)
        layout_box=QGroupBox('Page')
        layout_form=QFormLayout(layout_box)
        self.layout_mode=QComboBox()
        for label,key in [('Single column','single_column'),
                          ('Double column','double_column'),
                          ('Triple','triple'),
                          ('Square','square'),('Custom','custom')]:
            self.layout_mode.addItem(label,key)
        self.layout_mode.setCurrentIndex(max(0,self.layout_mode.findData(
            self.preset_name if self.preset_name in BUILTIN_MODES else 'custom')))
        layout_form.addRow('Format',self.layout_mode)
        size_row=QHBoxLayout()
        self.page_width=QDoubleSpinBox();self.page_height=QDoubleSpinBox()
        for box,value in ((self.page_width,self.preset.get('width_mm',86)),
                          (self.page_height,self.preset.get('height_mm',78))):
            box.setRange(15,1000);box.setDecimals(1);box.setSingleStep(5)
            box.setValue(float(value));box.setSuffix(' mm');size_row.addWidget(box)
        layout_form.addRow('Width × height',size_row)
        self.page_dpi=QSpinBox();self.page_dpi.setRange(150,2400)
        self.page_dpi.setSingleStep(150)
        # v32: maximum quality by default (old presets saved at 300/600 DPI are raised).
        self.page_dpi.setValue(max(1200,int(self.preset.get('dpi',1200))))
        self.page_dpi.setSuffix(' DPI');layout_form.addRow('Resolution',self.page_dpi)
        self.panel_count=QComboBox()
        for n in range(1,MAX_PANELS+1):
            self.panel_count.addItem(COUNT_LABELS.get(n,f'{n} images'),n)
        self.panel_count.setToolTip(f'Custom: 1 to {MAX_PANELS} images (channels, other scans, results and plots)')
        layout_form.addRow('Images',self.panel_count)
        # v30: arrangement of three images — row, triangle ▲ or reverse triangle ▼; v0.0.5: grid.
        self.arrangement_row=QWidget();arr=QHBoxLayout(self.arrangement_row);arr.setContentsMargins(0,0,0,0)
        self.arrangement_group=QButtonGroup(self);self.arrangement_group.setExclusive(True)
        self.arrangement_buttons={}
        for key,label,tip in (('row','▭ ▭ ▭  Row','Images side by side'),
                              ('triangle','▲  Triangle','One image centred on top, two below'),
                              ('inverted_triangle','▼  Reverse triangle','Two images on top, one centred below'),
                              ('grid','▦  Grid','Rows of images; choose the number of columns')):
            b=QPushButton(label);b.setCheckable(True);b.setToolTip(tip)
            b.setObjectName('TripleArrangement_'+key)
            self.arrangement_group.addButton(b);arr.addWidget(b);self.arrangement_buttons[key]=b
        self.grid_columns=QSpinBox()
        self.grid_columns.setObjectName('ExportGridColumnsV005')
        self.grid_columns.setRange(0,MAX_PANELS)
        self.grid_columns.setSpecialValueText('auto')
        self.grid_columns.setPrefix('columns: ')
        self.grid_columns.setToolTip('Images per row (auto = near-square grid). An incomplete last row is centred.')
        self.grid_columns.valueChanged.connect(lambda *_:self._arrangement_changed())
        arr.addWidget(self.grid_columns)
        arr.addStretch(1)
        self.arrangement_buttons.get(arrangement,self.arrangement_buttons['triangle']).setChecked(True)
        self.arrangement_group.buttonClicked.connect(lambda *_:self._arrangement_changed())
        layout_form.addRow('Arrangement',self.arrangement_row)
        self.panel_letters=QCheckBox('Panel letters a, b, c')
        self.panel_letters.setChecked(False)   # v34: off by default
        layout_form.addRow('',self.panel_letters)
        root.addWidget(layout_box)
        self.double=QCheckBox('Two independent images')
        self.double.setVisible(False) # API compatibility
        self.transparent=QCheckBox('Transparent background')
        self.transparent.setObjectName('TransparentExportBackgroundV26')
        self.transparent.setToolTip('Leave the page unpainted so the figure can be placed on any slide or poster background. JPEG has no transparency and stays white.')
        self.transparent.setChecked(bool(transparent))
        root.addWidget(self.transparent)
        # v33: choose one, two or all three output formats; all are written in one go.
        fmt_row=QHBoxLayout();fmt_row.addWidget(QLabel('Formats'))
        self.format_boxes={}
        for key,label in (('svg','SVG'),('pdf','PDF'),('png','PNG')):
            box=QCheckBox(label);box.setObjectName('ExportFormatV33_'+key)
            box.setChecked(key in formats)
            box.toggled.connect(self._formats_changed)
            self.format_boxes[key]=box;fmt_row.addWidget(box)
        fmt_row.addStretch(1)
        root.addLayout(fmt_row)
        # Image panels live in a scrolling grid that mirrors the chosen arrangement.
        self.controls=[]
        self.panel_scroll=QScrollArea()
        self.panel_scroll.setObjectName('ExportPanelsScrollV005')
        self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.panel_host=QWidget()
        self.panel_grid=QGridLayout(self.panel_host)
        self.panel_grid.setContentsMargins(0,0,0,0)
        self.panel_grid.setSpacing(8)
        self.panel_scroll.setWidget(self.panel_host)
        self.panel_scroll.setMinimumHeight(330)
        root.addWidget(self.panel_scroll,1)
        self._ensure_controls(3)
        self.layout_mode.currentIndexChanged.connect(self._layout_changed)
        self.panel_count.currentIndexChanged.connect(self._layout_changed)
        self._layout_changed()
        for control in self.controls: control['trace'].setCurrentIndex(max(0,control['trace'].findData(selected_trace)))
        bottom=QHBoxLayout()
        self.save_profile_button=QPushButton('Save as export profile…')
        self.save_profile_button.setObjectName('SaveExportProfileV005')
        self.save_profile_button.setToolTip('Store this page, the arrangement and every image setting under a name. '
                                            'It appears in the figure list at once and can be reused on any scan.')
        self.save_profile_button.clicked.connect(self.save_as_profile)
        try:
            from spm_studio.shared.appearance import set_icon
            set_icon(self.save_profile_button,'save')
        except Exception:
            pass
        bottom.addWidget(self.save_profile_button)
        self.profile_status=QLabel('');self.profile_status.setObjectName('hint')
        bottom.addWidget(self.profile_status,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Export…')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty('primary',True)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        root.addLayout(bottom)
        self._ok_button=buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._formats_changed()
        saved=self.preset.get('layout')
        if isinstance(saved,dict):
            try:self.apply_layout(saved)
            except Exception as exc:    # a hand-edited profile must never block exporting
                self.profile_status.setText(f'Saved figure not applied: {exc}')

    # ---- panels
    def _panel_scan(self,index):
        """Scan object a panel reads (the open scan, or another listed scan loaded on demand)."""
        path=self.controls[index]['scan'].currentData() if index<len(self.controls) else ''
        if not path:return self.scan
        if path not in self._loaded_scans:
            if self._scan_loader is None:
                from ..core.io import read_scan
                loader=read_scan
            else:
                loader=self._scan_loader
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:self._loaded_scans[path]=loader(path)
            finally:QApplication.restoreOverrideCursor()
        return self._loaded_scans[path]

    def _fill_images(self,index):
        """List what the panel can show for its scan; keep the same channel when possible."""
        fields=self.controls[index]
        image=fields['image']
        previous=image.currentData()
        try:
            scan=self._panel_scan(index)
        except Exception as exc:
            self.profile_status.setText(f'Could not open that scan: {exc}')
            fields['scan'].blockSignals(True);fields['scan'].setCurrentIndex(0);fields['scan'].blockSignals(False)
            scan=self.scan
        image.blockSignals(True)
        image.clear()
        if scan is self.scan:
            for key,label in self.choices:image.addItem(label,key)
        else:
            for name in scan.channels:image.addItem(f'Scan channel · {name}',{'kind':'channel','channel':name})
        wanted=(previous or {}).get('channel') if isinstance(previous,dict) else None
        chosen=0
        if wanted:
            chosen=next((i for i in range(image.count()) if (image.itemData(i) or {}).get('channel')==wanted),0)
        image.setCurrentIndex(chosen)
        image.blockSignals(False)
        source=fields['colorbar_source']
        source.blockSignals(True);source.clear();source.addItem('None','')
        for channel in scan.channels:source.addItem(f'Scan data · {channel}',channel)
        source.blockSignals(False)
        self._set_defaults(index)

    def _make_panel(self,index):
        scan=self.scan
        group=QGroupBox(f'Image {index+1}'); form=QFormLayout(group)
        scan_choice=QComboBox()
        scan_choice.setObjectName(f'ExportPanelScanV005_{index}')
        scan_choice.addItem(f'This scan · {Path(scan.path).name}','')
        for label,path in self.other_scans:scan_choice.addItem(label,path)
        scan_choice.setToolTip('The open scan, or another scan of the Files list (same figure, different scans)')
        image=QComboBox(); trace=QComboBox(); title=QLineEdit(); unit=QLineEdit(); legend=QComboBox(); scalebar_color=ColorField('#111111','Scale bar colour'); scalebar_position=QComboBox()
        show_scalebar=QCheckBox('Show scale bar');show_scalebar.setChecked(True)
        show_colorbar=QCheckBox('Show colourbar');show_colorbar.setToolTip('Show quantitative colourbar')
        source=QComboBox()
        source.addItem('None','')
        for channel in scan.channels:
            source.addItem(f'Scan data · {channel}',channel)
        for key,label in self.choices: image.addItem(label,key)
        trace.addItem('Forward','forward'); trace.addItem('Backward','backward')
        for label,value in [('Below','below'),('Right','right'),('Left','left'),('Hide','none')]: legend.addItem(label,value)
        for label,value in [('Bottom right','bottom_right'),('Bottom left','bottom_left'),('Top right','top_right'),('Top left','top_left')]: scalebar_position.addItem(label,value)
        if self.other_scans:form.addRow('Scan',scan_choice)
        else:scan_choice.setParent(group);scan_choice.hide()
        form.addRow('Image',image);form.addRow('Trace',trace)
        form.addRow('',show_colorbar);form.addRow('Position',legend)
        form.addRow('Colourbar data',source)
        form.addRow('Title',title)
        title.setPlaceholderText('LaTeX allowed, e.g. $\\Delta f$')
        unit_row=QHBoxLayout(); unit_row.addWidget(unit,1)
        unit_buttons=[]
        for label,value,tip in (('auto','','Automatic SI scale (nm / pm, mV, nA...)'),('nm','nm','Show the colourbar in nanometres'),
                                ('Å','Å','Show the colourbar in ångström (topography)'),('pm','pm','Show the colourbar in picometres')):
            button=QPushButton(label); button.setToolTip(tip); button.setFixedWidth(44)
            button.setObjectName('UnitQuick'+('Auto' if not value else value))
            button.clicked.connect(lambda _=False,field=unit,v=value:field.setText(v))
            unit_row.addWidget(button); unit_buttons.append((button,value))
        form.addRow('Unit',unit_row)
        unit.setToolTip('Shown inside [ ]; empty = automatic SI prefix')
        form.addRow('',show_scalebar)
        form.addRow('Bar colour',scalebar_color);form.addRow('Bar corner',scalebar_position)
        show_scalebar.toggled.connect(scalebar_color.setEnabled);show_scalebar.toggled.connect(scalebar_position.setEnabled)
        data={'group':group,'scan':scan_choice,'image':image,'trace':trace,'title':title,'unit':unit,'legend':legend,'scalebar_color':scalebar_color,'scalebar_position':scalebar_position,'show_scalebar':show_scalebar,
              'show_colorbar':show_colorbar,'colorbar_source':source,'unit_buttons':unit_buttons}
        show_colorbar.toggled.connect(lambda checked,n=index:self._bar_changed(n))
        source.currentIndexChanged.connect(lambda _,n=index:self._bar_changed(n))
        self.controls.append(data)
        image.currentIndexChanged.connect(lambda _,n=index:self._set_defaults(n))
        scan_choice.currentIndexChanged.connect(lambda _,n=index:self._fill_images(n))
        if index==0:
            current=next((i for i,(v,_) in enumerate(self.choices) if v.get('channel')==self.selected_channel),0); image.setCurrentIndex(current)
        elif len(self.choices)>1:
            used={c['image'].currentIndex() for c in self.controls[:-1]}
            image.setCurrentIndex(next((i for i,(v,_) in enumerate(self.choices)
                                        if i not in used and v['kind']=='channel'),
                                       min(index,len(self.choices)-1)))
        trace.setCurrentIndex(max(0,trace.findData(self.selected_trace)))
        self._set_defaults(index)
        group.setVisible(False)
        return data

    def _ensure_controls(self,count):
        """Create image panels on demand (three exist from the start; up to MAX_PANELS)."""
        while len(self.controls)<min(int(count),MAX_PANELS):
            self._make_panel(len(self.controls))

    def _reflow(self):
        """Place the visible panels like the exported figure (row, triangle or grid)."""
        n=self._n_panels()
        arrangement=self.arrangement()
        while self.panel_grid.count():
            self.panel_grid.takeAt(0)
        if arrangement in ('triangle','inverted_triangle') and n==3:
            # Two columns each spanning two grid cells, so the single image can be centred.
            spots=({'triangle':((0,1),(1,0),(1,2)),'inverted_triangle':((0,0),(0,2),(1,1))})[arrangement]
            for control,(r,c) in zip(self.controls[:3],spots):
                self.panel_grid.addWidget(control['group'],r,c,1,2)
            columns=4
        else:
            columns=n if arrangement=='row' else grid_shape(n,self.columns())[0]
            for i,control in enumerate(self.controls[:n]):
                self.panel_grid.addWidget(control['group'],i//columns,i%columns)
        for c in range(max(columns,MAX_PANELS)+1):
            self.panel_grid.setColumnStretch(c,1 if c<columns else 0)
        for i,control in enumerate(self.controls):
            control['group'].setVisible(i<n)

    def formats(self):
        return [key for key,box in self.format_boxes.items() if box.isChecked()]

    def _formats_changed(self,*_):
        ok=getattr(self,'_ok_button',None)
        if ok is not None:
            ok.setEnabled(bool(self.formats()))
            ok.setToolTip('' if self.formats() else 'Tick at least one format')

    def _layout_changed(self,*_):
        mode=self.layout_mode.currentData()
        forced={'single_column':(86.,78.,1),'double_column':(178.,115.,2),
                'triple':(178.,self._triple_height(),3),'square':(100.,100.,1)}
        if mode in forced:
            w,h,n=forced[mode]
            if mode==self.preset_name:
                w=float(self.preset.get('width_mm',w))
                h=float(self.preset.get('height_mm',h))
            self.page_width.setValue(w);self.page_height.setValue(h)
            self.panel_count.setCurrentIndex(n-1)
        custom=mode=='custom'
        self.page_width.setEnabled(custom);self.page_height.setEnabled(custom)
        self.panel_count.setEnabled(custom)
        n=self._n_panels()
        self._ensure_controls(max(3,n))
        self.double.setChecked(n>=2)
        # Arrangement choices that exist for this number of images.
        allowed={'row':2<=n<=3,'triangle':n==3,'inverted_triangle':n==3,'grid':custom and n>=2}
        for key,button in self.arrangement_buttons.items():
            button.setVisible(allowed[key])
        current=next((k for k,b in self.arrangement_buttons.items() if b.isChecked()),'row')
        if not allowed.get(current,False):
            fallback='grid' if allowed['grid'] and n>3 else ('row' if allowed['row'] else None)
            if fallback:self.arrangement_buttons[fallback].setChecked(True)
        self.arrangement_row.setVisible(n==3 or (custom and n>=2))
        self.grid_columns.setVisible(custom and n>=2)
        self.grid_columns.setEnabled(self.arrangement()=='grid')
        self.panel_letters.setVisible(n>=2)
        self._reflow()
        self._update_titles()

    def _n_panels(self):
        mode=self.layout_mode.currentData()
        if mode=='double_column':return 2
        if mode=='triple':return 3
        if mode=='custom':return int(self.panel_count.currentData() or 1)
        return 1

    def arrangement(self)->str:
        n=self._n_panels()
        chosen=next((key for key,button in self.arrangement_buttons.items() if button.isChecked()),'row')
        if n<=1:return 'row'
        if chosen in ('triangle','inverted_triangle') and n!=3:chosen='grid' if n>3 else 'row'
        if chosen=='row' and n>3:chosen='grid'
        if chosen=='grid' and self.layout_mode.currentData()!='custom':chosen='row'
        return chosen

    def columns(self)->int:
        """Images per row of a grid (0 = automatic)."""
        return int(self.grid_columns.value()) if self.arrangement()=='grid' else 0

    def _triple_height(self):
        return 72. if self.arrangement()=='row' else 168.

    def _arrangement_changed(self):
        if self.layout_mode.currentData()=='triple':
            self.page_height.setValue(self._triple_height())
        self.grid_columns.setEnabled(self.arrangement()=='grid')
        self._reflow()
        self._update_titles()

    def _update_titles(self):
        n=self._n_panels()
        arrangement=self.arrangement()
        if n==1:titles=['Image']
        elif n==2 and arrangement=='row':titles=['Left','Right']
        elif n==3 and arrangement in ('row','triangle','inverted_triangle'):
            titles=list({'row':('a · Left','b · Middle','c · Right'),
                         'triangle':('a · Top','b · Bottom left','c · Bottom right'),
                         'inverted_triangle':('a · Top left','b · Top right','c · Bottom')}[arrangement])
        else:
            columns=grid_shape(n,self.columns())[0]
            titles=[f'{chr(ord("a")+i)} · row {i//columns+1}, column {i%columns+1}' for i in range(n)]
        for control,title in zip(self.controls,titles):
            if title:control['group'].setTitle(title)

    def letters_enabled(self)->bool:
        return self._n_panels()>1 and self.panel_letters.isChecked()

    def resolved_preset(self):
        from ..core.presets import validate_export
        return validate_export({**{k:v for k,v in self.preset.items() if k!='layout'},'schema_version':1,
            'name':self.layout_mode.currentData(),
            'width_mm':self.page_width.value(),'height_mm':self.page_height.value(),
            'dpi':self.page_dpi.value()})

    def _set_defaults(self,index):
        fields=self.controls[index]
        choice=fields['image'].currentData()
        if not choice:return
        scan=self._panel_scan(index)
        defaults=panel_defaults(scan,choice,self.selected_trace)
        own=scan is self.scan
        fields['title'].setText(self.channel_titles.get(defaults.get('channel'),defaults['title']) if own else defaults['title'])
        # Empty = automatic SI prefix from the data range (nm, pm, mV...). The numbers follow
        # whatever unit is typed here (nm, Å, mV) when it matches the channel's base unit.
        fields['unit'].setText('')
        fields['unit'].setPlaceholderText(f"auto ({defaults['unit']})" if defaults['unit'] else 'auto')
        length_based=str(defaults.get('unit','')).strip()=='m'
        for button,value in fields.get('unit_buttons',()):
            button.setEnabled(not value or length_based)
        is_channel=defaults['kind']=='channel'
        is_result=defaults['kind']=='report'
        fields['trace'].setEnabled(is_channel)
        fields['show_colorbar'].setChecked(not is_result)
        fields['colorbar_source'].setVisible(is_result)
        fields['legend'].setCurrentIndex(max(0,fields['legend'].findData(defaults['colorbar_position'])))
        self._bar_changed(index)
        fields['scalebar_color'].setText(defaults.get('scale_bar_color','#111111'))
        target=fields['scalebar_position']
        target.setCurrentIndex(max(0,target.findData(defaults.get('scale_bar_position','bottom_right'))))

    def _bar_changed(self,index):
        fields=self.controls[index]
        choice=fields['image'].currentData()
        source=fields['colorbar_source'].currentData()
        valid=(choice is not None and
               (choice.get('kind')!='report' or bool(source)))
        fields['show_colorbar'].setEnabled(valid)
        if not valid:fields['show_colorbar'].setChecked(False)
        fields['legend'].setEnabled(valid and fields['show_colorbar'].isChecked())

    def transparent_background(self)->bool:
        return self.transparent.isChecked()

    def selection(self):
        result=[]
        for index,fields in enumerate(self.controls[:self._n_panels()]):
            scan=self._panel_scan(index)
            choice=fields['image'].currentData()
            if not choice:continue
            spec=panel_defaults(scan,choice,fields['trace'].currentData())
            if spec['kind']=='channel':
                traces=scan.channels[spec['channel']].traces
                wanted=fields['trace'].currentData()
                spec['trace']=wanted if (scan is self.scan or wanted in traces) else next(iter(traces))
            else:
                spec['trace']=fields['trace'].currentData()
            if scan is not self.scan:spec['scan_path']=str(scan.path)
            spec['title']=fields['title'].text().strip() or spec['title']
            spec['unit']=fields['unit'].text().strip()
            spec['colorbar_position']=(fields['legend'].currentData()
                                        if fields['show_colorbar'].isChecked() else 'none')
            spec['show_colorbar']=fields['show_colorbar'].isChecked()
            if spec['kind']=='report' and spec['show_colorbar']:
                spec['colorbar_source']=fields['colorbar_source'].currentData()
            spec['scale_bar_color']=fields['scalebar_color'].text().strip() or '#111111'
            spec['scale_bar_position']=fields['scalebar_position'].currentData()
            spec['show_scale_bar']=fields['show_scalebar'].isChecked()
            result.append(spec)
        return result

    # ---- v0.0.5: export profiles (the whole figure under a name)
    def layout_description(self)->dict:
        """The figure as stored in an export profile (see export_presets/README.md)."""
        panels=[]
        for fields in self.controls[:self._n_panels()]:
            choice=fields['image'].currentData() or {}
            scan_path=fields['scan'].currentData()
            item={'scan':Path(scan_path).name if scan_path else 'current',
                  'trace':str(fields['trace'].currentData() or 'forward'),
                  'title':fields['title'].text().strip(),'unit':fields['unit'].text().strip(),
                  'show_colorbar':fields['show_colorbar'].isChecked(),
                  'colorbar_position':str(fields['legend'].currentData() or 'below'),
                  'show_scale_bar':fields['show_scalebar'].isChecked(),
                  'scale_bar_color':fields['scalebar_color'].text().strip() or '#111111',
                  'scale_bar_position':str(fields['scalebar_position'].currentData() or 'bottom_right')}
            if choice.get('kind')=='channel':
                item.update(source='channel',channel=str(choice.get('channel','')))
            else:
                item.update(source='result',result=Path(str(choice.get('path',''))).stem,
                            colorbar_source=str(fields['colorbar_source'].currentData() or ''))
            panels.append(item)
        return {'arrangement':self.arrangement(),'columns':int(self.grid_columns.value()),
                'panel_letters':self.panel_letters.isChecked(),'transparent':self.transparent.isChecked(),
                'formats':self.formats() or ['svg'],'panels':panels}

    def apply_layout(self,layout:dict):
        """Rebuild the figure of a saved export profile on the scan that is open now."""
        from ..core.presets import validate_export_layout
        layout=validate_export_layout(layout)
        panels=layout['panels']
        self.layout_mode.setCurrentIndex(max(0,self.layout_mode.findData('custom')))
        self.panel_count.setCurrentIndex(len(panels)-1)
        self.grid_columns.setValue(int(layout.get('columns',0)))
        button=self.arrangement_buttons.get(layout.get('arrangement','grid'))
        if button is not None and not button.isHidden():
            button.setChecked(True)
        self.panel_letters.setChecked(bool(layout.get('panel_letters')))
        self.transparent.setChecked(bool(layout.get('transparent')))
        for key,box in self.format_boxes.items():box.setChecked(key in layout.get('formats',['svg']))
        self._ensure_controls(len(panels))
        missing=[]
        for index,(fields,panel) in enumerate(zip(self.controls,panels)):
            wanted_scan=panel.get('scan','current')
            scan_index=0
            if wanted_scan not in ('','current'):
                scan_index=next((i for i in range(fields['scan'].count())
                                 if Path(str(fields['scan'].itemData(i) or '')).name==wanted_scan),0)
                if scan_index==0:missing.append(f'scan {wanted_scan}')
            if fields['scan'].currentIndex()!=scan_index:fields['scan'].setCurrentIndex(scan_index)
            image=fields['image']
            target=-1
            if panel.get('source','channel')=='channel':
                target=next((i for i in range(image.count())
                             if (image.itemData(i) or {}).get('channel')==panel.get('channel')),-1)
                if target<0:missing.append(f"channel {panel.get('channel','?')}")
            else:
                fragment=str(panel.get('result','')).lower()
                target=next((i for i in range(image.count())
                             if (image.itemData(i) or {}).get('kind')=='report'
                             and fragment and fragment in Path(str(image.itemData(i).get('path',''))).stem.lower()),-1)
                if target<0:missing.append(f"result {panel.get('result','?')}")
            if target>=0:image.setCurrentIndex(target)
            self._set_defaults(index)
            fields['trace'].setCurrentIndex(max(0,fields['trace'].findData(panel.get('trace','forward'))))
            if panel.get('title'):fields['title'].setText(panel['title'])
            fields['unit'].setText(panel.get('unit',''))
            if 'colorbar_source' in panel and panel['colorbar_source']:
                fields['colorbar_source'].setCurrentIndex(max(0,fields['colorbar_source'].findData(panel['colorbar_source'])))
            if 'show_colorbar' in panel and fields['show_colorbar'].isEnabled():
                fields['show_colorbar'].setChecked(bool(panel['show_colorbar']))
            if 'colorbar_position' in panel:
                fields['legend'].setCurrentIndex(max(0,fields['legend'].findData(panel['colorbar_position'])))
            if 'show_scale_bar' in panel:fields['show_scalebar'].setChecked(bool(panel['show_scale_bar']))
            if panel.get('scale_bar_color'):fields['scalebar_color'].setText(panel['scale_bar_color'])
            if 'scale_bar_position' in panel:
                fields['scalebar_position'].setCurrentIndex(max(0,fields['scalebar_position'].findData(panel['scale_bar_position'])))
            self._bar_changed(index)
        self._layout_changed()
        if missing:
            self.profile_status.setText('Not available on this scan, replaced by a default: '+', '.join(dict.fromkeys(missing)))

    def profile_data(self,name:str)->dict:
        from ..core.presets import validate_export
        base={k:v for k,v in self.preset.items() if k!='layout'}
        return validate_export({**base,'schema_version':1,'name':name,
                                'width_mm':self.page_width.value(),'height_mm':self.page_height.value(),
                                'dpi':self.page_dpi.value(),'layout':self.layout_description()})

    def save_as_profile(self):
        """Ask for a name and write ``export_presets/<name>.json``; usable at once."""
        from spm_studio.shared.dialogs import MessageDialog, TextInputDialog
        from ..core.presets import write_json, validate_export
        from ..core import paths
        folder=self.save_folder or (paths.customization_dir()/'export_presets')
        suggestion=self.preset_name if self.preset_name not in BUILTIN_MODES+('custom',) else 'my_figure'
        name,ok=TextInputDialog.getText(self,'Save as export profile','Name of the export profile',text=suggestion)
        if not ok or not name.strip():return
        safe=''.join(c if c.isalnum() or c in '-_' else '_' for c in name.strip()).strip('_')
        if not safe:
            MessageDialog.warning(self,'Export profile','Use a name containing letters or digits.');return
        if safe in BUILTIN_MODES+('custom',):
            MessageDialog.warning(self,'Export profile',f'“{safe}” is a built-in format; choose another name.');return
        target=folder/f'{safe}.json'
        if target.exists() and MessageDialog.question(self,'Replace export profile?',
                f'{target.name} exists. Replace it?')!=MessageDialog.StandardButton.Yes:
            return
        try:
            write_json(target,self.profile_data(safe),validate_export)
        except Exception as exc:
            MessageDialog.warning(self,'Export profile',f'Could not save: {exc}');return
        try:paths.mark_factory_item_removed(f'export_presets/{target.name}',False)
        except Exception:pass
        self.preset_name=safe
        self.profile_status.setText(f'Saved “{safe}”. It is now in the figure list of the top bar.')
        self.profileSaved.emit(safe)
