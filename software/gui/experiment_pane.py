"""LED49 recording assistant integrated into RGB Vision; no automatic lighting."""
from pathlib import Path
import json
import shutil
import uuid
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QFormLayout, QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox, QDialog,
    QCheckBox, QDialogButtonBox)
from software.hardware.scenario import CONDITIONS, NAME, scenario
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
        form = QFormLayout(); self.controls = {}
        for key, title, value, maximum in [('initial_ms', 'Начальный OFF, мс', 5000, 60000),
                ('photo_ms', 'Каждый PHOTO, мс', 5000, 10000), ('pause_ms', 'Промежуточный OFF, мс', 3000, 60000),
                ('final_ms', 'Финальный OFF, мс', 5000, 60000)]:
            spin = QSpinBox(); spin.setRange(100, maximum); spin.setSingleStep(100); spin.setValue(value)
            spin.valueChanged.connect(self.update_plan); self.controls[key] = spin; form.addRow(title, spin)
        layout.addLayout(form)
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
        self.attach = self.add_button(row, 'Добавить видео к эксперименту', self.choose_video)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.view = self.add_button(row, 'Открыть видео', self.open_video)
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
        self.stages = scenario(**{key: value.value() for key, value in self.controls.items()})
        total = sum(stage.duration_ms for stage in self.stages)
        self.plan.setText(NAME + ': ' + ' → '.join(f'{s.color} {s.duration_ms/1000:g} с' for s in self.stages)
                          + f'\nПлан: {total/1000:g} с + обмен и переходы. Фактические границы сохраняются отдельно.'
                          + (' Начальный OFF <2 с: штатному построению фона может не хватить данных.' if self.stages[0].duration_ms<2000 else ''))
        self.progress.setRange(0, total)

    def buttons(self):
        idle = not self.running and not self.busy and not self.preparing
        self.start.setEnabled(self.connected and self.ready and idle)
        self.connect_button.setEnabled(not self.connected and idle)
        self.ports.setEnabled(not self.connected and idle)
        self.refresh.setEnabled(idle)
        self.check.setEnabled(self.connected and idle)
        self.disconnect_button.setEnabled(self.connected and not self.preparing)
        self.off.setEnabled(self.connected)
        for control in self.controls.values(): control.setEnabled(idle)
        for control in (self.save, self.log_button): control.setEnabled(bool(self.session_path) and idle)
        self.load.setEnabled(idle)
        self.attach.setEnabled(bool(self.session_path) and idle)
        self.view.setEnabled(bool(self.video) and idle)
        self.benchmark.setEnabled(bool(self.video) and idle)

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
        self.request('run', dict(stages=self.stages, conditions=conditions))

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
            self.stage.setText(f"Этап {value['stage']}/7; LED {value['color']}; осталось ≈{value['remaining_ms']/1000:.1f} с")
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
            self.stage.setText(f"Этап {len(result['actual'])}/7; LED "
                + ('OFF (STATUS)' if result['off_confirmed'] else 'состояние неизвестно') + '; эксперимент завершён.')
            self.outcome.setText(f"{result['status']}: {result['reason']}. OFF/EN подтверждён: {result['off_confirmed']}. "
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
            if data.get('scenario') != NAME or data.get('status') not in ('COMPLETED','ABORTED','FAILED'):
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
