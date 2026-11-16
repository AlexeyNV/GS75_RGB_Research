"""Operator-started electrical probe for FW 0.1.1; simulation needs no serial device."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class ProbeError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fields(line):
    result = {}
    for token in line.split():
        if '=' in token:
            key, value = token.split('=', 1)
            if key in result:
                raise ProbeError('ERROR_PROTOCOL', f'Duplicate field: {key}')
            result[key] = value
    return result


def integer(data, key):
    value = data.get(key, '')
    if not re.fullmatch(r'[0-9]+', value) or len(value) > 10:
        raise ProbeError('ERROR_PROTOCOL', f'Missing/invalid integer: {key}')
    result = int(value)
    if result > 0xffffffff:
        raise ProbeError('ERROR_PROTOCOL', f'Integer outside uint32: {key}')
    return result


def pin_list(value):
    pins = []
    for group in value.split(','):
        match = re.fullmatch(r'(\d+)(?:-(\d+))?', group)
        if not match:
            raise argparse.ArgumentTypeError('Use pins such as 32,33,34 or 1-40')
        a, b = int(match[1]), int(match[2] or match[1])
        if not 1 <= a <= b <= 40:
            raise argparse.ArgumentTypeError('Pins must be 1..40; ranges ascending')
        pins.extend(range(a, b + 1))
    return list(dict.fromkeys(pins))


class Clock:
    now = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


class VirtualClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(seconds, 0)


class SerialTransport:
    def __init__(self, port):
        import serial
        self.port = serial.Serial(port, 115200, timeout=0.02, write_timeout=0.25)
        self.partial = bytearray()

    def send(self, command):
        payload = (command + '\n').encode('ascii')
        if self.port.write(payload) != len(payload):
            raise OSError('Short USB write')

    def read(self, timeout):
        if b'\n' not in self.partial:
            self.port.timeout = min(timeout, 0.02)
            self.partial.extend(self.port.read(256))
        if len(self.partial) > 4096:
            raise ProbeError('ERROR_PROTOCOL', 'Oversized USB response')
        if b'\n' not in self.partial:
            return None
        raw, _, rest = self.partial.partition(b'\n')
        self.partial = bytearray(rest)
        try:
            return raw.decode('ascii').rstrip('\r')
        except UnicodeDecodeError as exc:
            raise ProbeError('ERROR_PROTOCOL', 'Non-ASCII USB response') from exc

    def close(self):
        self.port.close()


class Simulator:
    """Protocol fixture only: currents use LED49 observations; no optical inference."""
    def __init__(self, clock):
        self.clock, self.queue, self.commands = clock, [], []
        self.state, self.until, self.active, self.id = 'DISARMED', 0, None, 0
        self.closed = False

    def send(self, command):
        self.commands.append(command)
        now = self.clock.now()
        def put(line):
            self.queue.append((now, line))
        if command == 'OFF':
            self.queue = [(at, line) for at, line in self.queue if not line.startswith('DONE ')]
            self.state, self.active = 'DISARMED', None
            put('OK DISARMED')
        elif command == 'INFO':
            for line in ['FW: 0.1.1', 'END INFO']:
                put(line)
        elif command == 'STATUS':
            if self.state == 'IDLE' and now >= self.until:
                self.state = 'DISARMED'
            en = int(self.state == 'ACTIVE')
            put(f'OK STATE={self.state} SRC_EN={en} SNK_EN={en} FAULT=NONE')
        elif command == 'ADCSTATUS':
            put('OK ADCSTATUS VALID=1 HAS_SAMPLE=1 AGE_MS=0 ERRORS=0 OVR_COUNT=0')
        elif command == 'CURRENT':
            ua = self.active[2] if self.active else 16
            put(f'OK RAW=2 CURRENT_UA={ua} VALID=1 AGE_MS=0')
        elif command == 'SELFTEST':
            put('OK SELFTEST=PASS STATE=DISARMED FAULT=NONE')
        elif command.startswith('ARM '):
            seconds = int(command.split()[1])
            self.until, self.state = now + seconds, 'IDLE'
            put(f'OK ARM_TIMEOUT_S={seconds}')
        elif command.startswith('PAIR '):
            src, snk, duration = map(int, command.split()[1:])
            if self.state != 'IDLE' or now >= self.until:
                put('ERR NOT_ARMED')
                return
            self.id += 1
            ua = {(14, 32): 1033, (14, 33): 886, (14, 34): 794}.get((src, snk), 16)
            self.state, self.active = 'ACTIVE', (src, snk, ua)
            put(f'ACK ID={self.id} SRC={src} SNK={snk} DURATION_MS={duration}')
            self.queue.append((now + duration / 1000,
                               f'DONE ID={self.id} STATE=OFF CURRENT_AVG_UA={ua} CURRENT_MAX_UA={ua + 8} '
                               f'SAMPLES={duration - 1} FAULT=NONE REASON=TIMEOUT'))
        else:
            put('ERR UNKNOWN_COMMAND')
        self.queue.sort(key=lambda item: item[0])

    def read(self, timeout):
        end = self.clock.now() + timeout
        if not self.queue or self.queue[0][0] > end:
            self.clock.sleep(timeout)
            return None
        at, line = self.queue.pop(0)
        self.clock.sleep(at - self.clock.now())
        if line.startswith('DONE '):
            self.state, self.active = 'IDLE', None
        return line

    def close(self):
        self.closed = True


class Results:
    columns = ['source', 'sink', 'command_id', 'duration_ms', 'current_avg_ua', 'current_max_ua',
               'samples', 'reason', 'fault', 'timestamp_utc', 'ack_utc', 'done_utc', 'status',
               'current_candidate', 'simulation', 'error']

    def __init__(self, prefix, metadata):
        prefix = Path(prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        self.paths = [Path(str(prefix) + suffix) for suffix in ('.json', '.csv', '_candidates.csv')]
        # Reserve outputs before touching hardware. Never overwrite previous experiments.
        for path in self.paths:
            if path.exists():
                raise FileExistsError(f'Result already exists: {path}')
        for path in self.paths:
            with path.open('x', encoding='utf-8'):
                pass
        self.data = dict(metadata, started_utc=utc_now(), run_status='PREPARING', records=[], events=[],
                         current_candidates=[], error=None, cleanup_error=None)
        self.save()

    def save(self):
        candidates = [r for r in self.data['records'] if r['current_candidate']]
        self.data['current_candidates'] = candidates
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.paths[0].parent,
                                         suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        try:
            os.replace(temporary, self.paths[0])
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        for path, rows in [(self.paths[1], self.data['records']), (self.paths[2], candidates)]:
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=self.columns)
                writer.writeheader()
                writer.writerows(rows)


class Probe:
    def __init__(self, transport, clock, results, duration_ms=150, pause_ms=500,
                 arm_seconds=60, current_limit_ua=1800, threshold_ua=100, timeout=1.0):
        if not 10 <= duration_ms <= 300 or not 1 <= arm_seconds <= 60:
            raise ValueError('FW bounds: duration 10..300 ms, ARM 1..60 s')
        if not 0 <= threshold_ua < current_limit_ua <= 2000 or not 0 <= pause_ms <= 60000:
            raise ValueError('Invalid current threshold/limit or pause')
        if not math.isfinite(timeout) or not 0.1 <= timeout <= 2:
            raise ValueError('Response timeout must be 0.1..2 seconds')
        self.io, self.clock, self.results = transport, clock, results
        self.duration, self.pause, self.arm = duration_ms, pause_ms, arm_seconds
        self.limit, self.threshold, self.timeout = current_limit_ua, threshold_ua, timeout
        self.row, self.done, self.lease = None, None, 0

    def send(self, command):
        self.results.data['events'].append(dict(timestamp_utc=utc_now(), direction='TX', line=command))
        self.io.send(command)

    def read(self, timeout):
        line = self.io.read(timeout)
        if line:
            self.results.data['events'].append(dict(timestamp_utc=utc_now(), direction='RX', line=line))
        return line

    def consume(self, line):
        if line.startswith('ERR '):
            code = 'ARM_EXPIRED' if 'NOT_ARMED' in line else 'ERROR_DEVICE'
            raise ProbeError(code, line)
        data = fields(line)
        if line.startswith('DONE '):
            if self.row is None or self.row['command_id'] != integer(data, 'ID') or self.done is not None:
                raise ProbeError('ERROR_PROTOCOL', 'Unexpected/duplicate DONE ID')
            self.row.update(done_utc=utc_now(), fault=data.get('FAULT'), reason=data.get('REASON'))
            for field, key in [('current_avg_ua', 'CURRENT_AVG_UA'), ('current_max_ua', 'CURRENT_MAX_UA'), ('samples', 'SAMPLES')]:
                if key in data:
                    self.row[field] = integer(data, key)
            self.done = data
        if data.get('FAULT', 'NONE') != 'NONE':
            raise ProbeError('STOPPED_FAULT', line)
        if line.startswith('OK ADCSTATUS '):
            if integer(data, 'VALID') != 1 or integer(data, 'HAS_SAMPLE') != 1 or integer(data, 'AGE_MS') > 5:
                raise ProbeError('ERROR_ADC', line)
            if integer(data, 'ERRORS') or integer(data, 'OVR_COUNT'):
                raise ProbeError('ERROR_ADC', line)
        if line.startswith('OK RAW='):
            if integer(data, 'VALID') != 1 or integer(data, 'AGE_MS') > 5 or integer(data, 'RAW') >= 4095:
                raise ProbeError('ERROR_ADC', line)
            if integer(data, 'CURRENT_UA') > self.limit:
                raise ProbeError('OVER_LIMIT', line)
        if line.startswith('DONE '):
            if data.get('STATE') != 'OFF' or data.get('REASON') != 'TIMEOUT' or data.get('FAULT') != 'NONE':
                code = 'ARM_EXPIRED' if data.get('REASON') == 'ARM_EXPIRED' else 'ERROR_COMPLETION'
                raise ProbeError(code, line)
            avg, maximum, count = (integer(data, k) for k in ['CURRENT_AVG_UA', 'CURRENT_MAX_UA', 'SAMPLES'])
            if not count or count > self.duration + 1 or avg > maximum:
                raise ProbeError('ERROR_ADC', line)
            if maximum > self.limit or avg > self.limit:
                raise ProbeError('OVER_LIMIT', line)
        return data

    def wait(self, prefix, timeout=None):
        deadline = self.clock.now() + (self.timeout if timeout is None else timeout)
        while self.clock.now() < deadline:
            line = self.read(min(0.02, deadline - self.clock.now()))
            if not line:
                continue
            data = self.consume(line)
            if line.startswith(prefix):
                return data
            if not line.startswith('DONE '):
                raise ProbeError('ERROR_PROTOCOL', f'Unexpected reply: {line}')
        raise ProbeError('ERROR_TIMEOUT', f'Missing reply: {prefix}')

    def exchange(self, command, prefix):
        self.send(command)
        return self.wait(prefix)

    def status(self, expected):
        data = self.exchange('STATUS', 'OK STATE=')
        if data.get('STATE') != expected:
            code = 'ARM_EXPIRED' if expected == 'IDLE' and data.get('STATE') == 'DISARMED' else 'ERROR_STATE'
            raise ProbeError(code, f'Expected {expected}: {data}')
        if integer(data, 'SRC_EN') or integer(data, 'SNK_EN') or data.get('FAULT') != 'NONE':
            raise ProbeError('ERROR_STATE', f'Banks not off: {data}')

    def diagnostics(self):
        self.exchange('ADCSTATUS', 'OK ADCSTATUS ')
        self.exchange('CURRENT', 'OK RAW=')

    def verify_version(self):
        self.send('INFO')
        version, deadline = None, self.clock.now() + self.timeout
        while self.clock.now() < deadline:
            line = self.read(min(0.02, deadline - self.clock.now()))
            if not line:
                continue
            self.consume(line)
            if line == 'END INFO':
                if version != '0.1.1':
                    raise ProbeError('ERROR_VERSION', f'Expected FW 0.1.1, got {version}')
                return
            if line.startswith('FW: '):
                version = line[4:]
            elif ': ' not in line:
                raise ProbeError('ERROR_PROTOCOL', line)
        raise ProbeError('ERROR_TIMEOUT', 'Missing END INFO')

    def require_lease(self, reserve=0):
        if self.clock.now() + reserve >= self.lease:
            raise ProbeError('ARM_EXPIRED', 'ARM lease exhausted; explicit new run required')

    def pair(self, source, sink):
        self.row = dict.fromkeys(Results.columns)
        self.row.update(source=source, sink=sink, duration_ms=self.duration, timestamp_utc=utc_now(),
                        status='NOT_STARTED', current_candidate=False, simulation=self.results.data['simulation'])
        self.done = None
        self.require_lease(self.duration / 1000 + self.timeout + 0.2)
        self.status('IDLE')
        self.diagnostics()
        if self.exchange('SELFTEST', 'OK SELFTEST=')['SELFTEST'] != 'PASS':
            raise ProbeError('ERROR_SELFTEST', 'SELFTEST did not pass')
        self.require_lease(self.duration / 1000 + self.timeout + 0.2)
        self.send(f'PAIR {source} {sink} {self.duration}')
        self.row['status'] = 'RUNNING'
        ack = self.wait('ACK ID=')
        if (integer(ack, 'SRC'), integer(ack, 'SNK'), integer(ack, 'DURATION_MS')) != (source, sink, self.duration):
            raise ProbeError('ERROR_PROTOCOL', 'ACK parameters do not match PAIR')
        self.row.update(command_id=integer(ack, 'ID'), ack_utc=utc_now())
        deadline, monitor = self.clock.now() + self.duration / 1000 + self.timeout, self.clock.now()
        while self.done is None:
            self.require_lease()
            if self.clock.now() >= deadline:
                raise ProbeError('MISSING_DONE', 'DONE not received within bounded timeout')
            if self.clock.now() >= monitor:
                self.exchange('CURRENT', 'OK RAW=')
                if self.done is None:
                    self.exchange('ADCSTATUS', 'OK ADCSTATUS ')
                monitor = self.clock.now() + 0.02
            else:
                line = self.read(min(0.02, deadline - self.clock.now(), monitor - self.clock.now()))
                if line:
                    self.consume(line)
                    if not line.startswith('DONE '):
                        raise ProbeError('ERROR_PROTOCOL', line)
        self.status('IDLE')
        self.diagnostics()
        self.row.update(status='COMPLETED', current_candidate=self.row['current_avg_ua'] > self.threshold)
        self.results.data['records'].append(self.row)
        self.row = None
        self.results.save()

    def pause_between(self):
        until = self.clock.now() + self.pause / 1000
        while self.clock.now() < until:
            self.require_lease()
            self.status('IDLE')
            self.diagnostics()
            self.clock.sleep(min(0.05, max(0, until - self.clock.now())))

    def run(self, pairs):
        code = 0
        try:
            if not self.results.data['simulation'] and not self.results.data.get('operator_confirmed'):
                raise ProbeError('ERROR_CONFIRMATION', 'Operator authorization is required')
            if not pairs or any(not (1 <= s <= 40 and 1 <= t <= 40 and s != t) for s, t in pairs):
                raise ProbeError('ERROR_PLAN', 'Empty/invalid pair plan')
            self.exchange('OFF', 'OK DISARMED')
            self.verify_version()
            self.status('DISARMED')
            self.diagnostics()
            if self.exchange('SELFTEST', 'OK SELFTEST=')['SELFTEST'] != 'PASS':
                raise ProbeError('ERROR_SELFTEST', 'SELFTEST did not pass')
            # arm_seconds is explicit operator authorization in hardware mode. Never re-arm.
            self.lease = self.clock.now() + self.arm
            data = self.exchange(f'ARM {self.arm}', 'OK ARM_TIMEOUT_S=')
            if integer(data, 'ARM_TIMEOUT_S') != self.arm:
                raise ProbeError('ERROR_PROTOCOL', 'Unexpected ARM timeout')
            self.results.data['run_status'] = 'RUNNING'
            for index, (source, sink) in enumerate(pairs):
                self.pair(source, sink)
                if index + 1 < len(pairs):
                    self.pause_between()
            self.results.data['run_status'] = 'COMPLETED'
        except (Exception, KeyboardInterrupt) as exc:
            status = 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else getattr(exc, 'code', 'ERROR_USB' if isinstance(exc, OSError) else 'ERROR_INTERNAL')
            self.results.data.update(run_status=status, error=str(exc) or status)
            if self.row is not None:
                self.row.update(status=status, error=str(exc) or status, current_candidate=False)
                self.results.data['records'].append(self.row)
                self.row = None
            code = 130 if status == 'INTERRUPTED' else 1
        finally:
            # Always attempt OFF before output/close, including KeyboardInterrupt and disk errors.
            try:
                self.send('OFF')
                deadline = self.clock.now() + self.timeout
                acknowledged = False
                while self.clock.now() < deadline:
                    line = self.read(min(0.02, deadline - self.clock.now()))
                    if line == 'OK DISARMED':
                        acknowledged = True
                        break
                if not acknowledged:
                    raise ProbeError('ERROR_OFF', 'OFF acknowledgement missing')
            except (Exception, KeyboardInterrupt) as exc:
                self.results.data['cleanup_error'] = str(exc) or 'OFF interrupted'
                if not code:
                    self.results.data['run_status'] = 'ERROR_OFF'
                    code = 1
            finally:
                try:
                    self.io.close()
                except (Exception, KeyboardInterrupt) as exc:
                    self.results.data['cleanup_error'] = str(exc) or 'USB close interrupted'
                    if not code:
                        self.results.data['run_status'] = 'ERROR_USB'
                        code = 1
                finally:
                    self.results.data['finished_utc'] = utc_now()
                    self.results.save()
        return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    backend = parser.add_mutually_exclusive_group(required=True)
    backend.add_argument('--simulate', action='store_true')
    backend.add_argument('--port')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source', type=int)
    mode.add_argument('--sink', type=int)
    parser.add_argument('--pins', type=pin_list, default=pin_list('1-40'), help='Opposite side: 1-40 or 32,33,34')
    parser.add_argument('--duration-ms', type=int, default=150)
    parser.add_argument('--pause-ms', type=int, default=500)
    parser.add_argument('--arm-seconds', type=int, help='Explicit single ARM, 1..60 seconds; hardware mode requires it')
    parser.add_argument('--confirm-scan', action='store_true', help='Operator checked wiring, U13 OPEN, R1=2700 ohm and authorizes this plan')
    parser.add_argument('--current-limit-ua', type=int, default=1800)
    parser.add_argument('--threshold-ua', type=int, default=100, help='Diagnostic current candidate threshold; does not prove light')
    parser.add_argument('--response-timeout', type=float, default=1.0)
    parser.add_argument('--output', type=Path, help='New output prefix for JSON, CSV and candidates CSV')
    args = parser.parse_args(argv)
    fixed = args.source if args.source is not None else args.sink
    if not 1 <= fixed <= 40:
        parser.error('Fixed pin must be 1..40')
    if args.port and (not args.confirm_scan or args.arm_seconds is None):
        parser.error('Hardware requires --confirm-scan and explicit --arm-seconds; nothing opened')
    arm = args.arm_seconds if args.arm_seconds is not None else 60
    # Validate all bounds before creating files or opening a port.
    results = None
    try:
        Probe(None, None, None, args.duration_ms, args.pause_ms, arm, args.current_limit_ua, args.threshold_ua, args.response_timeout)
    except ValueError as exc:
        parser.error(str(exc))
    pairs = [(fixed, pin) if args.source is not None else (pin, fixed) for pin in args.pins if pin != fixed]
    if not pairs:
        parser.error('Plan contains no distinct pairs')
    prefix = args.output or Path('results') / ('rgb_probe_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    print(f"{'SIMULATION' if args.simulate else 'HARDWARE'}: {len(pairs)} pairs, {args.duration_ms} ms, pause {args.pause_ms} ms, one ARM {arm} s")
    metadata = dict(simulation=args.simulate, firmware_expected='0.1.1', plan=pairs, duration_ms=args.duration_ms,
                    pause_ms=args.pause_ms, arm_seconds=arm, threshold_ua=args.threshold_ua,
                    current_limit_ua=args.current_limit_ua, response_timeout=args.response_timeout,
                    operator_confirmed=args.confirm_scan, port=args.port,
                    optical_observation='NOT_IMPLEMENTED')
    try:
        results = Results(prefix, metadata)
        clock = VirtualClock() if args.simulate else Clock()
        transport = Simulator(clock) if args.simulate else SerialTransport(args.port)
    except (OSError, ImportError) as exc:
        if results is not None:
            results.data.update(run_status='ERROR_USB', error=str(exc), finished_utc=utc_now())
            results.save()
        print(f'Cannot initialize probe: {exc}')
        return 1
    code = Probe(transport, clock, results, args.duration_ms, args.pause_ms, arm,
                 args.current_limit_ua, args.threshold_ua, args.response_timeout).run(pairs)
    print(f"{results.data['run_status']}: {len(results.data['records'])} records; results: {prefix}")
    return code


if __name__ == '__main__':
    raise SystemExit(main())
