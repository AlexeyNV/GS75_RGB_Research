"""Deterministic FW 0.1.2 protocol simulator. Never opens a physical serial port."""
from .scenario import EXPECTED_UA, SINKS


class VirtualClock:
    def __init__(self): self.ns = 0
    def now_ns(self): return self.ns
    def advance(self, seconds): self.ns += max(1, round(seconds*1e9))


class SimulatedCDC:
    def __init__(self, clock=None, failure=None, hook=None):
        self.clock = clock or VirtualClock()
        self.failure, self.hook = failure, hook
        self.queue, self.commands, self.command_times = [], [], []
        self.active = None; self.id = 0; self.state = 'DISARMED'; self.fault = 'NONE'
        self.closed = self.disconnected = False
        self.max_read_timeout = 0

    def completion(self, reason='TIMEOUT'):
        operation = self.active
        self.active = None; self.state = 'IDLE' if reason == 'TIMEOUT' else 'DISARMED'
        ident = operation['id'] + (1 if self.failure == 'id' else 0)
        avg = 20 if self.failure == 'low_current' else (1500 if self.failure == 'deviation' else EXPECTED_UA[operation['color']])
        maximum = 2001 if self.failure == 'current' else avg + 50
        samples = 0 if self.failure == 'samples' else operation['duration'] - 1
        elapsed = operation['duration'] + (50 if self.failure == 'elapsed' else 0)
        if reason != 'TIMEOUT': elapsed = max(0, (self.clock.ns-operation['start_ns'])//1_000_000)
        if self.failure == 'expired': reason = 'ARM_EXPIRED'
        if self.failure == 'fault': self.fault = 'OVERCURRENT'; self.state = 'FAULT'; reason = 'FAULT'
        return (f"DONE ID={ident} STATE=OFF CURRENT_AVG_UA={avg} CURRENT_MAX_UA={maximum} SAMPLES={samples} "
            f"FAULT={self.fault} REASON={reason} MODE=PHOTO LED=49 COLOR={operation['color']} ELAPSED_MS={elapsed}")

    def send(self, command):
        self.commands.append(command); self.command_times.append((self.clock.ns, command))
        if self.closed or self.disconnected: raise OSError('USB removed')
        if command == 'PING': self.queue.append('PONG')
        elif command == 'INFO':
            fw = '0.1.1' if self.failure == 'version' else '0.1.2'
            capability = 'NONE' if self.failure == 'capability' else 'PHOTO_LED49'
            self.queue.extend([f'FW: {fw}', 'MCU: STM32F411RET6', f'CAPABILITIES: {capability}', 'END INFO'])
        elif command == 'STATUS':
            state = 'ACTIVE' if self.failure == 'active' else self.state
            en = int(self.active is not None or self.failure == 'en')
            self.queue.append(f'OK STATE={state} SRC=14 SNK=32 SRC_EN={en} SNK_EN={en} REMAIN_MS=0 FAULT={self.fault} MODE=NONE')
        elif command == 'ADCSTATUS':
            valid = 0 if self.failure == 'adc' or (self.failure == 'adc_active' and self.active) else 1
            age = 6 if self.failure == 'stale' else 0
            ovr = 1 if self.failure == 'ovr' else 0
            self.queue.append(f'OK ADCSTATUS VALID={valid} HAS_SAMPLE=1 AGE_MS={age} ERRORS=0 OVR_COUNT={ovr}')
        elif command == 'SELFTEST':
            self.queue.append('OK SELFTEST=' + ('FAIL' if self.failure == 'selftest' else 'PASS') + ' STATE=DISARMED FAULT=NONE')
        elif command.startswith('ARM '):
            self.state = 'IDLE'; self.queue.append('OK ARM_TIMEOUT_S=' + command.split()[1])
        elif command.startswith('PHOTO '):
            if self.failure == 'usb': self.disconnected = True; raise OSError('USB removed')
            _, led, color, duration = command.split(); self.id += 1
            assert led == 'LED49' and color in SINKS and self.state == 'IDLE' and self.active is None
            self.state = 'ACTIVE'
            self.active = dict(color=color, duration=int(duration), id=self.id, start_ns=self.clock.ns)
            if self.failure != 'noack':
                self.queue.append(f'ACK ID={self.id} MODE=PHOTO LED=49 COLOR={color} SRC=14 SNK={SINKS[color]} DURATION_MS={duration}')
        elif command == 'CURRENT':
            current = EXPECTED_UA[self.active['color']] if self.active else 16
            if not (self.failure == 'no_current' and self.active): self.queue.append(f'OK RAW=100 CURRENT_UA={current} AGE_MS=0 VALID=1')
        elif command == 'OFF':
            if self.active: self.queue.append(self.completion('OFF'))
            if self.state != 'FAULT': self.state = 'DISARMED'
            if self.failure != 'no_off': self.queue.append('OK DISARMED')
        else: raise AssertionError('Unsupported simulator command: ' + command)

    def read(self, timeout):
        self.max_read_timeout = max(self.max_read_timeout, timeout)
        self.clock.advance(min(timeout, .002) if self.queue else timeout)
        if self.hook: self.hook(self)
        if self.disconnected: raise OSError('USB removed')
        if self.queue: return self.queue.pop(0)
        if self.active:
            elapsed = (self.clock.ns-self.active['start_ns'])/1e6
            if self.failure == 'ctrlc' and elapsed > 50:
                self.failure = None; raise KeyboardInterrupt()
            limit = 50 if self.failure in ('fault', 'expired') else self.active['duration']
            if elapsed >= limit and self.failure != 'missing': return self.completion()
        return None

    def close(self): self.closed = True
