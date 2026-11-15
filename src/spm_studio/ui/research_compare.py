"""Run comparison: no interpolation or invented unit equivalence."""
from pathlib import Path
import csv, json, math
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,
    QPushButton,QComboBox,QLabel,QFileDialog,QMessageBox,QCheckBox,QAbstractItemView,QHeaderView)
from spm_studio.shared.dialogs import MessageDialog as QMessageBox, TextInputDialog as QInputDialog
from PySide6.QtCore import Qt
from spm_studio.shared import ResearchStore
from spm_studio.shared.ui_strings import ui_label, add_key_items, combo_key, set_combo_key

class CompareDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Compare SPM runs')
        self.resize(1100,630)
        self.setMinimumSize(640,420)
        self.store=ResearchStore()
        self.runs=self.store.runs()
        layout=QVBoxLayout(self)
        filters=QHBoxLayout()
        self.modules=QComboBox();self.modules.addItem('All tools','')
        add_key_items(self.modules,sorted({r['module_id'] for r in self.runs}))
        self.modules.currentTextChanged.connect(self.refresh)
        filters.addWidget(QLabel('Module'))
        filters.addWidget(self.modules)
        self.quant=QComboBox();self.quant.currentTextChanged.connect(self.refresh)
        filters.addWidget(QLabel('Quantity'))
        filters.addWidget(self.quant)
        filters.addStretch()
        layout.addLayout(filters)
        self.table=QTableWidget();self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(['Use','Scan','Module','Table','Quantity','Value','Unit','Uncertainty','Run ID'])
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)
        self.empty=QLabel('No measurements match these filters.')
        self.empty.setObjectName('muted');layout.addWidget(self.empty)
        footer=QHBoxLayout()
        self.action_buttons=[]
        for title,fn in [('Plot selected',self.plot),('Export CSV',self.export_csv),('Open selected run',self.open_run)]:
            b=QPushButton(title);b.clicked.connect(fn);footer.addWidget(b);self.action_buttons.append(b)
        footer.addStretch()
        layout.addLayout(footer)
        self.update_quant()
        self.refresh()

    def update_quant(self):
        previous=combo_key(self.quant)
        self.quant.blockSignals(True)
        self.quant.clear();self.quant.addItem('All quantities','')
        add_key_items(self.quant,sorted({m['key'] for r in self.runs for m in r.get('measurements',[])}))
        if self.quant.findData(previous)>=0:set_combo_key(self.quant,previous)
        self.quant.blockSignals(False)

    def refresh(self,*_):
        mod=combo_key(self.modules);quan=combo_key(self.quant)
        self.table.setRowCount(0)
        for r in self.runs:
            if mod and mod!=r['module_id']:continue
            for m in r.get('measurements',[]):
                if quan and quan!=m['key']:continue
                n=self.table.rowCount();self.table.insertRow(n)
                check=QCheckBox();check.setAccessibleName('Include measurement from '+Path(r['source_path']).name)
                check.setChecked(True);self.table.setCellWidget(n,0,check)
                cells=[Path(r['source_path']).name,r['module_id'],m.get('table',''),m['key'],
                       str(m['value']),str(m.get('unit') or 'unspecified'),
                       str(m.get('uncertainty') if m.get('uncertainty') is not None else 'unreported'),
                       r['result_id']]
                for j,value in enumerate(cells,1):
                    item=QTableWidgetItem(ui_label(value) if j in (2,3,4) else value)
                    item.setData(Qt.ItemDataRole.UserRole,value)
                    self.table.setItem(n,j,item)
        self.table.resizeColumnsToContents()
        self.empty.setVisible(self.table.rowCount()==0)
        for button in self.action_buttons:button.setEnabled(self.table.rowCount()>0)

    def selected(self):
        return [[self.table.item(i,j).data(Qt.ItemDataRole.UserRole) for j in range(1,9)] for i in range(self.table.rowCount())
                if self.table.cellWidget(i,0).isChecked()]

    def export_csv(self):
        rows=self.selected()
        if not rows:
            QMessageBox.information(self,'No measurements selected','Select at least one measurement to export.');return
        path,_=QFileDialog.getSaveFileName(self,'Save selected comparison','comparison.csv','CSV (*.csv)')
        if not path:return
        try:
            with open(path,'w',newline='',encoding='utf-8') as f:
                w=csv.writer(f);w.writerow(['scan','module','table','quantity','value','unit','uncertainty','run_id']);w.writerows(rows)
        except OSError as exc:QMessageBox.warning(self,'Cannot export comparison',str(exc))

    def plot(self):
        rows=self.selected()
        quantities={(r[3],r[5]) for r in rows}
        if len(quantities)!=1:
            QMessageBox.information(self,'Incompatible quantities','Select exactly one quantity and one declared unit.\nMixed units cannot be plotted safely.');return
        try:
            import matplotlib.pyplot as plt
            vals=[float(r[4]) for r in rows]
            errors=[float(r[6]) if r[6]!='unreported' else 0 for r in rows]
            fig,ax=plt.subplots(figsize=(9,5.5));idx=range(len(rows))
            ax.errorbar(list(idx),vals,yerr=errors,fmt='o',capsize=3)
            ax.set_xticks(list(idx),[r[0] for r in rows],rotation=45,ha='right')
            quantity,unit=next(iter(quantities));ax.set_ylabel(f'{ui_label(quantity)} ({unit})')
            ax.set_title('Selected runs · uncertainties omitted when unreported');fig.tight_layout()
            from ..core.plots import finalize_publication_figure
            finalize_publication_figure(fig)
            out,_=QFileDialog.getSaveFileName(self,'Save vector figure','comparison.svg','SVG (*.svg);;PDF (*.pdf);;PNG 600 DPI (*.png)')
            if out:
                from ..core.plots import savefig_maybe_transparent
                parent=self.parent()
                transparent=bool(getattr(parent,'export_transparent',lambda:False)()) if parent else False
                savefig_maybe_transparent(fig,out,transparent=transparent,dpi=600,bbox_inches='tight',pad_inches=.01)
            plt.show(block=False)
        except Exception as exc:QMessageBox.warning(self,'Plot failed',str(exc))

    def open_run(self):
        row=self.table.currentRow()
        if row>=0:
            run_id=self.table.item(row,8).data(Qt.ItemDataRole.UserRole)
        else:
            rows=self.selected()
            if not rows:return
            run_id=rows[0][-1]
        r=self.store.run(run_id)
        if not r:return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(r['run_folder']))
