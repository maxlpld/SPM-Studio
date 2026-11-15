"""Plot/output options belong to Studio, not separate legacy script windows."""
from __future__ import annotations
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QComboBox,QCheckBox,
    QPushButton,QDialogButtonBox,QHBoxLayout,QFileDialog,QMessageBox,QLabel,QGroupBox,QDoubleSpinBox,QPlainTextEdit)
from spm_studio.shared.dialogs import MessageDialog as QMessageBox, TextInputDialog as QInputDialog
from PySide6.QtCore import Qt
from pathlib import Path
import shutil,json
from spm_studio.core import paths
from spm_studio.core.plot_settings import available_styles,load_plot,validate_plot
from spm_studio.shared.ui_strings import add_key_items, combo_key, set_combo_key

CUSTOM_KEYS=('colormap_override','show_titles','text_replacements','colorbar_mode',
             'colorbar_size_pct','legend_mode','legend_frame')


def load_figure_customization(settings):
    """v32: user figure customization stored in the Studio settings (JSON)."""
    from spm_studio.core.plot_settings import DEFAULT_PLOT,validate_plot
    base={k:DEFAULT_PLOT[k] for k in CUSTOM_KEYS}
    try:
        raw=json.loads(str(settings.value('figure_customization','{}')) or '{}')
        merged=validate_plot({'schema_version':1,**{k:raw[k] for k in CUSTOM_KEYS if k in raw}})
        return {k:merged[k] for k in CUSTOM_KEYS}
    except Exception:
        return base


def script_formats(settings):
    """v0.8: figure formats written by analysis tools. SVG only unless the user ticks more."""
    raw=str(settings.value('script_formats_v08','svg') or 'svg')
    chosen=[f for f in ('svg','pdf','png') if f in raw.split(',')]
    return chosen or ['svg']


def save_figure_customization(settings,values):
    settings.setValue('figure_customization',json.dumps({k:values[k] for k in CUSTOM_KEYS if k in values}))


