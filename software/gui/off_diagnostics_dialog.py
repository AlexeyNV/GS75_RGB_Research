"""OFF evidence viewer for successful, failed and cancelled searches."""
import json
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QComboBox,QPushButton
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from .image_viewer import ImageViewer
from software.vision.project_storage import read_image


class OffDiagnosticsDialog(QDialog):
    def __init__(self,path,parent=None):
        super().__init__(parent);self.path=Path(path);self.resize(1150,850);self.setWindowTitle('Диагностика Automatic OFF')
        data=json.loads((self.path/'off_diagnostics.json').read_text(encoding='utf-8'));self.data=data;self.row=None
        layout=QVBoxLayout(self)
        folder=QPushButton('Открыть каталог диагностических файлов')
        folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.resolve()))));layout.addWidget(folder)
        info=QLabel(f"{data['status']}; выбрано {data.get('retained_frames',0)} / кандидатов {len(data['candidates'])}\n"
            +json.dumps(data.get('coverage',{}),ensure_ascii=False));info.setWordWrap(True);layout.addWidget(info)
        self.table=QTableWidget(len(data['candidates']),8)
        self.table.setHorizontalHeaderLabels(['Кадр','PTS мс','Причина','Выбран','RMSE','Raw >40','Stable >40','Smooth >40'])
        self.table.setMaximumHeight(230);self.table.setColumnWidth(2,320);layout.addWidget(self.table)
        for row,item in enumerate(data['candidates']):
            values=[item['frame_index'],item.get('timestamp_ms'),item['reason'],item['selected'],item.get('rmse_px'),
                item.get('changed_fraction'),item.get('stable_changed_fraction'),item.get('smooth_changed_fraction')]
            for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(f'{value:.5f}' if isinstance(value,float) else str(value)))
        self.layers=QComboBox();self.layers.addItems(['Карта покрытия','Исходный кадр','ArUco','Warp','Маска регистрации',
            'Общая область','До компенсации','Остаток','Сглаженный остаток','Изменения >40','Цветные области'])
        layout.addWidget(self.layers);self.viewer=ImageViewer();layout.addWidget(self.viewer,1)
        self.table.cellClicked.connect(self.select_row);self.layers.currentIndexChanged.connect(self.show_layer)
        self.show_layer()

    def select_row(self,row,column):
        self.row=self.data['candidates'][row]
        if self.layers.currentIndex()==0:self.layers.setCurrentIndex(2)
        else:self.show_layer()

    def show_layer(self,*args):
        index=self.layers.currentIndex()
        if index==0:path=self.path/'off_coverage.png'
        elif self.row is None:return
        else:
            stem=f"frame_{self.row['frame_index']:04d}"
            if index==1:
                group='accepted_frames' if self.row['reason']=='ELIGIBLE' else 'rejected_frames'
                path=self.path/group/(stem+'.jpg')
            elif index<=4:path=self.path/'registration_diagnostics'/stem/['markers.jpg','warped.jpg','valid_mask.png'][index-2]
            else:path=self.path/'residual_heatmaps'/stem/['common','before','residual','smooth_residual','changed','suspicious_color'][index-5]
        if path.is_file():self.viewer.set_image(read_image(path))
