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
        self.records=analysis.result['known_leds'] if analysis.result['parameters']['mode']=='KNOWN_LEDS' else analysis.result['candidates']
        self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['LED ID','Key name','Status','Color','Brightness','Chroma','Reason / ambiguity'])
        self.table.setMaximumHeight(160); self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers); layout.addWidget(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row,record in enumerate(self.records):
            self.table.insertRow(row)
            for col,value in enumerate([record['led_id'] or 'UNKNOWN',record['key_name'] or '',record['status'],record['color'],f"{record['brightness']:.2f}",f"{record['chroma']:.2f}",', '.join(record['rejection_reasons']+record['ambiguity_flags'])]):
                self.table.setItem(row,col,QTableWidgetItem(value))
        self.add=QPushButton('Add selected UNKNOWN to reference map (choose its PCB ID manually)')
        layout.addWidget(self.add); self.add.clicked.connect(self.choose_unknown)
        self.report=QPlainTextEdit(); self.report.setReadOnly(True); self.report.setMaximumHeight(170)
        summary={key:value for key,value in analysis.result.items() if key not in ['detections','candidates']}
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
        record=self.records[row]
        if 'Detected LEDs' not in self.analysis.images: return
        self.report.setPlainText(json.dumps(record,indent=2,ensure_ascii=False))
        if self.mode.currentText() not in ['Detected LEDs','Registered OFF','Registered ON','Difference','Valid overlap']:
            self.show_image('Detected LEDs')
        self.viewer.set_zoom(2); self.viewer.centerOn(record['x_ref_px'],record['y_ref_px'])

    def choose_unknown(self):
        row=self.table.currentRow()
        if row<0: return
        record=self.records[row]
        if record['led_id'] is not None:
            QMessageBox.information(self,'Existing LED','This region is already associated with a mapped LED.'); return
        if record['status']!='CANDIDATE':
            QMessageBox.information(self,'Rejected candidate','Inspect the rejection reasons before changing the map.'); return
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
    mode=QComboBox(); mode.addItems(['KNOWN_LEDS','DISCOVER'])
    roi=QSpinBox(); roi.setRange(5,500); roi.setValue(40)
    chroma=QSpinBox(); chroma.setRange(1,255); chroma.setValue(25)
    area=QSpinBox(); area.setRange(1,100000); area.setValue(6)
    form.addRow('Analysis mode',mode); form.addRow('LED ROI radius, reference px',roi)
    form.addRow('New chroma threshold',chroma); form.addRow('Minimum color area, px',area)
    experiment=QLineEdit(Path(on).stem)
    form.addRow('Brightness delta threshold',threshold)
    form.addRow('Experiment ID',experiment)
    buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); form.addRow(buttons)
    buttons.accepted.connect(options.accept); buttons.rejected.connect(options.reject)
    if not options.exec(): return
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        analysis=analyze_paths(window.document.data,off,on,experiment.text(),threshold=threshold.value(),match_radius=radius.value(),
            mode=mode.currentText(),roi_radius=roi.value(),color_threshold=chroma.value(),min_area=area.value())
    finally: QApplication.restoreOverrideCursor()
    dialog=AnalysisDialog(analysis,window); dialog.exec()
    if dialog.unknown_point:
        window.viewer.set_image(window.reference_image); window.refresh()
        window.viewer.centerOn(*dialog.unknown_point); window.add_at(*dialog.unknown_point)
