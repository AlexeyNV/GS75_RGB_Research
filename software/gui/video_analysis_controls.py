"""Video -> Analyze; configuration and history in the existing research project."""
from dataclasses import asdict
from pathlib import Path
import uuid
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QComboBox,QLabel,
    QDoubleSpinBox,QSpinBox,QDialog,QFormLayout,QDialogButtonBox)
from .video_event_results import VideoEventResults
from software.vision.temporal_events import TemporalSettings,profile_settings
from software.vision.video_analysis import analyze_video,reaggregate_video
from software.vision.project_storage import image_hash


class VideoAnalysisControls(QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.settings=TemporalSettings();self.running=False;self.windows=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);row=QHBoxLayout()
        self.mode=QComboBox();self.mode.addItems(['KNOWN_LEDS','DISCOVER']);row.addWidget(self.mode)
        self.profile=QComboBox();self.profile.addItems(['Reliable / Long Pulse','Short Pulse / Experimental'])
        self.profile.currentIndexChanged.connect(lambda i:setattr(self,'settings',profile_settings(bool(i))));row.addWidget(self.profile)
        self.start=QDoubleSpinBox();self.start.setRange(0,86400);self.start.setSuffix(' с');row.addWidget(QLabel('Auto OFF от'));row.addWidget(self.start)
        self.duration=QDoubleSpinBox();self.duration.setRange(.2,60);self.duration.setValue(2);self.duration.setSuffix(' с');row.addWidget(self.duration)
        configure=QPushButton('Параметры времени');configure.clicked.connect(self.configure);row.addWidget(configure)
        self.run=QPushButton('Анализировать видео');self.run.clicked.connect(self.analyze);row.addWidget(self.run)
        layout.addLayout(row);row=QHBoxLayout();self.history=QComboBox();row.addWidget(self.history,1)
        reopen=QPushButton('Открыть видеоанализ');reopen.clicked.connect(self.open_history);row.addWidget(reopen);layout.addLayout(row)
        self.status=QLabel('Все кадры, PTS без пропусков. UNKNOWN сохраняется; профиль Short не гарантирует обнаружение 33 мс.')
        self.status.setWordWrap(True);layout.addWidget(self.status)

    def configure(self):
        dialog=QDialog(self);dialog.setWindowTitle('Temporal detector — секунды PTS и качество')
        form=QFormLayout(dialog);controls={};values=asdict(self.settings)
        for key,title,maximum in [('min_on_s','Подтверждение ON, с',10.),('min_off_s','Гистерезис потери цвета, с',10.),
                ('max_gap_s','Максимальный UNKNOWN-разрыв, с',10.),('min_samples','Минимум наблюдений',100),
                ('min_chroma','Цветной сигнал',255.),('min_brightness','Яркость нового сигнала',255.),
                ('min_color_confidence','Уверенность цвета',1.),('spatial_radius_px','DISCOVER: радиус, ref px',500.)]:
            control=QSpinBox() if key=='min_samples' else QDoubleSpinBox()
            control.setRange(1 if key=='min_samples' else (.001 if key=='max_gap_s' else 0),maximum)
            if key!='min_samples':control.setDecimals(3)
            control.setValue(values[key]);form.addRow(title,control);controls[key]=control
        info=QLabel('Надёжный OFF всегда разделяет события. Короткие UNKNOWN-разрывы сохраняются в отчёте.');info.setWordWrap(True);form.addRow(info)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec()==QDialog.Accepted:self.settings=TemporalSettings(profile=self.profile.currentText(),**{k:v.value() for k,v in controls.items()})

    def analyze(self,checked=False,session_path=None):
        if not self.owner.guard():return
        if not self.owner.video_path:self.owner.error('Сначала откройте MP4 во вкладке «Видео»');return
        if self.owner.calibrator.document and self.owner.calibrator.document.dirty:self.owner.error('Сначала сохраните карту');return
        self.owner.playing=False;self.owner.play_timer.stop()
        for window in self.windows:window.playing=False;window.timer.stop()
        project=self.owner.project;video=self.owner.video_path;settings=self.settings;mode=self.mode.currentText()
        start=self.start.value();duration=self.duration.value()
        output=project.resolve(project.data['reports_dir'])/('video_events_'+uuid.uuid4().hex)
        self.running=True;self.run.setEnabled(False);self.status.setText('Построение OFF, затем полный проход видео…')
        history=list(project.data.get('video_analyses',[]))
        def work(cancel,progress):
            import json
            data=project.checked_calibration()
            report=None
            for entry in reversed(history):
                source=project.resolve(entry['report'])
                if entry['status']!='COMPLETED' or not (source/'events.json').is_file():continue
                previous=json.loads((source/'events.json').read_text(encoding='utf-8'))
                off=previous.get('off') or {}
                if previous['mode']==mode and previous['calibration_version']==data['calibration_version'] and off.get('start_s')==start and off.get('duration_s')==duration and previous['source_sha256']==image_hash(video):
                    report=reaggregate_video(source,output,settings,cancel,progress,video=video);break
            if report is None:report=analyze_video(video,data,output,mode,settings,start,duration,cancel,progress)
            if session_path and report['status']=='COMPLETED':
                from software.vision.experiment_mapping import link_analysis
                from software.vision.project_storage import atomic_json
                try:link_analysis(output,session_path)
                except Exception as exc:
                    atomic_json(output/'correspondence_error.json',dict(session=str(session_path),error=str(exc)))
                    report['correspondence_error']=str(exc)
            return report
        def done(report):
            self.running=False;self.run.setEnabled(True)
            self.status.setText(f"{report['status']}; кадров {report['processed_frames']}; событий "
                f"{sum(e['status']=='CONFIRMED' for e in report['events'])}. {report.get('error','')} {report.get('correspondence_error','')}")
            project.data.setdefault('video_analyses',[]).append(dict(id=uuid.uuid4().hex,name=Path(video).name+' / '+mode,
                report=project.relative(output),status=report['status'],calibration_version=report['calibration_version'],
                experiment_session=project.relative(session_path) if session_path else None))
            project.save();self.refresh_history();self.open_results(output)
        if not self.owner.start_job(work,done):self.running=False;self.run.setEnabled(True)

    def progress_update(self,current,total,value):
        if not self.running or not isinstance(value,dict):return
        if value.get('name')=='VIDEO_ANALYSIS':
            counts=value.get('frame_states',value['states']);eta=value.get('eta_s')
            self.status.setText(f"Кадр {value['frame']} / {total}; PTS {value['pts_s']:.3f} с; обработано {current}; "
                f"UNCERTAIN {counts.get('UNCERTAIN',0)}, INVALID {counts.get('INVALID_GEOMETRY',0)}, "
                f"NO_COVERAGE {counts.get('NO_COVERAGE',0)}; подтверждено {value['confirmed_events']}; "
                +(f'ещё ≈{eta:.1f} с' if eta is not None else 'ETA неизвестно'))
        elif value.get('name')=='OFF':self.status.setText('OFF: '+value['state']+'; события ещё не анализировались.')
        elif value.get('name')=='TEMPORAL_REUSE':self.status.setText(f'Пересчёт {current}/{total} по сохранённым наблюдениям, без OpenCV.')

    def operation_failed(self,message):
        if self.running:self.running=False;self.run.setEnabled(True);self.status.setText(message)

    def refresh_history(self):
        self.history.clear()
        if self.owner.project:
            for row in self.owner.project.data.get('video_analyses',[]):self.history.addItem(row['name']+' / '+row['status'],row['report'])

    def open_history(self):
        if self.owner.guard() and self.history.currentData():self.open_results(self.owner.project.resolve(self.history.currentData()))

    def open_results(self,path):
        self.windows=[w for w in self.windows if not w.closed]
        window=VideoEventResults(self.owner,path);self.windows.append(window);window.show()

    def close_results(self):
        for window in self.windows:window.close()