class PlotOptions(QDialog):
    def __init__(self,parent,settings):
        super().__init__(parent)
        self.setWindowTitle('Results & figures')
        self.setMinimumWidth(560)
        self.settings=settings
        main=QVBoxLayout(self)
        form=QFormLayout()
        self.style=QComboBox()
        self._reload_styles()
        set_combo_key(self.style,str(settings.value('plot_style','Clean publication')))
        form.addRow('Plot style',self.style)
        fmt_row=QHBoxLayout();self.format_boxes={}
        current=script_formats(settings)
        for key,label in (('svg','SVG'),('pdf','PDF'),('png','PNG')):
            box=QCheckBox(label);box.setObjectName('ScriptFormatV08_'+key)
            box.setChecked(key in current);self.format_boxes[key]=box;fmt_row.addWidget(box)
        fmt_row.addStretch(1)
        self.format_boxes['svg'].setToolTip('Default. Vector figure, identical to Export…')
        form.addRow('Save results as',fmt_row)
        self.show_results=QCheckBox('Show the result after each run')
        self.show_results.setChecked(str(settings.value('show_module_result','false')).lower()=='true')
        form.addRow(self.show_results)
        self.transparent=QCheckBox('Transparent background')
        self.transparent.setObjectName('GlobalTransparentExportV30')
        self.transparent.setToolTip('No white page behind figures, scans and plots, so they sit directly on any '
                                    'slide or poster colour. JPEG cannot store transparency and stays white.')
        self.transparent.setChecked(str(settings.value('export_transparent','false')).lower()=='true')
        form.addRow(self.transparent)
        main.addLayout(form)
        # v32: figure customization for every analysis script (lattice, CPD, flake, KPFM, …)
        from spm_studio.core.plot_settings import VALID_MPL_CMAPS,COLORBAR_MODES,LEGEND_MODES
        custom=load_figure_customization(settings)
        box=QGroupBox('Plots of analysis tools');box.setObjectName('FigureCustomizationV32')
        cf=QFormLayout(box)
        self.cmap=QComboBox();self.cmap.addItem("Script default",'')
        for name in sorted(VALID_MPL_CMAPS,key=str.lower):self.cmap.addItem(name,name)
        set_combo_key(self.cmap,custom['colormap_override'])
        cf.addRow('Colormap (FFT, Δf…)',self.cmap)
        self.titles=QCheckBox('Show plot titles');self.titles.setChecked(custom['show_titles']);cf.addRow(self.titles)
        self.cbar=QComboBox()
        for m in COLORBAR_MODES:self.cbar.addItem({'auto':'Script default','hide':'Hide colourbars'}.get(m,m.capitalize()),m)
        set_combo_key(self.cbar,custom['colorbar_mode'])
        self.cbar_size=QDoubleSpinBox();self.cbar_size.setRange(1,40);self.cbar_size.setSuffix(' % thickness')
        self.cbar_size.setValue(custom['colorbar_size_pct'])
        cbr=QHBoxLayout();cbr.addWidget(self.cbar,1);cbr.addWidget(self.cbar_size)
        cf.addRow('Colourbar',cbr)
        self.legend=QComboBox()
        for m in LEGEND_MODES:self.legend.addItem({'auto':'Script default','hide':'Hide legends'}.get(m,m),m)
        set_combo_key(self.legend,custom['legend_mode'])
        self.legend_frame=QCheckBox('frame');self.legend_frame.setChecked(custom['legend_frame'])
        lr=QHBoxLayout();lr.addWidget(self.legend,1);lr.addWidget(self.legend_frame)
        cf.addRow('Legend',lr)
        self.replacements=QPlainTextEdit(custom['text_replacements'])
        self.replacements.setPlaceholderText('One per line, old => new (LaTeX allowed), e.g.\n'
                                             '2D FFT diagnostic => $\\Delta f$ FFT\nDistance (nm) => $x$ (nm)\nPeak positions =>')
        self.replacements.setMaximumHeight(96)
        cf.addRow('Rename labels',self.replacements)
        main.addWidget(box)
        row=QHBoxLayout()
        sample=QPushButton('Duplicate style')
        sample.clicked.connect(self._clone_style)
        import_style=QPushButton('Import JSON…')
        import_style.clicked.connect(self._import_style)
        folder=QPushButton('Open folder')
        folder.clicked.connect(lambda:parent._open_directory(paths.customization_dir()/'plot_styles'))
        for b in (sample,import_style,folder):row.addWidget(b)
        main.addLayout(row)
        actions=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(self._accept)
        actions.rejected.connect(self.reject)
        main.addWidget(actions)

    def _reload_styles(self):
        styles,_=available_styles(paths.customization_dir()/'plot_styles')
        current=combo_key(self.style) if self.style.count() else None
        self.style.clear()
        add_key_items(self.style,styles)
        if current:set_combo_key(self.style,current)

    def _clone_style(self):
        from spm_studio.shared.dialogs import TextInputDialog as QInputDialog
        name,ok=QInputDialog.getText(self,'New plot profile','Profile name:')
        if not ok or not name.strip():return
        safe=''.join(c if c.isalnum() or c in '-_' else '_' for c in name.strip())
        folder=paths.customization_dir()/'plot_styles';folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'{safe}.json'
        if path.exists():
            QMessageBox.warning(self,'Already exists',str(path));return
        styles,_=available_styles(folder)
        data=dict(styles[combo_key(self.style)]);data['name']=name.strip()
        path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
        self._reload_styles();set_combo_key(self.style,safe)
        QMessageBox.information(self,'Editable profile saved',str(path))

    def _import_style(self):
        path,_=QFileDialog.getOpenFileName(self,'Import publication style','','JSON (*.json)')
        if not path:return
        try:
            data=load_plot(path)
            out=paths.customization_dir()/'plot_styles'/Path(path).name
            if out.exists():raise FileExistsError(out)
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
            self._reload_styles();set_combo_key(self.style,out.stem)
        except (ValueError,OSError,TypeError) as e:
            QMessageBox.warning(self,'Invalid style',str(e))

    def _accept(self):
        self.settings.setValue('plot_style',combo_key(self.style))
        chosen=[k for k,b in self.format_boxes.items() if b.isChecked()] or ['svg']
        self.settings.setValue('script_formats_v08',','.join(chosen))
        self.settings.setValue('show_module_result',self.show_results.isChecked())
        self.settings.setValue('export_transparent','true' if self.transparent.isChecked() else 'false')
        save_figure_customization(self.settings,{
            'colormap_override':self.cmap.currentData() or '','show_titles':self.titles.isChecked(),
            'colorbar_mode':self.cbar.currentData(),'colorbar_size_pct':float(self.cbar_size.value()),
            'legend_mode':self.legend.currentData(),'legend_frame':self.legend_frame.isChecked(),
            'text_replacements':self.replacements.toPlainText()})
        self.accept()
