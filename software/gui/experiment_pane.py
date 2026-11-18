"""LED49 recording assistant integrated into RGB Vision; no automatic lighting."""
from pathlib import Path
import json
import shutil
import uuid
from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QFormLayout, QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox, QDialog,
    QCheckBox, QDialogButtonBox)
from software.hardware.scenario import CONDITIONS, NAME, SHORT_NAME, scenario, short_scenario
from software.hardware.journal import save_session
from software.hardware.video_link import attach_video
from .experiment_worker import ExperimentWorker


class ExperimentPane(QWidget):
    def __init__(self, owner, root=None, factory=None):
        super().__init__()
        self.owner = owner
        self.running = self.busy = self.ready = self.connected = self.preparing = False
        self.session_path = self.video = None
        self.last_device={};self.last_current='—'
        self.worker = ExperimentWorker(root or Path(__file__).resolve().parents[2]/'results/video_experiments', self,
                                       **({'factory': factory} if factory else {}))
        self.worker.update.connect(self.update_state)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.ports = QComboBox(); self.ports.setEditable(True); row.addWidget(self.ports)
        self.refresh = self.add_button(row, 'Обновить порты', self.refresh_ports)
        self.connect_button = self.add_button(row, 'Подключить', self.connect_port)
        self.disconnect_button = self.add_button(row, 'Отключить', self.disconnect_port)
        self.check = self.add_button(row, 'Проверить стенд', lambda: self.request('check'))
        layout.addLayout(row)
        self.connection = QLabel('Не подключено. Открытие вкладки не включает выходы.')
        self.connection.setWordWrap(True); layout.addWidget(self.connection)
        self.diagnostics = QLabel('Диагностика ещё не выполнялась: FW, STATUS, ADCSTATUS, SELFTEST.')
        self.diagnostics.setWordWrap(True); layout.addWidget(self.diagnostics)
        self.instructions = QLabel('Телефон: все ArUco в кадре; 1080p/30 FPS, по возможности фиксируйте фокус и экспозицию. '
            'Начните запись вручную, затем запустите эксперимент. Небольшие наклоны допустимы; избегайте смаза и потери маркеров. '
            'Дождитесь финального OFF, остановите запись и добавьте MP4. Приложение камерой телефона не управляет.')
        self.instructions.setWordWrap(True); layout.addWidget(self.instructions)
        self.scenario_choice = QComboBox(); self.scenario_choice.addItem('LED49 RGB 5 seconds', NAME)
        self.scenario_choice.addItem('LED49 Short Pulse Test', SHORT_NAME); layout.addWidget(self.scenario_choice)
        form = QFormLayout(); self.controls = {}; self.timing_form = form
        for key, title, value, maximum in [('initial_ms', 'Начальный OFF, мс', 5000, 60000),
                ('photo_ms', 'Каждый PHOTO, мс', 5000, 10000), ('pause_ms', 'Промежуточный OFF, мс', 3000, 60000),
                ('final_ms', 'Финальный OFF, мс', 5000, 60000)]:
            spin = QSpinBox(); spin.setRange(100, maximum); spin.setSingleStep(100); spin.setValue(value)
            spin.valueChanged.connect(self.update_plan); self.controls[key] = spin; form.addRow(title, spin)
        layout.addLayout(form)
        self.short_options = QWidget(); short = QVBoxLayout(self.short_options); short.setContentsMargins(0,0,0,0)
        row = QHBoxLayout(); self.short_color=QComboBox();self.short_color.addItems(['RED','GREEN','BLUE'])
        row.addWidget(QLabel('Цвет'));row.addWidget(self.short_color);self.duration_boxes={}
        for duration in (100,200,300):
            box=QCheckBox(f'{duration} мс');box.setChecked(True);box.toggled.connect(self.update_plan)
            self.duration_boxes[duration]=box;row.addWidget(box)
        self.repeats=QSpinBox();self.repeats.setRange(1,30);self.repeats.setValue(10)
        row.addWidget(QLabel('Повторов'));row.addWidget(self.repeats);short.addLayout(row)
        row=QHBoxLayout();self.order=QComboBox();self.order.addItem('По длительностям','ordered');self.order.addItem('Перемешать','shuffled')
        row.addWidget(self.order);self.seed=QSpinBox();self.seed.setRange(0,2147483647);self.seed.setValue(49)
        row.addWidget(QLabel('Seed'));row.addWidget(self.seed)
        self.marker=QCheckBox('Маркер RED 1000 мс + OFF 2000 мс');row.addWidget(self.marker);short.addLayout(row)
        short.addWidget(QLabel('Анализ: Short Pulse / Experimental. Длительность света по одной выборке не подтверждается.'))
        for signal in (self.short_color.currentIndexChanged,self.repeats.valueChanged,self.order.currentIndexChanged,
                       self.seed.valueChanged,self.marker.toggled):signal.connect(self.update_plan)
        layout.addWidget(self.short_options);self.short_options.hide()
        self.scenario_choice.currentIndexChanged.connect(self.change_scenario)
        self.plan = QLabel(); self.plan.setWordWrap(True); layout.addWidget(self.plan)
        self.stage = QLabel('Этап — / 7; LED OFF; оставшееся время —'); layout.addWidget(self.stage)
        self.electrical = QLabel('STM32: —; FAULT: —; ток: —'); layout.addWidget(self.electrical)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.start = self.add_button(row, 'Запустить эксперимент', self.prepare)
        self.off = self.add_button(row, 'Прервать / OFF', self.abort)
        self.off.setStyleSheet('QPushButton {background:#b42323; color:white; font-weight:bold; min-height:38px;}')
        layout.addLayout(row)
        self.outcome = QLabel('Ожидание. IWDG выключен: держите питание физически доступным.')
        self.outcome.setWordWrap(True); layout.addWidget(self.outcome)
        row = QHBoxLayout()
        self.save = self.add_button(row, 'Сохранить результаты', self.export_results)
        self.log_button = self.add_button(row, 'Открыть журнал', self.open_log)
        self.load = self.add_button(row, 'Открыть прежнюю сессию', self.load_session)
        self.attach = self.add_button(row, 'Добавить записанное видео', self.choose_video)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.view = self.add_button(row, 'Открыть видео', self.open_video)
        self.analysis_mode=QComboBox();self.analysis_mode.addItems(['KNOWN_LEDS','DISCOVER']);row.addWidget(self.analysis_mode)
        self.analyze = self.add_button(row, 'Анализировать эксперимент', self.analyze_experiment)
        self.benchmark = self.add_button(row, 'Проверить производительность на этом видео', self.open_benchmark)
        layout.addLayout(row)
        self.video_info = QLabel('Видео не привязано. Синхронизация: UNALIGNED; точное смещение неизвестно.')
        self.video_info.setWordWrap(True); layout.addWidget(self.video_info)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000)
        layout.addWidget(self.log, 1)
        self.update_plan(); self.buttons()
        # No port is opened/enumerated until the operator requests it.

    @staticmethod
    def add_button(row, title, callback):
        button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button); return button

    def update_plan(self):
        if not hasattr(self,'plan'):return
        name=self.scenario_choice.currentData()
        self.config={}
        try:
            if name==SHORT_NAME:
                self.config=dict(color=self.short_color.currentText(),durations=[d for d,b in self.duration_boxes.items() if b.isChecked()],
                    repeats=self.repeats.value(),pause_ms=self.controls['pause_ms'].value(),
                    initial_ms=self.controls['initial_ms'].value(),final_ms=self.controls['final_ms'].value(),
                    order=self.order.currentData(),seed=self.seed.value(),marker=self.marker.isChecked())
                self.stages=short_scenario(**self.config)
            else:self.stages = scenario(**{key: value.value() for key, value in self.controls.items()})
        except ValueError as exc:
            self.stages=[];self.plan.setText(str(exc));self.start.setEnabled(False);return
        total = sum(stage.duration_ms for stage in self.stages)
        description=(' → '.join(f'{s.color} {s.duration_ms/1000:g} с' for s in self.stages) if name==NAME else
            f"{len([s for s in self.stages if s.role=='SHORT_PULSE'])} отдельных PHOTO; {self.config['order']}; seed={self.config['seed']}; маркер={self.config['marker']}")
        self.plan.setText(name + ': ' + description
                          + f'\nПлан: {total/1000:g} с + обмен и переходы. Фактические границы сохраняются отдельно.'
                          + (' Начальный OFF <2 с: штатному построению фона может не хватить данных.' if self.stages[0].duration_ms<2000 else ''))
        self.progress.setRange(0, total)
        if hasattr(self,'stage') and not self.running:self.stage.setText(f'Этап — / {len(self.stages)}; LED OFF; оставшееся время —')
        if hasattr(self,'start'):self.buttons()

    def change_scenario(self):
        short=self.scenario_choice.currentData()==SHORT_NAME
        self.short_options.setVisible(short)
        self.controls['photo_ms'].setVisible(not short)
        self.timing_form.labelForField(self.controls['photo_ms']).setVisible(not short)
        self.controls['pause_ms'].setValue(700 if short else 3000)
        self.update_plan()

    def buttons(self):
        idle = not self.running and not self.busy and not self.preparing
        self.start.setEnabled(self.connected and self.ready and idle and bool(self.stages))
        self.connect_button.setEnabled(not self.connected and idle)
        self.ports.setEnabled(not self.connected and idle)
        self.refresh.setEnabled(idle)
        self.check.setEnabled(self.connected and idle)
        self.disconnect_button.setEnabled(self.connected and not self.preparing)
        self.off.setEnabled(self.connected)
        for control in self.controls.values(): control.setEnabled(idle)
        self.scenario_choice.setEnabled(idle);self.short_options.setEnabled(idle)
        for control in (self.save, self.log_button): control.setEnabled(bool(self.session_path) and idle)
        self.load.setEnabled(idle)
        self.attach.setEnabled(bool(self.session_path) and idle)
        self.view.setEnabled(bool(self.video) and idle)
        self.benchmark.setEnabled(bool(self.video) and idle)
        self.analyze.setEnabled(bool(self.video) and bool(self.session_path) and idle)
        self.analysis_mode.setEnabled(idle)

    def refresh_ports(self):
        try:
            from serial.tools.list_ports import comports
            current = self.ports.currentText(); self.ports.clear()
            for port in comports(): self.ports.addItem(port.device)
            if current: self.ports.setEditText(current)
        except Exception as exc: self.owner.error(str(exc))

    def request(self, action, value=None):
        self.busy = True; self.buttons(); self.worker.submit(action, value)

    def connect_port(self):
        port = self.ports.currentText().strip()
        if not port:
            self.refresh_ports(); port = self.ports.currentText().strip()
        if port: self.request('connect', port)
        else: self.owner.error('Выберите обнаруженный COM-порт или введите COM19.')

    def disconnect_port(self):
        self.worker.interrupt('Operator disconnect')
        self.ready = False; self.request('disconnect')

    def prepare(self):
        if not self.ready or self.running: return
        if self.owner.active_job:
            self.owner.error('Дождитесь завершения обработки видео/фото перед управлением стендом.'); return
        self.preparing = True; self.request('prepare')

    def confirm_conditions(self):
        dialog = QDialog(self); dialog.setWindowTitle('Запись начата? Подтвердите условия')
        layout = QVBoxLayout(dialog)
        message = QLabel('Начните запись на телефоне. После подтверждения начнётся первый OFF.\n'
                         'ПО не проверяет U13/R1 физически. IWDG выключен; питание должно быть доступно.')
        message.setWordWrap(True); layout.addWidget(message)
        boxes = []
        for title in ('U13 OPEN', 'R1 = 2700 Ом', 'Подключена исследуемая RGB-плата MSI GS75',
                      'Могу физически снять питание STM32', 'Присутствую при эксперименте; запись видео начата'):
            box = QCheckBox(title); boxes.append(box); layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Подтвердить и начать')
        buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        for box in boxes: box.toggled.connect(lambda: buttons.button(QDialogButtonBox.Ok).setEnabled(all(b.isChecked() for b in boxes)))
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        return dict.fromkeys(CONDITIONS, True) if dialog.exec() == QDialog.Accepted else None

    def begin_confirmed(self, conditions):
        self.running = True; self.ready = False; self.video = self.session_path = None
        self.progress.setValue(0); self.outcome.setText('RUNNING — запись камеры управляется оператором.')
        binding=self.project_binding()
        self.request('run', dict(stages=list(self.stages), conditions=conditions,
            scenario_name=self.scenario_choice.currentData(),scenario_config=dict(self.config),project_binding=binding))

    def project_binding(self):
        p=self.owner.project
        return dict(project_path=str(p.path),calibration=p.data.get('calibration'),data_root=str(p.root)) if p else None

    def abort(self):
        self.ready = False
        self.worker.interrupt()
        if not self.running: self.request('off')
        self.outcome.setText('ABORTED: прекращение сценария, отправляется OFF; ожидаем подтверждение EN=0.')
        self.buttons()

    def update_state(self, value):
        if 'connected' in value:
            self.connected = value['connected']
            self.connection.setText('COM подключён; идёт диагностика.' if self.connected else 'COM отключён.')
            if not self.connected: self.ready = False
        if 'ready' in value: self.ready = value['ready']
        if 'busy' in value: self.busy = value['busy']
        if 'diagnostics' in value:
            d = value['diagnostics']
            self.diagnostics.setText(f"FW {d['info']['FW']} / PHOTO_LED49; STATE={d['status']['STATE']}; "
                f"EN=0/0; FAULT=NONE; ADC VALID={d['adc']['VALID']}, AGE_MS={d['adc']['AGE_MS']}; SELFTEST=PASS.")
            self.connection.setText('Подключено. Диагностика пройдена; выходы выключены по STATUS.')
        if 'event' in value:
            e = value['event']; self.log.appendPlainText(f"{e['utc']} {e['direction']} {e['text']}")
        if 'stage' in value:
            self.stage.setText(f"Этап {value['stage']}/{len(self.stages)}; LED {value['color']}; осталось ≈{value['remaining_ms']/1000:.1f} с")
        if 'progress_ms' in value: self.progress.setValue(int(value['progress_ms']))
        if 'current_ua' in value: self.last_current=value['current_ua']
        if 'device' in value:
            self.last_device=value['device']
        if 'current_ua' in value or 'device' in value:
            d=self.last_device
            self.electrical.setText(f"STM32 {d.get('STATE','—')}; FAULT={d.get('FAULT','—')}; EN={d.get('SRC_EN','—')}/{d.get('SNK_EN','—')}; ток {self.last_current} мкА")
        if 'warning' in value: self.outcome.setText(value['warning'])
        if 'off_confirmed' in value and not value['off_confirmed']:
            self.outcome.setText('ВНИМАНИЕ: физическое состояние выходов не подтверждено. При необходимости снимите питание.')
        if 'error' in value:
            self.preparing = False; self.running=False; self.ready = False
            self.outcome.setText(value['error']); self.owner.log(value['error'])
        if value.get('prepared') and self.preparing:
            conditions = self.confirm_conditions(); self.preparing = False
            if conditions and not self.worker.abort.is_set(): self.begin_confirmed(conditions)
        if 'result' in value:
            result = value['result']; self.running = False; self.busy = False; self.ready = False
            self.session_path = Path(value['session_path'])
            self.stage.setText(f"Этап {len(result['actual'])}/{len(result['planned'])}; LED "
                + ('OFF (STATUS)' if result['off_confirmed'] else 'состояние неизвестно') + '; эксперимент завершён.')
            self.outcome.setText(('[SIMULATION — не аппаратное испытание] ' if result.get('simulation') else '')
                + f"{result['status']}: {result['reason']}. OFF/EN подтверждён: {result['off_confirmed']}. "
                + ('' if result['off_confirmed'] else 'Физическое состояние неизвестно; снимите питание!'))
            if result['status'] == 'COMPLETED': self.progress.setValue(self.progress.maximum())
            self.buttons()
            if result['status'] == 'COMPLETED' and not self.worker.stopping.is_set():
                if QMessageBox.question(self, 'Эксперимент завершён', 'Финальный OFF подтверждён. Остановите запись. Выбрать записанное видео?') == QMessageBox.Yes:
                    self.choose_video()
        self.buttons()

    def export_results(self):
        destination = QFileDialog.getExistingDirectory(self, 'Каталог для копии результатов')
        if destination and self.session_path:
            target = Path(destination)/(self.session_path.name + '_export_' + uuid.uuid4().hex[:8])
            shutil.copytree(self.session_path, target)
            self.owner.log('Экспорт: ' + str(target))

    def open_log(self):
        if self.session_path: QDesktopServices.openUrl(QUrl.fromLocalFile(str((self.session_path/'events.jsonl').resolve())))

    def load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Открыть сессию эксперимента', 'results/video_experiments', 'Session (session.json)')
        if not path: return
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if data.get('scenario') not in (NAME,SHORT_NAME) or data.get('status') not in ('COMPLETED','ABORTED','FAILED'):
                raise ValueError('Не завершённая сессия LED49')
            self.session_path = Path(path).parent; self.video = data.get('video')
            self.outcome.setText(data['status'] + ': ' + data.get('reason', ''))
            if self.video: self.video_info.setText(str(self.video))
            self.buttons()
        except Exception as exc: self.owner.error(str(exc))

    def choose_video(self):
        if not self.session_path or self.running: return
        path, _ = QFileDialog.getOpenFileName(self, 'Выбрать записанное видео', '', 'Video (*.mp4 *.mov)')
        if path: self.import_video(path)

    def import_video(self, path):
        session_path = self.session_path
        def done(video):
            self.video = video
            self.video_info.setText(f"{video['path']}\n{video['width']}×{video['height']}, FPS={video['fps']}, "
                f"длительность={video['duration_s']} с. UNALIGNED: оптическое смещение и погрешность неизвестны.")
            self.buttons()
        self.owner.start_job(lambda cancel, progress: attach_video(session_path, path), done)

    def open_video(self):
        if self.video: self.owner.open_video(self.video['path'])

    def open_benchmark(self):
        if self.video and not self.owner.active_job:
            self.owner.performance.select_video(self.video['path'])
            self.owner.tabs.setCurrentWidget(self.owner.performance)

    def analyze_experiment(self):
        if not self.session_path or not self.video or self.running or self.owner.active_job:return
        try:
            path=self.session_path/'session.json';data=json.loads(path.read_text(encoding='utf-8'))
            binding=data.get('project_binding') or {}
            bound=binding.get('project_path')
            if not bound or not Path(bound).is_file():
                selected,_=QFileDialog.getOpenFileName(self,'Выбрать проект для эксперимента',
                    str(self.owner.project.path) if self.owner.project else '', 'Project (*.json)')
                if not selected:return
                bound=selected
            if not self.owner.project or self.owner.project.path!=Path(bound).resolve():
                self.owner.open_project(bound)
                if not self.owner.project or self.owner.project.path!=Path(bound).resolve():return
                data['project_binding']=self.project_binding();save_session(self.session_path,data)
                if self.owner.active_job:self.resume_analysis();return
            if not self.owner.project:return
            data['project_binding']=self.project_binding();save_session(self.session_path,data)
            try:self.owner.project.checked_calibration()
            except (ValueError,OSError):
                selected,_=QFileDialog.getOpenFileName(self,'Выбрать калибровку для эксперимента','','Calibration (*.json)')
                if not selected:return
                root=self.owner.project.root
                reference=json.loads(Path(selected).read_text(encoding='utf-8'))['reference']['path']
                if not (root/reference).is_file():
                    if (Path(selected).parent/reference).is_file():root=Path(selected).parent
                    else:
                        chosen=QFileDialog.getExistingDirectory(self,'Корень данных с эталоном калибровки',str(root))
                        if not chosen:return
                        root=Path(chosen)
                self.owner.load_calibration(selected,root)
                if self.owner.active_job:self.resume_analysis();return
                self.owner.project.checked_calibration()
            data['project_binding']=self.project_binding();save_session(self.session_path,data)
            controls=self.owner.video_events
            controls.mode.setCurrentText(self.analysis_mode.currentText())
            controls.profile.setCurrentIndex(1 if data['scenario']==SHORT_NAME else 0)
            controls.start.setValue(0);controls.duration.setValue(2)
            if self.owner.video_path!=Path(self.video['path']) or self.owner.video_meta is None:
                self.owner.open_video(self.video['path'])
                if self.owner.active_job:self.resume_analysis();return
            self.owner.tabs.setCurrentWidget(self.owner.video_page)
            controls.analyze(session_path=path)
        except Exception as exc:self.owner.error(str(exc))

    def resume_analysis(self):
        def ready():
            if not self.owner.isVisible():return
            if self.owner.active_job:QTimer.singleShot(15,ready)
            elif self.owner.job_success:self.analyze_experiment()
        QTimer.singleShot(15,ready)
