"""No-console video benchmark and automatic OFF controls in the existing application."""
from pathlib import Path
import shutil
import time
import uuid
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,
    QFileDialog,QSpinBox,QDoubleSpinBox,QComboBox,QTableWidget,QTableWidgetItem,QPlainTextEdit,QCheckBox)
from software.vision.off_background import build_off,update_off,from_photo
from software.vision.project_storage import read_image,atomic_json
from software.vision.pts_video import SequentialVideoReader
from software.vision.video_benchmark import benchmark,plot_report,export_report


class PerformancePane(QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.video=None;self.off=None;self.off_key=None
        self.report=None;self.output=None;self.gui_ms=0.
        layout=QVBoxLayout(self);row=QHBoxLayout()
        self.choose=QPushButton('Выбрать MP4');self.choose.clicked.connect(self.choose_video);row.addWidget(self.choose)
        self.run=QPushButton('Измерить производительность');self.run.clicked.connect(self.measure);row.addWidget(self.run)
        self.build=QPushButton('Построить OFF');self.build.clicked.connect(self.build_model);row.addWidget(self.build)
        self.update=QPushButton('Обновить OFF в гарантированном интервале');self.update.clicked.connect(self.update_model);row.addWidget(self.update)
        self.export=QPushButton('Экспорт JSON / CSV / Markdown');self.export.clicked.connect(self.export_results);row.addWidget(self.export);layout.addLayout(row)
        self.info=QLabel('Выберите видео. Начальный интервал должен содержать только OFF.');self.info.setWordWrap(True);layout.addWidget(self.info)
        form=QFormLayout();self.start=QDoubleSpinBox();self.start.setRange(0,86400);self.start.setSuffix(' с')
        self.duration=QDoubleSpinBox();self.duration.setRange(.2,60);self.duration.setValue(2);self.duration.setSuffix(' с')
        self.frames=QSpinBox();self.frames.setRange(0,1000000);self.frames.setValue(120);self.frames.setSpecialValueText('Всё видео')
        self.warmup=QSpinBox();self.warmup.setRange(0,30);self.warmup.setValue(3)
        self.source=QComboBox();self.source.addItems(['Автоматический OFF из интервала','Назначенное OFF-фото проекта'])
        self.guarantee=QCheckBox('Подтверждаю: интервал обновления гарантированно OFF')
        form.addRow('Источник OFF',self.source);form.addRow('Начало OFF',self.start);form.addRow('Длительность OFF',self.duration)
        form.addRow('Измеренных кадров (0 = всё видео)',self.frames);form.addRow('Отдельный прогрев, кадров',self.warmup)
        form.addRow(self.guarantee);layout.addLayout(form)
        self.summary=QLabel('Короткий тест не доказывает устойчивую работу в реальном времени.');self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.summary.setMinimumHeight(90)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Вариант / стадия','Mean ms','P50','P95','P99','Max','FPS','Качество / RSS'])
        self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        self.table.setColumnWidth(0,350);self.table.setMaximumHeight(190)
        self.graph=QLabel();self.graph.setAlignment(Qt.AlignCenter);self.graph.setFixedHeight(180);layout.addWidget(self.graph)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(100);layout.addWidget(self.details)

    def choose_video(self):
        if not self.owner.guard():return
        path,_=QFileDialog.getOpenFileName(self,'Видео для измерений','','Video (*.mp4 *.mov *.avi)')
        if path:self.select_video(path)

    def select_video(self,path):
        self.video=Path(path);self.off=None;self.off_key=None
        def work(cancel,progress):
            reader=SequentialVideoReader()
            try:return reader.open(path)
            finally:reader.close()
        def done(meta):self.info.setText(f"{path}\n{meta['width']}×{meta['height']}, FPS={meta['fps']}, длительность={meta['duration_s']} с, PyAV PTS")
        self.owner.start_job(work,done)

    def key(self):
        p=self.owner.project
        return (str(self.video),self.start.value(),self.duration.value(),(p.data.get('calibration') or {}).get('version'))

    def build_model(self):
        if not self.owner.guard() or not self.video:return
        key=self.key();project=self.owner.project;video=self.video;start=self.start.value();duration=self.duration.value()
        def work(cancel,progress):
            data=project.checked_calibration()
            return build_off(video,data,cancel,start,duration,notify=progress)
        def done(off):
            self.off=off;self.off_key=key
            self.summary.setText(f"OFF: принято {off.metadata['retained_frames']}, маска {off.metadata['valid_fraction']:.1%}; отклонено {len(off.metadata['rejected'])}")
        self.owner.start_job(work,done)

    def update_model(self):
        if not self.owner.guard() or not self.video:return
        if self.off is None:self.owner.error('Сначала постройте OFF');return
        if not self.guarantee.isChecked():self.owner.error('Подтвердите гарантированный OFF-интервал для обновления');return
        active=False
        if self.report:
            for run in self.report['runs']:
                if run['frames']:active|=any(r['status'] in ('ON','CANDIDATE') for r in run['frames'][-1]['records'])
        if active:self.owner.error('Обновление OFF запрещено: последнее измерение содержит подтверждённое свечение');return
        project=self.owner.project;start=self.start.value();duration=self.duration.value();key=self.key();video=self.video
        def work(cancel,progress):return update_off(self.off,build_off(video,project.checked_calibration(),cancel,start,duration,notify=progress),True,active)
        def done(value):self.off=value;self.off_key=key;self.summary.setText('OFF обновлён только на общей достоверной маске')
        self.owner.start_job(work,done)

    def measure(self):
        if not self.owner.guard() or not self.video:return
        if self.owner.calibrator.document and self.owner.calibrator.document.dirty:
            self.owner.error('Сначала сохраните карту');return
        project=self.owner.project;video=self.video;key=self.key();off=self.off if key==self.off_key else None
        start=self.start.value();duration=self.duration.value();limit=self.frames.value();warmup=self.warmup.value()
        mode=self.owner.analysis_mode.currentText();explicit=self.source.currentIndex()==1
        output=project.resolve(project.data['reports_dir'])/('benchmark_'+uuid.uuid4().hex)
        self.gui_ms=0.
        def work(cancel,progress):
            data=project.checked_calibration();model=off
            if explicit:
                photos=[m for m in project.data['media'] if m['role']=='OFF' and m['kind']=='photo']
                if len(photos)!=1:raise ValueError('Назначьте одно OFF-фото проекта')
                model=from_photo(read_image(project.resolve(photos[0]['path'])),data)
            report=benchmark(video,data,output,cancel,limit=limit,warmup=warmup,off=model,
                start_s=start,duration_s=duration,mode=mode,notify=progress,gui_open=True)
            plot_report(report,output/'frame_times.png');export_report(report,output)
            return report,str(output)
        def done(value):
            started=time.perf_counter_ns();self.report,path=value;self.output=Path(path);self.show_report()
            self.gui_ms+=(time.perf_counter_ns()-started)/1e6
            self.report['separate_costs_ms']['GUI_UPDATE']=self.gui_ms
            atomic_json(self.output/'benchmark.json',self.report)
        self.owner.start_job(work,done)

    def progress_update(self,current,total,value):
        if not isinstance(value,dict) or 'benchmark_frame_ms' not in value:return
        started=time.perf_counter_ns()
        self.summary.setText(f"{value['variant']}: кадр {current}/{total}, {value['benchmark_frame_ms']:.2f} мс. Все кадры декодируются последовательно.")
        self.gui_ms+=(time.perf_counter_ns()-started)/1e6

    def show_report(self):
        report=self.report;self.table.setRowCount(0)
        for run in report['runs']:
            for name,stat in [('TOTAL',run['end_to_end'])]+list(run['stages'].items()):
                row=self.table.rowCount();self.table.insertRow(row)
                quality=report['quality'][run['variant']]['verdict']
                values=[run['variant']+' / '+name]+[f"{stat[k]:.3f}" if stat[k] is not None else '—' for k in ('mean_ms','p50_ms','p95_ms','p99_ms','max_ms','fps')]+[quality+f" / {(run['peak_observed_rss_bytes'] or 0)/2**20:.1f} MiB"]
                for col,text in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(text))
        self.graph.setPixmap(QPixmap(str(self.output/'frame_times.png')).scaled(1100,180,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        summaries=[]
        for run in report['runs']:
            fits=[rate for rate,v in run['budgets'].items() if v['p95_fits']]
            summaries.append(f"{run['variant']}: {run['wall_fps']:.1f} FPS сквозных; CPU {run['cpu_machine_percent']:.1f}% ПК; узкое место {run['slowest_stage']}; бюджеты {', '.join(fits) or 'не выдержаны'} FPS")
        self.summary.setText('\n'.join(summaries)+'\nЭто короткий офлайн-тест, не гарантия realtime.')
        import json
        self.details.setPlainText(json.dumps(dict(machine=report['machine'],off=report['off'],quality=report['quality']),indent=2,ensure_ascii=False))

    def export_results(self):
        if not self.owner.guard() or self.report is None:return
        folder=QFileDialog.getExistingDirectory(self,'Каталог экспорта benchmark')
        if not folder:return
        target=Path(folder)/self.output.name
        def work(cancel,progress):
            if target.exists():raise FileExistsError('Экспорт уже существует: выберите другой каталог')
            shutil.copytree(self.output,target);export_report(self.report,target);return str(target)
        self.owner.start_job(work,lambda path:self.owner.log('Benchmark экспортирован: '+path))
