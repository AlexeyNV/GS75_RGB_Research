"""Single-owner CDC executor. Shared PHOTO parser/validation and transport with CLI."""
import threading
import time
from tools.photo_led49 import PhotoSession, PhotoError, fields, integer
from .journal import Journal, utc_now
from .scenario import CONDITIONS, EXPECTED_UA, SINKS, scenario


class Aborted(PhotoError):
    pass


class Experiment(PhotoSession):
    def __init__(self, transport, port, root, clock_ns=time.monotonic_ns, notify=lambda value: None, abort=None):
        self.clock_ns = clock_ns
        super().__init__(transport, clock=lambda: clock_ns()/1e9, progress=lambda _: None)
        self.port, self.root, self.notify = port, root, notify
        self.abort = abort or threading.Event()
        self.journal = None
        self.recording = False
        self.phase = None
        self.measurement = None
        self.reason = 'Operator OFF'
        self.last_ui_ns = 0
        self.last_status = None

    def checkpoint(self):
        if self.abort.is_set():
            raise Aborted(self.reason)

    def record(self, direction, text):
        event = dict(utc=utc_now(), monotonic_ns=self.clock_ns(), direction=direction, text=text)
        self.events.append(event)
        if self.journal and self.recording:
            self.journal.event(direction, text)
            if self.measurement is not None and direction == 'RX':
                data = fields(text)
                if text.startswith('ACK '):
                    self.measurement.update(ack=text, ack_ns=event['monotonic_ns'], id=integer(data, 'ID'))
                elif text.startswith('DONE '):
                    self.measurement.update(done=text, done_ns=event['monotonic_ns'])
                    for key in ('CURRENT_AVG_UA', 'CURRENT_MAX_UA', 'SAMPLES', 'ELAPSED_MS', 'REASON', 'FAULT'):
                        if key in data:
                            self.measurement[key.lower()] = data[key] if key in ('REASON', 'FAULT') else integer(data, key)
                self.journal.save()
        self.notify(dict(event=event))

    def send(self, command):
        self.checkpoint()
        return super().send(command)

    def receive(self, timeout=.02):
        self.checkpoint()
        line = super().receive(min(timeout, .02))
        if line:
            data = fields(line)
            if line.startswith('ACK '):
                self.notify(dict(device=dict(STATE='ACTIVE (ACK)', FAULT='NONE', SRC_EN='1', SNK_EN='1')))
            if line.startswith('OK ADCSTATUS '):
                self.validate_adc(data)
            if line.startswith('OK RAW='):
                self.notify(dict(current_ua=integer(data, 'CURRENT_UA')))
            if line.startswith('OK STATE='):
                self.notify(dict(device=data))
        if self.phase and self.clock_ns() - self.last_ui_ns >= 100_000_000:
            self.last_ui_ns = self.clock_ns()
            elapsed = (self.clock_ns() - self.phase['start_ns'])/1e6
            self.notify(dict(stage=self.phase['index'], color=self.phase['color'],
                remaining_ms=max(0, self.phase['duration_ms']-elapsed),
                progress_ms=sum(s.duration_ms for s in self.stages[:self.phase['index']-1]) + min(elapsed, self.phase['duration_ms'])))
        return line

    @staticmethod
    def validate_adc(data):
        if any(integer(data, key) != value for key, value in
               [('VALID', 1), ('HAS_SAMPLE', 1), ('ERRORS', 0), ('OVR_COUNT', 0)]) or integer(data, 'AGE_MS') > 5:
            raise PhotoError('ADC invalid/stale/error')

    def preflight(self, require_disarmed=True):
        result = super().preflight(require_disarmed=True)
        self.notify(dict(diagnostics=result, device=result['status']))
        return result

    def safe_off(self):
        """Bypass abort and journal failures; bounded reads, then verify reported EN."""
        self.off_confirmed = False
        def record(direction, text):
            try:
                self.record(direction, text)
            except Exception:
                pass
        try:
            self.transport.send('OFF')
            record('TX', 'OFF')
            deadline = self.clock() + 1
            acknowledged = False
            while self.clock() < deadline:
                line = self.transport.read(.02)
                if line:
                    record('RX', line)
                    if line == 'OK DISARMED':
                        acknowledged = True
                        break
            self.transport.send('STATUS')
            record('TX', 'STATUS')
            deadline = self.clock() + 1
            while self.clock() < deadline:
                line = self.transport.read(.02)
                if line:
                    record('RX', line)
                    if line.startswith('OK STATE='):
                        status = fields(line)
                        self.last_status = status
                        self.off_confirmed = (acknowledged and status.get('STATE') in ('DISARMED', 'FAULT')
                            and all(integer(status, key) == 0 for key in ('SRC_EN', 'SNK_EN')))
                        self.notify(dict(device=status))
                        break
        except Exception as exc:
            record('ERROR', 'OFF unavailable: ' + str(exc))
        self.notify(dict(off_confirmed=self.off_confirmed))
        return self.off_confirmed

    def off_stage(self, stage):
        if not self.safe_off():
            raise PhotoError('OFF/EN unconfirmed; physically remove power')
        deadline = self.clock_ns() + stage.duration_ms*1_000_000
        self.phase['off_confirmed_ns'] = self.clock_ns()
        next_check = self.clock_ns()
        while self.clock_ns() < deadline:
            self.checkpoint()
            if self.clock_ns() >= next_check:
                status = fields(self.query('STATUS', 'OK STATE='))
                if status.get('STATE') != 'DISARMED' or any(integer(status, k) for k in ('SRC_EN', 'SNK_EN')):
                    raise PhotoError('OFF stage unexpectedly active')
                self.validate_adc(fields(self.query('ADCSTATUS', 'OK ADCSTATUS ')))
                self.query('CURRENT', 'OK RAW=')
                next_check = self.clock_ns() + 500_000_000
            self.receive(min(.02, max(0, (deadline-self.clock_ns())/1e9)))

    def run_sequence(self, stages=None, conditions=None):
        self.stages = stages or scenario()
        # Accept only the preset structure and bounded controls, never arbitrary pins/colors.
        validated = scenario(self.stages[0].duration_ms, self.stages[1].duration_ms,
                             self.stages[2].duration_ms, self.stages[-1].duration_ms)
        if list(self.stages) != validated or not conditions or any(conditions.get(key) is not True for key in CONDITIONS):
            raise ValueError('Invalid scenario or missing physical operator confirmation')
        self.ack = self.done = None
        self.journal = Journal(self.root, self.stages, self.port, conditions, self.clock_ns)
        self.recording = True
        result = self.journal.data
        try:
            result['diagnostics'] = self.preflight()
            self.journal.save()
            for index, stage in enumerate(self.stages, 1):
                self.checkpoint()
                self.phase = dict(index=index, color=stage.color, duration_ms=stage.duration_ms,
                    start_ns=self.clock_ns(), start_utc=utc_now(), status='RUNNING')
                result['actual'].append(self.phase)
                self.journal.event('STAGE', 'BEGIN', **self.phase)
                self.notify(dict(stage=index, color=stage.color, remaining_ms=stage.duration_ms))
                if stage.color == 'OFF':
                    self.off_stage(stage)
                else:
                    self.ack = self.done = None
                    self.measurement = dict(color=stage.color, source=14, sink=SINKS[stage.color],
                        duration_ms=stage.duration_ms, command=f'PHOTO LED49 {stage.color} {stage.duration_ms}', status='RUNNING')
                    result['measurements'].append(self.measurement)
                    self.journal.save()
                    # One bounded ARM and PHOTO; CLI owns matching ACK/DONE and electrical checks.
                    done = super().run(stage.color, stage.duration_ms)
                    avg = integer(done, 'CURRENT_AVG_UA')
                    if avg < 100:
                        raise PhotoError('LED49 average current <100 uA; inspect board/connection')
                    warning = '' if abs(avg/EXPECTED_UA[stage.color]-1) <= .35 else 'Current differs >35% from historical observation; calibration unverified'
                    if warning:
                        self.journal.event('WARNING', warning)
                        self.notify(dict(warning=warning))
                    self.measurement.update(status='COMPLETED', warning=warning)
                    if not self.safe_off():
                        raise PhotoError('OFF/EN unconfirmed; physically remove power')
                    if self.last_status.get('FAULT') != 'NONE':
                        raise PhotoError('FAULT after PHOTO; no automatic recovery')
                    self.measurement = None
                self.phase.update(end_ns=self.clock_ns(), end_utc=utc_now(), status='COMPLETED')
                self.phase['host_elapsed_ms'] = (self.phase['end_ns']-self.phase['start_ns'])/1e6
                self.journal.event('STAGE', 'END', **self.phase)
                self.journal.save()
            self.checkpoint()
            result.update(status='COMPLETED', reason='All seven stages completed')
        except BaseException as exc:
            result.update(status='ABORTED' if isinstance(exc, (Aborted, KeyboardInterrupt)) else 'FAILED',
                          reason=type(exc).__name__ + ': ' + str(exc))
            if self.phase and self.phase['status'] == 'RUNNING':
                self.phase.update(status=result['status'], end_ns=self.clock_ns(), end_utc=utc_now())
                self.phase['host_elapsed_ms'] = (self.phase['end_ns']-self.phase['start_ns'])/1e6
            if self.measurement:
                self.measurement['status'] = result['status']
            try:
                self.journal.event('ERROR', result['reason'])
            except OSError:
                pass
        finally:
            confirmed = self.safe_off()
            result.update(off_confirmed=confirmed, utc_finished=utc_now(), finished_ns=self.clock_ns())
            if not confirmed and result['status'] == 'COMPLETED':
                result.update(status='FAILED', reason='Final OFF/EN unconfirmed; physically remove power')
            if self.last_status and (self.last_status.get('FAULT') != 'NONE' or self.last_status.get('STATE') != 'DISARMED') and result['status'] == 'COMPLETED':
                result.update(status='FAILED', reason='FAULT at final STATUS; no automatic recovery')
            try:
                self.journal.save()
            except OSError as exc:
                result.update(status='FAILED', reason='Journal write failed: ' + str(exc))
            self.phase = self.measurement = None
            self.recording = False
        self.notify(dict(result=result, session_path=str(self.journal.path)))
        return result
