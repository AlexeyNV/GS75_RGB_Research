"""Persistent result browser; only the selected full-resolution layer is loaded."""
import json
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
    QPushButton,QTableWidget,QTableWidgetItem,QPlainTextEdit,QAbstractItemView)
from .image_viewer import ImageViewer
from software.vision.research_project import LAYERS
from software.vision.project_storage import read_image
from software.vision.image_registration import transform_points


class ResultPane(QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.record=None;self.path=None;self.records=[];self.pending_layer=None
        layout=QVBoxLayout(self)
        self.quality=QLabel('Выберите результат в истории');self.quality.setWordWrap(True);layout.addWidget(self.quality)
        row=QHBoxLayout();self.layers=QComboBox();row.addWidget(self.layers)
        add=QPushButton('Добавить кандидата в карту');add.clicked.connect(self.add_candidate);row.addWidget(add);layout.addLayout(row)
        self.viewer=ImageViewer();self.viewer.add_mode=True;layout.addWidget(self.viewer,1)
        self.table=QTableWidget(0,10);self.table.setHorizontalHeaderLabels(
            ['LED','Клавиша','Статус','Цвет','X / Y','Яркость','Цветность','Регистрация','Уверенность','Причины'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMaximumHeight(180);layout.addWidget(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(4,150)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(100);layout.addWidget(self.details)
        self.layers.currentTextChanged.connect(self.show_layer);self.table.cellClicked.connect(self.center_record)
        self.viewer.pointClicked.connect(self.image_clicked)

    def open(self,path):
        self.path=Path(path);self.record=json.loads((self.path/'results.json').read_text(encoding='utf-8'))
        r=self.record;self.records=r['known_leds'] if r['parameters']['mode']=='KNOWN_LEDS' else r['candidates']
        self.quality.setText(f"Геометрия: {r['registration_status']} | Анализ: {r['analysis_status']} | "+
            ' | '.join(f"{k}: {v.get('reason')} RMSE={v.get('reprojection_rmse_px')}" for k,v in r['registrations'].items()))
        self.table.setRowCount(len(self.records))
        for row,rec in enumerate(self.records):
            values=[rec.get('led_id') or 'UNKNOWN',rec.get('key_name') or '',rec['status'],rec['color'],
                f"{rec['x_ref_px']:.2f} / {rec['y_ref_px']:.2f}",f"{rec['brightness']:.2f}",f"{rec['chroma']:.2f}",
                r['registration_status'],f"{rec.get('color_confidence',0):.3f}",
                ', '.join(rec.get('rejection_reasons',[])+rec.get('ambiguity_flags',[]))]
            for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(str(value)))
        self.layers.blockSignals(True);self.layers.clear()
        self.layers.addItems([k for k,v in LAYERS.items() if (self.path/v).is_file()])
        sources=r.get('sources',{})
        for role,label in [('off','Original OFF'),('on','Original ON')]:
            if role in sources:self.layers.addItem(label)
        chosen='Detected LEDs' if self.layers.findText('Detected LEDs')>=0 else self.layers.itemText(0)
        self.layers.setCurrentText(chosen);self.layers.blockSignals(False);self.show_layer(chosen)
        self.details.setPlainText(json.dumps({k:v for k,v in r.items() if k not in ('candidates','detections','known_leds')},indent=2,ensure_ascii=False))

    def show_layer(self,name):
        if not name or not self.record:return
        if self.owner.active_job:self.pending_layer=name;return
        self.pending_layer=None
        if name.startswith('Original '):
            role='off' if name.endswith('OFF') else 'on'
            sources=self.record['sources'];identifier=sources.get(role+'_id')
            path=self.owner.project.resolve(self.owner.project.media(identifier)['path'] if identifier else sources[role])
        else:path=self.path/LAYERS[name]
        def done(image):
            if self.layers.currentText()==name:self.viewer.set_image(image)
        self.owner.start_job(lambda cancel,progress:read_image(path),done)

    def original_role(self):
        name=self.layers.currentText()
        if name=='Original OFF':return 'off'
        if name in ('Original ON','ON markers','Original ON annotated'):return 'on'
        return None

    def center_record(self,row,column=0):
        if not 0<=row<len(self.records):return
        rec=self.records[row];point=[rec['x_ref_px'],rec['y_ref_px']];role=self.original_role()
        if role:
            matrix=self.record['registrations'][role]['matrix']
            if matrix is None:return
            point=transform_points([point],np.linalg.inv(matrix))[0]
        self.viewer.set_zoom(2);self.viewer.centerOn(*point)
        self.details.setPlainText(json.dumps(rec,ensure_ascii=False,indent=2))

    def image_clicked(self,x,y):
        if not self.records:return
        role=self.original_role()
        if role:
            matrix=self.record['registrations'][role]['matrix']
            if matrix is None:return
            x,y=transform_points([[x,y]],matrix)[0]
        index=min(range(len(self.records)),key=lambda i:(self.records[i]['x_ref_px']-x)**2+(self.records[i]['y_ref_px']-y)**2)
        rec=self.records[index]
        if (rec['x_ref_px']-x)**2+(rec['y_ref_px']-y)**2>max(20,self.record['parameters']['roi_radius_px'])**2:return
        self.table.selectRow(index);self.center_record(index)

    def add_candidate(self):
        row=self.table.currentRow()
        if row<0:return
        rec=self.records[row]
        if rec.get('led_id') or rec['status']!='CANDIDATE':
            self.owner.error('Выберите неотклонённый UNKNOWN-кандидат');return
        document=self.owner.calibrator.document
        if not document or document.data['calibration_version']!=self.record['calibration_version']:
            self.owner.error('Карта изменилась после опыта. Повторите анализ с текущей картой');return
        self.owner.tabs.setCurrentWidget(self.owner.calibrator)
        self.owner.calibrator.add_at(rec['x_ref_px'],rec['y_ref_px'])
