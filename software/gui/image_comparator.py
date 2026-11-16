"""One graphics view with switchable originals, registration, difference and overlay."""
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,
    QPlainTextEdit,QTableWidget,QTableWidgetItem,QFileDialog,QMessageBox,QDialogButtonBox,
    QFormLayout,QSpinBox,QLineEdit,QApplication,QLabel)
from .image_viewer import ImageViewer
from software.vision.led_detection import analyze_paths,export
from . import ensure_fonts


class AnalysisDialog(QDialog):
    def __init__(self,analysis,parent=None):
        ensure_fonts(); super().__init__(parent); self.analysis=analysis; self.unknown_point=None
        self.setWindowTitle('RGB Vision - manual optical review'); self.resize(1300,950)
        layout=QVBoxLayout(self)
        registration=analysis.result['registrations']
        def error(name):
            value=registration[name]['reprojection_rmse_px']
            return f'{value:.3f} px' if value is not None else 'n/a'
        quality=QLabel(f"Geometry: {analysis.result['registration_status']} | OFF RMSE {error('off')} | ON RMSE {error('on')} | Analysis: {analysis.result['analysis_status']}")
        quality.setWordWrap(True); layout.addWidget(quality)
        controls=QHBoxLayout()
        self.mode=QComboBox(); self.mode.addItems(list(analysis.images))
        controls.addWidget(self.mode); self.overlay=QPushButton('Toggle detection overlay')
        controls.addWidget(self.overlay); save=QPushButton('Export JSON / CSV / PNG'); controls.addWidget(save)
        layout.addLayout(controls); self.viewer=ImageViewer(); layout.addWidget(self.viewer,1)
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['LED ID','Key name','Color','Brightness','Ambiguity / action'])
        self.table.setMaximumHeight(160); self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers); layout.addWidget(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row,record in enumerate(analysis.result['detections']):
            self.table.insertRow(row)
            for col,value in enumerate([record['led_id'] or 'UNKNOWN',record['key_name'] or '',record['color'],f"{record['brightness']:.2f}",', '.join(record['ambiguity_flags'])]):
                self.table.setItem(row,col,QTableWidgetItem(value))
        self.add=QPushButton('Add selected UNKNOWN to reference map (choose its PCB ID manually)')
        layout.addWidget(self.add); self.add.clicked.connect(self.choose_unknown)
        self.report=QPlainTextEdit(); self.report.setReadOnly(True); self.report.setMaximumHeight(170)
        summary={key:value for key,value in analysis.result.items() if key not in ['detections']}
        self.report.setPlainText(json.dumps(summary,indent=2,ensure_ascii=False)); layout.addWidget(self.report)
        self.mode.currentTextChanged.connect(self.show_image)
        self.overlay.clicked.connect(self.toggle_overlay); save.clicked.connect(self.save_results)
        self.table.cellClicked.connect(self.center_record)
        self.show_image('Detected LEDs' if 'Detected LEDs' in analysis.images else 'ON markers')

    def show_image(self,name):
        self.mode.blockSignals(True); self.mode.setCurrentText(name); self.mode.blockSignals(False)
        self.viewer.set_image(self.analysis.images[name])

    def toggle_overlay(self):
        if 'Detected LEDs' not in self.analysis.images: return
        self.show_image('Registered ON' if self.mode.currentText()=='Detected LEDs' else 'Detected LEDs')

    def center_record(self,row,column):
        record=self.analysis.result['detections'][row]
        if self.mode.currentText() not in ['Detected LEDs','Registered OFF','Registered ON','Difference','Valid overlap']:
            self.show_image('Detected LEDs')
        self.viewer.set_zoom(2); self.viewer.centerOn(record['x_ref_px'],record['y_ref_px'])

    def choose_unknown(self):
        row=self.table.currentRow()
        if row<0: return
        record=self.analysis.result['detections'][row]
        if record['led_id'] is not None:
            QMessageBox.information(self,'Existing LED','This region is already associated with a mapped LED.'); return
        self.unknown_point=(record['x_ref_px'],record['y_ref_px']); self.accept()

    def save_results(self):
        path=QFileDialog.getExistingDirectory(self,'Select export directory')
        if not path: return
        overwrite=False
        if any(Path(path).iterdir()):
            overwrite=QMessageBox.question(self,'Existing directory','Overwrite known analysis files in this directory? Other files remain untouched.')==QMessageBox.Yes
            if not overwrite: return
        try: export(self.analysis,path,overwrite); QMessageBox.information(self,'Export',f'Saved in {path}')
        except Exception as exc: QMessageBox.warning(self,'Export failed',str(exc))


def analyze_dialog(window):
    off,_=QFileDialog.getOpenFileName(window,'Select OFF photograph','','Images (*.jpg *.jpeg *.png *.tif *.tiff)')
    if not off: return
    on,_=QFileDialog.getOpenFileName(window,'Select ON photograph','','Images (*.jpg *.jpeg *.png *.tif *.tiff)')
    if not on: return
    options=QDialog(window); options.setWindowTitle('Photo analysis settings'); form=QFormLayout(options)
    threshold=QSpinBox(); threshold.setRange(1,255); threshold.setValue(30)
    radius=QSpinBox(); radius.setRange(1,1000); radius.setValue(20)
    experiment=QLineEdit(Path(on).stem)
    form.addRow('Brightness delta threshold',threshold); form.addRow('LED match radius, reference px',radius)
    form.addRow('Experiment ID',experiment)
    buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); form.addRow(buttons)
    buttons.accepted.connect(options.accept); buttons.rejected.connect(options.reject)
    if not options.exec(): return
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        analysis=analyze_paths(window.document.data,off,on,experiment.text(),threshold=threshold.value(),match_radius=radius.value())
    finally: QApplication.restoreOverrideCursor()
    dialog=AnalysisDialog(analysis,window); dialog.exec()
    if dialog.unknown_point:
        window.viewer.set_image(window.reference_image); window.refresh()
        window.viewer.centerOn(*dialog.unknown_point); window.add_at(*dialog.unknown_point)
