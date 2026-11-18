"""Video event player, immutable algorithm output and separate operator review."""
import json
import csv
from pathlib import Path
import re
import shutil
import uuid
from collections import Counter
import numpy as np
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
    QTableWidget,QTableWidgetItem,QSlider,QScrollBar,QFileDialog,QInputDialog,QSplitter,QPlainTextEdit)
from .image_viewer import ImageViewer
from .event_timeline import EventTimeline
from .experiment_tables import ExperimentTables
from software.vision.video_source import VideoReader
from software.vision.project_storage import read_image,atomic_json,image_hash
from software.vision.video_event_replay import replay_layer
from software.vision.video_event_export import load_decisions,save_decision
from software.vision.event_alignment import align_session
from software.vision.experiment_mapping import link_analysis,validate_bundle,analysis_signature,save_association
from software.vision.image_registration import transform_points


class VideoEventResults(QDialog):
    def __init__(self,owner,path):
        super().__init__(owner);self.owner=owner;self.path=Path(path);self.closed=self.closing=self.loading=False
        self.report=json.loads((self.path/'events.json').read_text(encoding='utf-8'))
        self.report_hash=image_hash(self.path/'events.json')
        self.calibration=json.loads((self.path/'calibration_snapshot.json').read_text(encoding='utf-8'))
        self.frames=[json.loads(line) for line in (self.path/'frame_results.jsonl').read_text(encoding='utf-8').splitlines()][:self.report['processed_frames']]
        self.events=self.report['events'];self.tracks=self.report.get('unknown_tracks',[])
        self.decoder=VideoReader();self.video_path=Path(self.report['source']);self.current_index=0;self.requested_index=0;self.pending=None
        if (self.path/'media_link.json').is_file():self.video_path=Path(json.loads((self.path/'media_link.json').read_text(encoding='utf-8'))['path'])
        self.off_image=self.off_mask=None;self.position=None;self.target=None;self.playing=False
        self.correspondence=None;self.correspondence_path=None;self.table_windows=[];self.snapshot_error='';self.operations=[]
        self.load_correspondence()
        self.setWindowTitle('RGB Vision — события видео / независимые наблюдения');self.resize(1400,1020)
        layout=QVBoxLayout(self)
        self.summary=QLabel()
        self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.timeline=EventTimeline();self.timeline.set_report(self.report);self.timeline.seek.connect(self.seek_pts);layout.addWidget(self.timeline)
        self.timeline.set_timestamps([f['timestamp_ms']/1000 for f in self.frames if f.get('timestamp_ms') is not None])
        self.timeline.set_electrical(self.operations,(self.correspondence or {}).get('alignment'))
        self.timeline.operation_selected.connect(self.select_operation)
        row=QHBoxLayout()
        for title,callback in [('Шкала +',lambda:self.timeline.zoom(2)),('Шкала −',lambda:self.timeline.zoom(.5)),('Вся запись',self.timeline.reset_view)]:
            button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        self.timeline_range=QLabel();row.addWidget(self.timeline_range)
        self.pan=QScrollBar(Qt.Horizontal);self.pan.setRange(0,10000);self.pan.valueChanged.connect(lambda value:self.timeline.pan(value/10000));row.addWidget(self.pan,1)
        self.timeline.view_changed.connect(self.timeline_view_changed);layout.addLayout(row)
        row=QHBoxLayout();self.operation_choice=QComboBox();row.addWidget(self.operation_choice,1)
        self.operation_choice.activated.connect(lambda _:self.select_operation(self.operation_choice.currentData()))
        for title,callback in [('К операции',lambda:self.select_operation(self.operation_choice.currentData())),
            ('Связать событие с операцией вручную',self.manual_link),('Снять ручную связь',lambda:self.manual_link(reset=True))]:
            button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        layout.addLayout(row);self.update_operations()
        row=QHBoxLayout()
        for title,callback in [('▶ / ❚❚',self.play_pause),('ROI крупнее',self.zoom_roi),('Экспорт отчёта',self.export),
            ('Связать session.json',self.link_session),('Таблицы соответствий',self.show_tables),
            ('Обновить соответствия',self.refresh_correspondence),('Найти перемещённое видео',self.relink_video)]:
            button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        self.layers=QComboBox();self.layers.addItems(['Original','Geometry','Registered','Coverage','Difference','ROI'])
        self.layers.currentTextChanged.connect(lambda _:self.request_frame(self.requested_index));row.addWidget(self.layers);layout.addLayout(row)
        self.viewer=ImageViewer();layout.addWidget(self.viewer,1)
        self.slider=QSlider(Qt.Horizontal);self.slider.setRange(0,max(0,len(self.frames)-1));self.slider.sliderReleased.connect(lambda:self.request_frame(self.slider.value()));layout.addWidget(self.slider)
        self.frame_info=QLabel('PTS кадров сохранены; длительность события — наблюдаемый span, не точный физический импульс.');layout.addWidget(self.frame_info)
        self.filter=QComboBox();self.filter.addItems(['CONFIRMED','Все','CANDIDATE','REJECTED']);self.filter.currentTextChanged.connect(self.refresh_tables);layout.addWidget(self.filter)
        tables=QSplitter(Qt.Horizontal)
        self.event_table=QTableWidget(0,9);self.event_table.setHorizontalHeaderLabels(['Источник','Цвет','Start PTS','End PTS','Span, с','Алгоритм','Оператор','Уверенность','Флаги'])
        self.event_table.horizontalHeader().setStretchLastSection(True)
        self.event_table.cellClicked.connect(self.select_event);tables.addWidget(self.event_table)
        self.track_table=QTableWidget(0,5);self.track_table.setHorizontalHeaderLabels(['Оптический трек','X / Y','Алгоритм','Оператор','PCB ID вручную'])
        self.track_table.setVisible(bool(self.tracks));self.track_table.horizontalHeader().setStretchLastSection(True)
        self.track_table.cellClicked.connect(self.select_track);tables.addWidget(self.track_table);layout.addWidget(tables)
        tables.setMaximumHeight(190)
        row=QHBoxLayout()
        for title,callback in [('Подтвердить',lambda:self.review('ACCEPTED')),('Отклонить',lambda:self.review('REJECTED')),
            ('Сбросить решение',lambda:self.review('RESET')),('PCB ID вручную',self.identify),('Добавить позицию в карту',self.add_to_map)]:
            button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        layout.addLayout(row)
        self.details=QPlainTextEdit('Штриховка — UNKNOWN; тёмно-серый OFF — только надёжные OFF-наблюдения. Track ID не является PCB LED ID.')
        self.details.setReadOnly(True);self.details.setMaximumHeight(115);layout.addWidget(self.details)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.advance)
        if self.correspondence:self.filter.setCurrentText('Все')
        self.refresh_tables()
        self.timeline_view_changed(self.timeline.view_start,self.timeline.view_end)
        if self.frames and self.report['status']=='COMPLETED':QTimer.singleShot(0,lambda:self.request_frame(0))

    def refresh_tables(self,*args):
        decisions=load_decisions(self.path);selected=self.filter.currentText()
        self.shown_events=[e for e in self.events if selected=='Все' or e['status']==selected]
        self.event_table.setRowCount(len(self.shown_events))
        for row,e in enumerate(self.shown_events):
            operator=decisions.get(e['event_id'],{}).get('decision','—')
            values=[e['entity'],e['color'],f"{e['start_pts']:.3f}",f"{e['end_pts']:.3f}",f"{e['duration_s']:.3f}",e['status'],operator,f"{e['confidence']:.2f}",', '.join(e['uncertainty_flags'])]
            for col,value in enumerate(values):self.event_table.setItem(row,col,QTableWidgetItem(value))
        self.track_table.setRowCount(len(self.tracks))
        for row,t in enumerate(self.tracks):
            manual=decisions.get(t['track_id'],{})
            values=[t['track_id'],f"{t['x_ref_px']:.1f} / {t['y_ref_px']:.1f}",t['status'],manual.get('decision','—'),manual.get('pcb_led_id') or '']
            for col,value in enumerate(values):self.track_table.setItem(row,col,QTableWidgetItem(value))
        self.update_summary()

    def update_summary(self):
        counts=Counter(e['status'] for e in self.events);shown=Counter(e['status'] for e in getattr(self,'shown_events',[]))
        self.summary.setText(f"{self.report['status']} | run {self.report.get('analysis_id',self.path.name)} | алгоритм {self.report['algorithm_version']} | "
            f"{self.report['settings']['profile']} | кадров {self.report['processed_frames']}\n"
            f"ВСЕ события {len(self.events)}: CONFIRMED={counts['CONFIRMED']}, CANDIDATE={counts['CANDIDATE']}, REJECTED={counts['REJECTED']}; "
            f"показано {sum(shown.values())} ({dict(shown)}); UNKNOWN-интервалов {len(self.report.get('uncertainty_intervals',[]))}. {self.snapshot_error}")

    def timeline_view_changed(self,start,end):
        self.timeline_range.setText(f'PTS {start:.3f}–{end:.3f} с')
        self.pan.blockSignals(True);self.pan.setValue(round(start/max(1e-9,self.timeline.extent()-(end-start))*10000));self.pan.blockSignals(False)

    def update_operations(self):
        if not hasattr(self,'operation_choice'):return
        current=self.operation_choice.currentData();self.operation_choice.blockSignals(True);self.operation_choice.clear()
        for operation in self.operations:self.operation_choice.addItem(
            f"ID {operation['operation_id']} | KP{operation['source_kp']}→KP{operation['sink_kp']} | {operation['requested_duration_ms']} мс",operation['operation_key'])
        index=self.operation_choice.findData(current)
        if index>=0:self.operation_choice.setCurrentIndex(index)
        self.operation_choice.blockSignals(False)

    def select_operation(self,key):
        operation=next((o for o in self.operations if o['operation_key']==key),None)
        if operation is None:return
        self.playing=False;self.timer.stop()
        self.target=None;self.position=None
        matches=[r for r in self.correspondence['mapping'] if r['operation_key']==key and r['optical_event_id']]
        ids={r['optical_event_id'] for r in matches};self.timeline.selected_event_ids=ids
        self.operation_choice.setCurrentIndex(self.operation_choice.findData(key));self.filter.setCurrentText('Все')
        lines=[f"STM32 ID={operation['operation_id']} KP{operation['source_kp']}→KP{operation['sink_kp']}; "
            f"запрос/elapsed={operation['requested_duration_ms']}/{operation['measured_duration_ms']} мс; "
            f"AVG/MAX={operation['current_avg_ua']}/{operation['current_max_ua']} мкА; {operation['electrical_status']}"]
        selected=[e for e in self.events if e['event_id'] in ids]
        for e in selected:lines.append(f"ОПТИКА {e['event_id']}: {e['status']}; PTS {e['start_pts']:.6f}–{e['end_pts']:.6f}; "
            f"фрагментов {len(e.get('observation_fragments',[])) or 1}; confidence={e['confidence']:.3f}; "+', '.join(e['uncertainty_flags']))
        for e in selected:
            for fragment in e.get('observation_fragments',[]):lines.append(
                f"{fragment['fragment_id']}: кадры {fragment['start_frame']}–{fragment['end_frame']}, PTS {fragment['start_pts']:.6f}–{fragment['end_pts']:.6f}")
        if not selected:lines.append('Нет однозначно связанных оптических событий; см. причины в таблицах соответствий.')
        lines.append('События/фрагменты не доказывают непрерывное свечение через UNKNOWN. Электрическая дорожка — USB/video оценка.')
        self.details.setPlainText('\n'.join(lines));offset=self.correspondence['alignment']['offset_s']
        if offset is not None and operation.get('host_ack_s') is not None:
            start=operation['host_ack_s']-offset;self.timeline.focus_interval(start,start+operation['requested_duration_ms']/1000)
            lower=(operation.get('host_tx_s') or operation['host_ack_s'])-offset
            upper=(operation.get('host_done_s') or operation['host_ack_s']+operation['requested_duration_ms']/1000)-offset
            for frame in self.frames:
                if not lower<=frame['timestamp_ms']/1000<=upper:continue
                records=frame['result']['records'];geometry=frame['result']['registrations']['on']
                record=next((r for r in records if r.get('led_id')==operation.get('pcb_led_id')),None)
                if geometry['status']!='REGISTERED' or record and record.get('roi_coverage',0)<.9:
                    lines.append(f"Кадр {frame['frame_index']}: H={geometry['status']}, ROI={record.get('roi_coverage') if record else None}; "
                        +', '.join(record.get('rejection_reasons',[]) if record else [geometry.get('reason','Geometry unavailable')]))
        self.details.setPlainText('\n'.join(lines))
        if selected:
            e=selected[0];self.target=e['event_id'];self.position=(e['x_ref_px'],e['y_ref_px']);self.request_frame(e['start_frame'])
        elif offset is not None and operation.get('host_ack_s') is not None:self.seek_pts(operation['host_ack_s']-offset)
        self.event_table.clearSelection()
        first_item=None
        for row,e in enumerate(self.shown_events):
            if e['event_id'] in ids:
                if first_item is None:first_item=self.event_table.item(row,0)
                for col in range(self.event_table.columnCount()):self.event_table.item(row,col).setSelected(True)
        if first_item:self.event_table.scrollToItem(first_item)
        self.timeline.update()

    def manual_link(self,reset=False):
        if self.target not in {e['event_id'] for e in self.events} or not self.operations:
            self.owner.error('Выберите оптическое событие и связанный журнал');return
        if reset:save_association(self.path,None,self.target,'RESET')
        else:
            labels=[f"{o['operation_key']}: ID {o['operation_id']} KP{o['source_kp']}→KP{o['sink_kp']} {o['requested_duration_ms']} мс" for o in self.operations]
            label,ok=QInputDialog.getItem(self,'Ручное соответствие — не калибровка часов','Выберите операцию для '+self.target,labels,0,False)
            if not ok:return
            save_association(self.path,self.operations[labels.index(label)]['operation_key'],self.target,'ACCEPTED','Explicit operator association; optical status/confidence unchanged')
        self.refresh_correspondence()

    def select_event(self,row,column=0):
        if not 0<=row<len(self.shown_events):return
        event=self.shown_events[row];self.target=event['event_id'];self.position=(event['x_ref_px'],event['y_ref_px'])
        self.details.setPlainText(self.event_details(event));self.playing=False;self.timer.stop();self.request_frame(event['start_frame'])

    def select_track(self,row,column=0):
        if not 0<=row<len(self.tracks):return
        track=self.tracks[row];self.target=track['track_id'];self.position=(track['x_ref_px'],track['y_ref_px'])
        self.details.setPlainText(json.dumps(track,ensure_ascii=False));self.playing=False;self.timer.stop();self.request_frame(track['start_frame'])

    def request_frame(self,index):
        if self.closing or not self.frames:return
        index=max(0,min(len(self.frames)-1,int(index)))
        self.requested_index=index
        if self.owner.active_job:
            self.pending=index;QTimer.singleShot(20,self.drain);return
        if not self.video_path.is_file():self.frame_info.setText('Видео не найдено. Выберите «Найти перемещённое видео».');return
        layer=self.layers.currentText();position=self.position;off=self.off_image;mask=self.off_mask
        self.loading=True
        def work(cancel,progress):
            if self.decoder.capture is None or self.decoder.path!=self.video_path:self.decoder.open(self.video_path)
            image,info=self.decoder.frame(index);actual=info['frame_index'];actual=min(actual,len(self.frames)-1)
            model=off if off is not None else read_image(self.path/'off_model/off.png')
            valid=mask if mask is not None else read_image(self.path/'off_model/valid_mask.png')[:,:,0]
            warning=''
            try:shown=replay_layer(image,self.frames[actual],self.calibration,model,valid,layer,position)
            except ValueError as exc:shown=image;warning=str(exc)
            return shown,info,model,valid,warning
        def done(value):
            self.loading=False
            if self.closing:return
            shown,info,self.off_image,self.off_mask,warning=value
            self.current_index=min(info['frame_index'],len(self.frames)-1);frame=self.frames[self.current_index]
            self.viewer.set_image(shown);self.slider.setValue(self.current_index)
            self.timeline.cursor=frame['timestamp_ms']/1000;self.timeline.update()
            self.frame_info.setText(f"Кадр {self.current_index}; analysis PTS={frame['timestamp_ms']/1000:.6f} с; геометрия "
                f"{frame['result']['registration_status']}. {warning}")
            records=frame['result']['records']
            if records:
                record=min(records,key=lambda r:np.hypot(r.get('x_ref_px',0)-self.position[0],r.get('y_ref_px',0)-self.position[1])) if self.position else records[0]
                local='INVALID_GEOMETRY' if record.get('roi_coverage',0)<.9 else record['status']
                self.frame_info.setText(self.frame_info.text()+f" ROI={record.get('roi_coverage')}; local={local}; "
                    f"chroma={record.get('chroma')}; confidence={record.get('color_confidence')}. "+', '.join(record.get('rejection_reasons',[])))
            if self.position:self.zoom_roi()
            if self.playing:self.schedule_next()
        if not self.owner.start_job(work,done):self.loading=False

    def drain(self):
        if self.pending is not None and not self.closing:
            index=self.pending;self.pending=None;self.request_frame(index)

    def seek_pts(self,pts):
        if self.frames:self.playing=False;self.timer.stop();self.request_frame(min(range(len(self.frames)),key=lambda i:abs(self.frames[i]['timestamp_ms']/1000-pts)))

    def play_pause(self):
        self.playing=not self.playing
        if self.playing:self.schedule_next()
        else:self.timer.stop()

    def schedule_next(self):
        if self.current_index+1>=len(self.frames):self.playing=False;return
        delay=self.frames[self.current_index+1]['timestamp_ms']-self.frames[self.current_index]['timestamp_ms']
        self.timer.start(max(5,round(delay)))

    def advance(self):
        if self.playing:self.request_frame(self.current_index+1)

    def zoom_roi(self):
        if not self.position or not self.frames:return
        point=self.position;layer=self.layers.currentText()
        matrix=self.frames[self.current_index]['result']['registrations']['on'].get('matrix')
        if layer in ('Original','Geometry'):
            if matrix is None:return
            point=transform_points([point],np.linalg.inv(matrix))[0]
        elif layer=='ROI':point=(100,100)
        self.viewer.set_zoom(3);self.viewer.centerOn(*point)

    def review(self,decision):
        if self.target is None:self.owner.error('Выберите событие или трек');return
        note,ok=QInputDialog.getText(self,'Решение оператора','Комментарий (не изменяет автоматический результат)')
        if ok:
            save_decision(self.path,self.target,decision,note);self.refresh_tables();self.refresh_correspondence()

    def identify(self):
        if self.target not in {t['track_id'] for t in self.tracks}:self.owner.error('Выберите неизвестный оптический трек');return
        value,ok=QInputDialog.getText(self,'PCB ID — только вручную','Введите LED ID по проверенной шелкографии, например LED<number>')
        if not ok:return
        if not re.fullmatch(r'LED\d+',value.strip()):self.owner.error('Нужен LED ID по шелкографии, без автоматического номера трека');return
        save_decision(self.path,self.target,'ACCEPTED','PCB identity explicitly entered by operator',value.strip());self.refresh_tables();self.refresh_correspondence()

    def add_to_map(self):
        if self.position is None or self.target not in {t['track_id'] for t in self.tracks}:self.owner.error('Выберите оптический трек');return
        document=self.owner.calibrator.document
        if not document or document.data['reference']['sha256']!=self.calibration['reference']['sha256'] or document.data['markers']!=self.calibration['markers']:
            self.owner.error('Координатная основа карты изменилась. Повторите анализ.');return
        track=next(t for t in self.tracks if t['track_id']==self.target)
        if track['status']!='CONFIRMED' and load_decisions(self.path).get(self.target,{}).get('decision')!='ACCEPTED':
            self.owner.error('Сначала проверьте и подтвердите слабый кандидат');return
        self.owner.tabs.setCurrentWidget(self.owner.calibrator);self.owner.calibrator.add_at(*self.position,suggest_id=False)

    def link_session(self):
        path,_=QFileDialog.getOpenFileName(self,'Журнал независимого эксперимента','','Session (session.json)')
        if not path:return
        def work(cancel,progress):
            return link_analysis(self.path,path)
        def done(value):
            self.load_correspondence();a=value['alignment']
            self.details.setPlainText(f"{a['status']}; offset={a['offset_s']}; uncertainty={a['uncertainty_s']}. Это не аппаратная синхронизация. Таблицы соответствий готовы.")
        self.owner.start_job(work,done)

    def load_correspondence(self):
        link=self.path/'correspondence_link.json'
        if link.is_file():
            path=self.path/json.loads(link.read_text(encoding='utf-8'))['directory'];validation=validate_bundle(path,self.report)
            if not validation['valid']:
                self.snapshot_error='CSV другого снимка: '+validation['reason'];self.correspondence_path=self.correspondence=None;self.operations=[]
            else:
                self.snapshot_error='';self.correspondence_path=path
                self.correspondence=json.loads((path/'experiment_mapping.json').read_text(encoding='utf-8'))
                self.operations=self.correspondence.get('electrical_operations',[])
                if not self.operations:
                    with (path/'electrical_operations.csv').open(encoding='utf-8-sig',newline='') as stream:self.operations=list(csv.DictReader(stream))
                    for operation in self.operations:
                        for key in ('host_tx_s','host_ack_s','host_done_s','requested_duration_ms','measured_duration_ms',
                                    'operation_id','source_kp','sink_kp','current_avg_ua','current_max_ua'):
                            value=operation.get(key);operation[key]=float(value) if value not in (None,'') else None
            if hasattr(self,'timeline'):self.timeline.set_electrical(self.operations,(self.correspondence or {}).get('alignment'));self.update_operations();self.update_summary()

    def event_details(self,event):
        lines=[f"ОПТИКА: {event['entity']} {event['color']}; PTS {event['start_pts']:.6f}–{event['end_pts']:.6f}; "
               f"{event['status']}; confidence={event['confidence']:.3f}; coverage={event.get('coverage')}; "
               f"позиция=({event.get('x_ref_px')}, {event.get('y_ref_px')}) reference px"]
        matches=[r for r in (self.correspondence or {}).get('mapping',[]) if r['optical_event_id']==event['event_id']]
        for r in matches:
            lines.append(f"STM32: PHOTO/PAIR ID={r['operation_id']}; KP{r['source_kp']}→KP{r['sink_kp']}; "
                f"запрос/elapsed={r['requested_duration_ms']}/{r['measured_duration_ms']} мс; "
                f"AVG/MAX={r['current_avg_ua']}/{r['current_max_ua']} мкА; FAULT={r['fault']}; {r['electrical_status']}")
            lines.append(f"СВЯЗЬ: {r['mapping_status']}; {r['alignment_confidence']}; envelope ±{r['alignment_uncertainty_s']} с; "
                'аппаратной синхронизации нет')
        if not matches:lines.append('STM32: однозначная операция не сопоставлена; ток и SOURCE/SINK неизвестны.')
        return '\n'.join(lines)

    def refresh_correspondence(self):
        if self.closing:return
        link=self.path/'correspondence_link.json'
        if not link.is_file():return
        if self.owner.active_job:QTimer.singleShot(30,self.refresh_correspondence);return
        session=json.loads(link.read_text(encoding='utf-8'))['session']
        def done(value):
            self.load_correspondence();self.details.setPlainText('Создан новый снимок таблиц; прежние таблицы и автоматические события сохранены.')
        self.owner.start_job(lambda cancel,progress:link_analysis(self.path,session),done)

    def show_tables(self):
        self.load_correspondence()
        if self.snapshot_error:self.owner.error(self.snapshot_error+'; нажмите «Обновить соответствия».');return
        if not self.correspondence_path:self.owner.error('Сначала свяжите журнал эксперимента или запустите «Анализировать эксперимент».');return
        window=ExperimentTables(self,self.correspondence_path);self.table_windows.append(window);window.show()

    def relink_video(self):
        path,_=QFileDialog.getOpenFileName(self,'Найти исходное видео','','Video (*.mp4 *.mov *.avi)')
        if not path:return
        def work(cancel,progress):
            if image_hash(path)!=self.report['source_sha256']:raise ValueError('SHA-256 видео не совпадает с исходным анализом')
            atomic_json(self.path/'media_link.json',dict(path=str(Path(path).resolve())));return path
        def done(value):self.video_path=Path(value);QTimer.singleShot(0,lambda:self.request_frame(self.current_index))
        self.owner.start_job(work,done)

    def export(self):
        if image_hash(self.path/'events.json')!=self.report_hash:
            self.owner.error('Файл анализа изменён после открытия окна. Откройте нужный run заново.');return
        self.load_correspondence()
        if self.snapshot_error:self.owner.error(self.snapshot_error+'; обновите соответствия перед экспортом.');return
        folder=QFileDialog.getExistingDirectory(self,'Экспорт видеоанализа')
        if not folder:return
        target=Path(folder)/(self.path.name+'_export_'+uuid.uuid4().hex[:8])
        display_filter=self.filter.currentText()
        def work(cancel,progress):
            shutil.copytree(self.path,target)
            atomic_json(target/'export_manifest.json',dict(analysis_id=self.report.get('analysis_id',self.path.name),
                analysis_signature=analysis_signature(self.report),algorithm_version=self.report['algorithm_version'],settings=self.report['settings'],
                all_event_counts=dict(Counter(e['status'] for e in self.events)),display_filter=display_filter,
                latest_correspondence=self.correspondence_path.name if self.correspondence_path else None,
                note='Optical CSV exports all automatic events; GUI display filter does not alter export'))
        self.owner.start_job(work,lambda _:self.details.setPlainText('Экспорт: '+str(target)))

    def closeEvent(self,event):
        self.playing=False;self.timer.stop();self.closing=True
        if self.loading and self.owner.active_job:
            self.owner.cancel_job();event.ignore();QTimer.singleShot(30,self.close);return
        for window in self.table_windows:window.close()
        self.decoder.close();self.off_image=self.off_mask=None;self.viewer.scene().clear();self.closed=True;event.accept()
