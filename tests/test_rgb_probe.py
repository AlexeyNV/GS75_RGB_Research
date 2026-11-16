"""Protocol-level tests of the actual probe, without serial ports or power."""
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rgb_probe', ROOT / 'tools/rgb_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Injected(probe.Simulator):
    def __init__(self, clock, failure):
        super().__init__(clock)
        self.failure = failure

    def send(self, command):
        if command == 'CURRENT' and self.state == 'ACTIVE':
            if self.failure == 'usb':
                raise OSError('USB disconnected')
            if self.failure == 'interrupt':
                raise KeyboardInterrupt()
        super().send(command)
        if command == 'OFF' and self.failure == 'off_ack' and self.commands.count('OFF') > 1:
            self.queue = []
        if command.startswith('PAIR '):
            if self.failure == 'missing_done':
                self.queue = [(t, line) for t, line in self.queue if not line.startswith('DONE ')]
            changes = {'wrong_id': ('DONE ID=1 ', 'DONE ID=99 '),
                       'fault': ('FAULT=NONE REASON=TIMEOUT', 'FAULT=OVERCURRENT REASON=OVERCURRENT'),
                       'high_done': ('CURRENT_MAX_UA=1041', 'CURRENT_MAX_UA=1900'),
                       'off_reason': ('REASON=TIMEOUT', 'REASON=OFF'),
                       'no_samples': ('SAMPLES=149 ', ''),
                       'zero_samples': ('SAMPLES=149 ', 'SAMPLES=0 ')}
            if self.failure in changes:
                old, new = changes[self.failure]
                self.queue = [(t, line.replace(old, new)) for t, line in self.queue]
        if command == 'ADCSTATUS':
            if self.failure in ['stale', 'adc_errors'] or (self.failure == 'active_adc' and self.state == 'ACTIVE'):
                old, new = ('AGE_MS=0', 'AGE_MS=6') if self.failure == 'stale' else ('VALID=1', 'VALID=0')
                if self.failure == 'adc_errors':
                    old, new = 'ERRORS=0', 'ERRORS=1'
                self.queue = [(t, line.replace(old, new)) for t, line in self.queue]
        if command == 'CURRENT' and self.state == 'ACTIVE' and self.failure == 'high_live':
            self.queue = [(t, line.replace('CURRENT_UA=1033', 'CURRENT_UA=1900')) for t, line in self.queue]
        if command == 'STATUS' and self.id == 1 and self.state == 'IDLE' and self.failure == 'expired':
            self.queue = [(t, line.replace('STATE=IDLE', 'STATE=DISARMED')) for t, line in self.queue]


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / 'probe'

    def run_probe(self, pairs=None, failure=None, **options):
        clock = probe.VirtualClock()
        io = Injected(clock, failure)
        result = probe.Results(self.prefix, {'simulation': True})
        runner = probe.Probe(io, clock, result, **options)
        code = runner.run(pairs or [(14, 32), (14, 33), (14, 34)])
        data = json.loads(Path(str(self.prefix) + '.json').read_text(encoding='utf-8'))
        self.assertEqual(io.commands[-1], 'OFF')
        self.assertTrue(io.closed)
        self.assertEqual(io.state, 'DISARMED')
        self.assertLessEqual(sum(c.startswith('ARM ') for c in io.commands), 1)
        return code, data, io

    def test_led49_fixture_and_exports(self):
        code, data, io = self.run_probe()
        self.assertEqual(code, 0)
        self.assertEqual(data['run_status'], 'COMPLETED')
        self.assertEqual([r['current_avg_ua'] for r in data['records']], [1033, 886, 794])
        self.assertEqual([r['command_id'] for r in data['records']], [1, 2, 3])
        for row in data['records']:
            self.assertTrue(row['simulation'])
            self.assertEqual(row['duration_ms'], 150)
            self.assertEqual(row['samples'], 149)
            self.assertEqual(row['fault'], 'NONE')
            self.assertEqual(row['reason'], 'TIMEOUT')
            self.assertTrue(row['timestamp_utc'] and row['ack_utc'] and row['done_utc'])
        for suffix in ['.csv', '_candidates.csv']:
            with Path(str(self.prefix) + suffix).open(encoding='utf-8', newline='') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 3)
        first_pair = next(i for i, c in enumerate(io.commands) if c.startswith('PAIR '))
        for command in ['STATUS', 'ADCSTATUS', 'CURRENT', 'SELFTEST', 'ARM 60']:
            self.assertIn(command, io.commands[:first_pair])

    def test_fixed_sink_and_current_threshold(self):
        code, data, _ = self.run_probe([(14, 32), (13, 32)], threshold_ua=1000)
        self.assertEqual(code, 0)
        self.assertEqual([(r['source'], r['sink']) for r in data['current_candidates']], [(14, 32)])
        self.assertEqual(len(data['records']), 2)

    def test_full_source14_simulation(self):
        code, data, _ = self.run_probe([(14, p) for p in range(1, 41) if p != 14])
        self.assertEqual(code, 0)
        self.assertEqual(len(data['records']), 39)
        self.assertEqual([r['sink'] for r in data['current_candidates']], [32, 33, 34])

    def test_failures_stop_before_second_pair_and_attempt_off(self):
        expected = {'usb': 'ERROR_USB', 'interrupt': 'INTERRUPTED', 'missing_done': 'MISSING_DONE',
                    'wrong_id': 'ERROR_PROTOCOL', 'fault': 'STOPPED_FAULT', 'high_live': 'OVER_LIMIT',
                    'high_done': 'OVER_LIMIT', 'active_adc': 'ERROR_ADC', 'off_reason': 'ERROR_COMPLETION',
                    'no_samples': 'ERROR_PROTOCOL', 'zero_samples': 'ERROR_ADC'}
        for failure, status in expected.items():
            with self.subTest(failure=failure):
                self.prefix = Path(self.temp.name) / failure
                code, data, io = self.run_probe(failure=failure)
                self.assertNotEqual(code, 0)
                self.assertEqual(data['run_status'], status)
                self.assertEqual(len(data['records']), 1)
                self.assertEqual(data['records'][0]['status'], status)
                self.assertEqual(sum(c.startswith('PAIR ') for c in io.commands), 1)

    def test_bad_adc_refuses_arm(self):
        for failure in ['stale', 'adc_errors']:
            self.prefix = Path(self.temp.name) / failure
            code, data, io = self.run_probe(failure=failure)
            self.assertNotEqual(code, 0)
            self.assertEqual(data['run_status'], 'ERROR_ADC')
            self.assertFalse(any(c.startswith(('ARM ', 'PAIR ')) for c in io.commands))

    def test_arm_expiry_never_rearms(self):
        code, data, io = self.run_probe(arm_seconds=2, pause_ms=3000)
        self.assertEqual(code, 1)
        self.assertEqual(data['run_status'], 'ARM_EXPIRED')
        self.assertEqual(sum(c.startswith('PAIR ') for c in io.commands), 1)

    def test_device_disarmed_during_scan(self):
        code, data, _ = self.run_probe(failure='expired')
        self.assertEqual(code, 1)
        self.assertEqual(data['run_status'], 'ARM_EXPIRED')

    def test_off_ack_missing_is_not_success(self):
        code, data, _ = self.run_probe(failure='off_ack')
        self.assertEqual(code, 1)
        self.assertEqual(data['run_status'], 'ERROR_OFF')
        self.assertIn('acknowledgement', data['cleanup_error'])

    def test_public_runner_requires_hardware_confirmation(self):
        clock = probe.VirtualClock()
        io = probe.Simulator(clock)
        results = probe.Results(self.prefix, {'simulation': False, 'operator_confirmed': False})
        code = probe.Probe(io, clock, results).run([(14, 32)])
        self.assertEqual(code, 1)
        self.assertEqual(results.data['run_status'], 'ERROR_CONFIRMATION')
        self.assertEqual(io.commands, ['OFF'])

    def test_serial_fragmentation_and_coalesced_done(self):
        class Port:
            timeout = 0
            def __init__(self):
                self.chunks = [b'ACK ID=', b'1\r\nDONE ID=1\nOK DISARMED\n']
            def read(self, size):
                return self.chunks.pop(0) if self.chunks else b''
            def write(self, data):
                return len(data) - 1
        io = probe.SerialTransport.__new__(probe.SerialTransport)
        io.port, io.partial = Port(), bytearray()
        self.assertIsNone(io.read(.02))
        self.assertEqual(io.read(.02), 'ACK ID=1')
        self.assertEqual(io.read(.02), 'DONE ID=1')
        self.assertEqual(io.read(.02), 'OK DISARMED')
        with self.assertRaises(OSError):
            io.send('PAIR 14 32 150')
        io.partial = bytearray(b'\xff\n')
        with self.assertRaises(probe.ProbeError):
            io.read(.02)

    def test_validation_and_no_overwrite(self):
        for options in [{'duration_ms': 0}, {'duration_ms': 301}, {'current_limit_ua': 2001},
                        {'arm_seconds': 61}, {'pause_ms': -1}, {'timeout': float('nan')}]:
            with self.assertRaises(ValueError):
                probe.Probe(None, None, None, **options)
        probe.Results(self.prefix, {'simulation': True})
        content = Path(str(self.prefix) + '.json').read_bytes()
        with self.assertRaises(FileExistsError):
            probe.Results(self.prefix, {})
        self.assertEqual(content, Path(str(self.prefix) + '.json').read_bytes())
        self.assertEqual(probe.pin_list('1-3,2,40'), [1, 2, 3, 40])

    def test_cli_requires_explicit_hardware_authorization(self):
        script = str(ROOT / 'tools/rgb_probe.py')
        for args in [['--port', 'COM_FAKE', '--source', '14'],
                     ['--port', 'COM_FAKE', '--source', '14', '--confirm-scan']]:
            process = subprocess.run([sys.executable, script, *args], capture_output=True, text=True)
            self.assertEqual(process.returncode, 2)
            self.assertIn('--arm-seconds', process.stderr)


    def test_pair_protocol_supports_new_photo_firmware(self):
        for version in ('0.1.1','0.1.2','0.1.3'):
            clock=probe.VirtualClock()
            io=probe.Simulator(clock)
            original=io.send
            def send(command):
                original(command)
                if command=='INFO':
                    io.queue=[(t,line.replace('FW: 0.1.1','FW: '+version)) for t,line in io.queue]
            io.send=send
            result=probe.Results(Path(self.temp.name)/version, {'simulation':True})
            runner=probe.Probe(io,clock,result)
            if version=='0.1.3':
                with self.assertRaises(probe.ProbeError): runner.verify_version()
            else:
                runner.verify_version()
            # No ARM/PAIR is sent during version detection.
            self.assertEqual(io.commands,['INFO'])


if __name__ == '__main__':
    unittest.main()
