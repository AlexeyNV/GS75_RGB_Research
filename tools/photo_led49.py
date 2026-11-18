"""One operator-confirmed LED49 PHOTO command; never retries ARM or PHOTO."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rgb_probe import SerialTransport, fields, integer


class PhotoError(RuntimeError):
    pass


class PhotoSession:
    def __init__(self, transport, log=None, clock=time.monotonic, progress=print, monitor_interval=.25):
        self.transport, self.log, self.clock, self.progress = transport, log, clock, progress
        self.events = []
        self.ack = self.done = None
        self.off_confirmed = False
        if not .01 <= monitor_interval <= .5: raise ValueError('Invalid monitoring interval')
        self.monitor_interval = monitor_interval

    def record(self, direction, text):
        event = dict(utc=datetime.now(timezone.utc).isoformat(), monotonic_s=self.clock(), direction=direction, text=text)
        self.events.append(event)
        if self.log:
            self.log.write(json.dumps(event) + '\n')
            self.log.flush()

    def send(self, command):
        self.record('TX', command)
        self.transport.send(command)

    def receive(self, timeout=.05):
        line = self.transport.read(timeout)
        if line is None:
            return None
        self.record('RX', line)
        if line.startswith('ERR '):
            raise PhotoError(line)
        data = fields(line)
        if data.get('FAULT', 'NONE') != 'NONE':
            raise PhotoError(line)
        if line.startswith('DONE '):
            if self.ack is None or integer(data, 'ID') != integer(self.ack, 'ID'):
                raise PhotoError('Unexpected DONE ID: ' + line)
            self.done = data
            if (data.get('MODE') != 'PHOTO' or data.get('LED') != '49' or data.get('COLOR') != self.color
                    or data.get('STATE') != 'OFF' or data.get('REASON') != 'TIMEOUT' or data.get('FAULT') != 'NONE'
                    or integer(data, 'SAMPLES') == 0 or integer(data, 'CURRENT_MAX_UA') > 2000
                    or integer(data, 'CURRENT_AVG_UA') > integer(data, 'CURRENT_MAX_UA')
                    or not self.duration <= integer(data, 'ELAPSED_MS') <= self.duration + 10):
                raise PhotoError('Invalid or interrupted PHOTO completion: ' + line)
        if line.startswith('OK RAW='):
            if (integer(data, 'VALID') != 1 or integer(data, 'AGE_MS') > 5
                    or integer(data, 'CURRENT_UA') > 2000):
                raise PhotoError('Unsafe CURRENT: ' + line)
            self.progress(f"CURRENT {data['CURRENT_UA']} uA")
        return line

    def wait(self, predicate, timeout=1.0):
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            line = self.receive(min(.05, max(0, deadline-self.clock())))
            if line is not None and predicate(line):
                return line
        raise PhotoError('Response timeout')

    def query(self, command, prefix):
        self.send(command)
        return self.wait(lambda line: line.startswith(prefix))

    def preflight(self, require_disarmed=False):
        if self.query('PING', 'PONG') != 'PONG':
            raise PhotoError('Invalid PING response')
        self.send('INFO')
        info = {}
        deadline = self.clock() + 1
        while True:
            if self.clock() >= deadline:
                raise PhotoError('INFO timeout')
            line = self.receive()
            if line == 'END INFO':
                break
            if line and ': ' in line:
                key, value = line.split(': ', 1)
                if key in info:
                    raise PhotoError('Duplicate INFO field')
                info[key] = value
        if info.get('FW') != '0.1.2' or 'PHOTO_LED49' not in info.get('CAPABILITIES', '').split(','):
            raise PhotoError('Requires FW 0.1.2 with PHOTO_LED49; never falls back to PAIR')
        status = fields(self.query('STATUS', 'OK STATE='))
        if status.get('STATE') not in (('DISARMED',) if require_disarmed else ('DISARMED', 'IDLE')) or status.get('FAULT') != 'NONE' or any(integer(status,k) for k in ('SRC_EN','SNK_EN')):
            raise PhotoError('Device not safely idle')
        adc = fields(self.query('ADCSTATUS', 'OK ADCSTATUS '))
        if (integer(adc,'VALID') != 1 or integer(adc,'HAS_SAMPLE') != 1
                or integer(adc,'AGE_MS') > 5 or integer(adc,'ERRORS') != 0 or integer(adc,'OVR_COUNT') != 0):
            raise PhotoError('ADC preflight failed')
        if fields(self.query('SELFTEST', 'OK SELFTEST=')).get('SELFTEST') != 'PASS':
            raise PhotoError('SELFTEST failed')
        return dict(info=info, status=status, adc=adc, selftest='PASS')

    def run(self, color, duration_ms):
        self.color, self.duration = color.upper(), duration_ms
        try:
            if self.color not in ('RED', 'GREEN', 'BLUE') or not 100 <= duration_ms <= 10000:
                raise ValueError('PHOTO supports RED/GREEN/BLUE and 100..10000 ms')
            self.preflight()
            seconds = math.ceil(duration_ms/1000) + 5
            if integer(fields(self.query(f'ARM {seconds}', 'OK ARM_TIMEOUT_S=')), 'ARM_TIMEOUT_S') != seconds:
                raise PhotoError('ARM response mismatch')
            self.send(f'PHOTO LED49 {self.color} {duration_ms}')
            self.ack = fields(self.wait(lambda line: line.startswith('ACK ')))
            if (self.ack.get('MODE') != 'PHOTO' or self.ack.get('LED') != '49' or self.ack.get('COLOR') != self.color
                    or integer(self.ack,'SRC') != 14 or integer(self.ack,'SNK') != {'RED':32,'GREEN':33,'BLUE':34}[self.color]
                    or integer(self.ack,'DURATION_MS') != duration_ms):
                raise PhotoError('ACK mismatch')
            integer(self.ack, 'ID')
            started = self.clock(); deadline = started + duration_ms/1000 + 1
            next_current = started + self.monitor_interval
            while self.done is None:
                if self.clock() >= deadline:
                    raise PhotoError('Missing DONE')
                if self.clock() >= next_current:
                    self.progress(f"Remaining approximately {max(0, duration_ms/1000-(self.clock()-started)):.1f} s")
                    self.query('CURRENT', 'OK RAW='); next_current = self.clock() + self.monitor_interval
                    adc = fields(self.query('ADCSTATUS', 'OK ADCSTATUS '))
                    if (integer(adc, 'VALID') != 1 or integer(adc, 'HAS_SAMPLE') != 1
                            or integer(adc, 'AGE_MS') > 5 or integer(adc, 'ERRORS') != 0 or integer(adc, 'OVR_COUNT') != 0):
                        raise PhotoError('ADC monitoring failed')
                self.receive()
            return self.done
        finally:
            # Even if USB is gone, record the attempt; do not claim it reached the MCU.
            try:
                # Stop must reach transport even when writing the log has failed.
                self.transport.send('OFF')
                try: self.record('TX', 'OFF')
                except OSError: pass
                end = self.clock() + 1
                while self.clock() < end:
                    line = self.transport.read(.05)
                    if line is not None:
                        try: self.record('RX', line)
                        except OSError: pass
                        if line == 'OK DISARMED':
                            self.off_confirmed = True
                            break
                if not self.off_confirmed:
                    self.record('ERROR', 'OFF acknowledgement unavailable')
            except (OSError, RuntimeError) as exc:
                try: self.record('ERROR', 'OFF failed: ' + str(exc))
                except OSError: pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--color', choices=['red','green','blue'], required=True)
    parser.add_argument('--duration-s', type=float, default=5)
    parser.add_argument('--confirm-photo', action='store_true', help='Confirm U13 OPEN, R1=2700 ohm, prepared LED49 and one ARM/PHOTO')
    parser.add_argument('--log', type=Path, default=None, help='New JSONL log; existing files refused')
    args = parser.parse_args()
    if not math.isfinite(args.duration_s) or not .1 <= args.duration_s <= 10:
        parser.error('--duration-s must be 0.1..10')
    duration = round(args.duration_s*1000)
    if not args.confirm_photo:
        if input('U13 OPEN, R1=2700 ohm, LED49 prepared. Type PHOTO to authorize one ARM and PHOTO: ') != 'PHOTO':
            parser.error('Operator did not confirm')
    path = args.log or Path('results') / ('photo_led49_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    transport = None
    try:
        with path.open('x', encoding='utf-8') as log:
            transport = SerialTransport(args.port)
            session = PhotoSession(transport, log)
            try:
                result = session.run(args.color, duration)
                print(json.dumps(result)); return 0 if session.off_confirmed else 2
            except (Exception, KeyboardInterrupt) as exc:
                session.record('ERROR', type(exc).__name__ + ': ' + str(exc))
                print(f'Stopped: {exc}. OFF confirmed: {session.off_confirmed}', file=sys.stderr)
                return 2
    finally:
        if transport:
            transport.close()


if __name__ == '__main__':
    raise SystemExit(main())
