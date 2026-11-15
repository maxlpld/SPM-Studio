"""Choose publication panels, including script-generated lattice PDF results."""
from pathlib import Path
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QGroupBox,QComboBox,
    QLineEdit,QLabel,QDialogButtonBox,QFormLayout,QCheckBox,QHBoxLayout,QPushButton,QDoubleSpinBox,QSpinBox,QButtonGroup,QWidget)
from ..core.export_layout import panel_defaults
from .color_field import ColorField

class PublicationDialog(QDialog):
    def __init__(self, scan, report_files=(), *, two_columns=False, selected_channel='',
                 selected_trace='forward', channel_titles=None, preset=None, layout_name=None, parent=None,
                 transparent=False, arrangement='triangle', formats=('svg',)):
        super().__init__(parent)
        self.setWindowTitle('Export figure')
        self.setMinimumWidth(980)
        self.scan=scan
        self.preset=dict(preset or {})
        self.preset_name=str(layout_name or self.preset.get('name','single_column'))
        self.selected_trace=selected_trace
        self.channel_titles=channel_titles or {}
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
            self.preset_name if self.preset_name in ('single_column','double_column','triple','square') else 'custom')))
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
        self.panel_count.addItem('One image',1);self.panel_count.addItem('Two images',2)
        self.panel_count.addItem('Three images',3)
        layout_form.addRow('Images',self.panel_count)
        # v30: arrangement of three images — row, triangle ▲ or reverse triangle ▼
        self.arrangement_row=QWidget();arr=QHBoxLayout(self.arrangement_row);arr.setContentsMargins(0,0,0,0)
        self.arrangement_group=QButtonGroup(self);self.arrangement_group.setExclusive(True)
        self.arrangement_buttons={}
        for key,label,tip in (('row','▭ ▭ ▭  Row','Three images side by side'),
                              ('triangle','▲  Triangle','One image centred on top, two below'),
                              ('inverted_triangle','▼  Reverse triangle','Two images on top, one centred below')):
            b=QPushButton(label);b.setCheckable(True);b.setToolTip(tip)
            b.setObjectName('TripleArrangement_'+key)
            self.arrangement_group.addButton(b);arr.addWidget(b);self.arrangement_buttons[key]=b
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
        self.controls=[]
        row=QHBoxLayout(); root.addLayout(row)
        for index,side in enumerate(('Left image','Right image','Third image')):
            group=QGroupBox(side); form=QFormLayout(group)
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
            data={'group':group,'image':image,'trace':trace,'title':title,'unit':unit,'legend':legend,'scalebar_color':scalebar_color,'scalebar_position':scalebar_position,'show_scalebar':show_scalebar,
                  'show_colorbar':show_colorbar,'colorbar_source':source,'unit_buttons':unit_buttons}
            show_colorbar.toggled.connect(lambda checked,n=index:self._bar_changed(n))
            source.currentIndexChanged.connect(lambda _,n=index:self._bar_changed(n))
            self.controls.append(data)
            image.currentIndexChanged.connect(lambda _,n=index:self._set_defaults(n))
            if index==0:
                current=next((i for i,(v,_) in enumerate(self.choices) if v.get('channel')==selected_channel),0); image.setCurrentIndex(current)
            elif len(self.choices)>1:
                used={c['image'].currentIndex() for c in self.controls[:-1]}
                image.setCurrentIndex(next((i for i,(v,_) in enumerate(self.choices)
                                            if i not in used and v['kind']=='channel'),
                                           min(index,len(self.choices)-1)))
            self._set_defaults(index); row.addWidget(group,1)
        self.layout_mode.currentIndexChanged.connect(self._layout_changed)
        self.panel_count.currentIndexChanged.connect(self._layout_changed)
        self._layout_changed()
        for control in self.controls: control['trace'].setCurrentIndex(max(0,control['trace'].findData(selected_trace)))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Export…')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty('primary',True)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        self._ok_button=buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._formats_changed()

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
        self.double.setChecked(n>=2)
        self.controls[1]['group'].setVisible(n>=2)
        self.controls[2]['group'].setVisible(n==3)
        self.arrangement_row.setVisible(n==3)
        self.panel_letters.setVisible(n>=2)
        self._update_titles()

    def _n_panels(self):
        mode=self.layout_mode.currentData()
        if mode=='double_column':return 2
        if mode=='triple':return 3
        if mode=='custom':return int(self.panel_count.currentData() or 1)
        return 1

    def arrangement(self)->str:
        for key,button in self.arrangement_buttons.items():
            if button.isChecked():return key
        return 'row'

    def _triple_height(self):
        return 72. if self.arrangement()=='row' else 168.

    def _arrangement_changed(self):
        if self.layout_mode.currentData()=='triple':
            self.page_height.setValue(self._triple_height())
        self._update_titles()

    def _update_titles(self):
        n=self._n_panels()
        if n==1:titles=('Image','','')
        elif n==2:titles=('Left','Right','')
        else:
            titles={'row':('a · Left','b · Middle','c · Right'),
                    'triangle':('a · Top','b · Bottom left','c · Bottom right'),
                    'inverted_triangle':('a · Top left','b · Top right','c · Bottom')}[self.arrangement()]
        for control,title in zip(self.controls,titles):
            if title:control['group'].setTitle(title)

    def letters_enabled(self)->bool:
        return self._n_panels()>1 and self.panel_letters.isChecked()

    def resolved_preset(self):
        from ..core.presets import validate_export
        return validate_export({**self.preset,'schema_version':1,
            'name':self.layout_mode.currentData(),
            'width_mm':self.page_width.value(),'height_mm':self.page_height.value(),
            'dpi':self.page_dpi.value()})

    def _set_defaults(self,index):
        fields=self.controls[index]
        choice=fields['image'].currentData()
        if not choice:return
        defaults=panel_defaults(self.scan,choice,self.selected_trace)
        fields['title'].setText(self.channel_titles.get(defaults.get('channel'),defaults['title']))
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
        for fields in self.controls[:self._n_panels()]:
            spec=panel_defaults(self.scan,fields['image'].currentData(),fields['trace'].currentData())
            spec['trace']=fields['trace'].currentData()
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
