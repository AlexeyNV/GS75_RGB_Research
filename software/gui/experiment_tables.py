"""Read-only CSV snapshots available from the event timeline, without a shell."""
import csv
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QTableWidget,QTableWidgetItem,QPushButton,QLabel


TABLES = [('electrical_operations.csv','STM32 — операции'),('optical_events.csv','Оптика — события'),
          ('electrical_optical_mapping.csv','Соответствия'),('short_pulse_summary.csv','Короткие импульсы')]


class ExperimentTables(QDialog):
    def __init__(self,parent,path):
        super().__init__(parent);self.path=Path(path);self.setWindowTitle('Электрические и оптические результаты');self.resize(1400,650)
        layout=QVBoxLayout(self)
        label=QLabel('STM32 и оптика разделены. VERIFIED требует решения оператора. Пустые значения неизвестны; маркер исключён из short summary.')
        label.setWordWrap(True);layout.addWidget(label);self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.tables=[]
        for name,title in TABLES:
            with (self.path/name).open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
            priority={
                'electrical_optical_mapping.csv':['operation_id','source_kp','sink_kp','requested_duration_ms','current_avg_ua',
                    'optical_event_id','optical_track_id','pcb_led_id','color','optical_start_pts','optical_end_pts','mapping_status'],
                'electrical_operations.csv':['operation_id','role','source_kp','sink_kp','requested_duration_ms','measured_duration_ms',
                    'current_avg_ua','current_max_ua','adc_samples','fault','electrical_status'],
                'optical_events.csv':['event_id','entity','led_id','color','start_pts','end_pts','duration_s','status','confidence','coverage'],
                'short_pulse_summary.csv':['requested_duration_ms','requested','completed','detected_operations','confirmed','candidate','missed','unobservable','unaligned']}
            original=rows[0];headers=[key for key in priority[name] if key in original]
            headers += [key for key in original if key not in headers]
            table=QTableWidget(max(0,len(rows)-1),len(headers));table.setHorizontalHeaderLabels(headers)
            table.horizontalHeader().setSectionsMovable(True)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            for row,values in enumerate(rows[1:]):
                for col,key in enumerate(headers):table.setItem(row,col,QTableWidgetItem(values[original.index(key)]))
            self.tabs.addTab(table,title);self.tables.append(table)
        row=QHBoxLayout();button=QPushButton('Открыть CSV');button.clicked.connect(self.open_csv);row.addWidget(button)
        button=QPushButton('Открыть папку таблиц');button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.resolve()))));row.addWidget(button)
        layout.addLayout(row)

    def open_csv(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str((self.path/TABLES[self.tabs.currentIndex()][0]).resolve())))
