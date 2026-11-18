"""Bounded short-PHOTO series on injected CDC only; never hardware tests."""
from collections import Counter
import json
from pathlib import Path
import tempfile
import threading
import unittest
from software.hardware.experiment import Experiment
from software.hardware.scenario import CONDITIONS,SHORT_NAME,short_scenario,Stage
from software.hardware.simulator import SimulatedCDC
from software.hardware.electrical_operations import load_operations,operations_from_probe


class ShortExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def execute(self,config=None,failure=None,hook=None):
        fake=SimulatedCDC(failure=failure,hook=hook);abort=threading.Event()
        engine=Experiment(fake,'SIMULATED',self.root,fake.clock.now_ns,abort=abort)
        config=config or {}
        result=engine.run_sequence(short_scenario(**config),dict.fromkeys(CONDITIONS,True),SHORT_NAME,config)
        return fake,engine,result

    def test_default_30_operations_independent_arm_off_and_exact_pauses(self):
        fake,engine,result=self.execute()
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        measurements=result['measurements'];self.assertEqual(len(measurements),30)
        self.assertEqual(Counter(m['duration_ms'] for m in measurements),{100:10,200:10,300:10})
        self.assertEqual(len([c for c in fake.commands if c.startswith('ARM ')]),30)
        self.assertFalse(any(c.startswith('PAIR') for c in fake.commands))
        self.assertEqual([m['id'] for m in measurements],list(range(1,31)))
        for m in measurements:
            self.assertTrue(m['off_confirmed']);self.assertEqual(m['elapsed_ms'],m['duration_ms'])
            self.assertGreater(m['samples'],0);self.assertLessEqual(m['current_max_ua'],2000)
            self.assertLess(m['tx_ns'],m['ack_ns']);self.assertLess(m['ack_ns'],m['done_ns'])
        pauses=[s for s in result['actual'] if s['color']=='OFF']
        self.assertEqual([p['duration_ms'] for p in pauses],[5000]+[700]*29+[5000])
        for p in pauses:self.assertGreaterEqual(p['end_ns']-p['off_confirmed_ns'],p['duration_ms']*1e6)
        self.assertTrue(result['simulation']);self.assertTrue(result['off_confirmed']);self.assertIsNone(fake.active)
        _,ops=load_operations(engine.journal.path/'session.json');self.assertEqual(len(ops),30)

    def test_marker_has_separate_role_seed_is_reproducible(self):
        config=dict(marker=True,order='shuffled',seed=173,repeats=2)
        first=short_scenario(**config);self.assertEqual(first,short_scenario(**config))
        self.assertNotEqual(first,short_scenario(**dict(config,seed=174)))
        fake,engine,result=self.execute(config)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(result['planned'][1]['role'],'SYNC_MARKER')
        self.assertEqual(result['measurements'][0]['command'],'PHOTO LED49 RED 1000')
        self.assertEqual(result['planned'][2]['duration_ms'],2000)
        self.assertEqual(Counter(m['duration_ms'] for m in result['measurements'][1:]),{100:2,200:2,300:2})

    def test_all_short_failures_stop_without_retry_and_keep_remaining_plan(self):
        for failure in ('adc_active','fault','usb','missing','id','noack','current','elapsed','samples','no_current'):
            with self.subTest(failure=failure):
                fake,engine,result=self.execute(dict(repeats=1),failure)
                self.assertEqual(result['status'],'FAILED',result)
                self.assertEqual(len([c for c in fake.commands if c.startswith('PHOTO ')]),1)
                self.assertEqual(len([c for c in fake.commands if c.startswith('ARM ')]),1)
                saved=json.loads((engine.journal.path/'session.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['status'],'FAILED');self.assertEqual(len(saved['measurements']),1)
                _,ops=load_operations(engine.journal.path/'session.json')
                self.assertEqual([o['electrical_status'] for o in ops],['FAILED','NOT_EXECUTED','NOT_EXECUTED'])

    def test_off_interrupts_middle_of_series_and_no_later_photo(self):
        fake=SimulatedCDC();abort=threading.Event()
        def hook(device):
            if device.id==4 and device.active and device.clock.ns-device.active['start_ns']>25_000_000:abort.set()
        fake.hook=hook;engine=Experiment(fake,'SIM',self.root,fake.clock.now_ns,abort=abort)
        result=engine.run_sequence(short_scenario(),dict.fromkeys(CONDITIONS,True),SHORT_NAME)
        self.assertEqual(result['status'],'ABORTED');self.assertTrue(result['off_confirmed'])
        self.assertEqual(len(result['measurements']),4);self.assertIsNone(fake.active)
        self.assertEqual(result['measurements'][-1]['status'],'ABORTED')
        self.assertIn('REASON=OFF',result['measurements'][-1]['done'])

    def test_ack_wrong_parameters_and_missing_off_stop_before_next_operation(self):
        for wrong in ('ACK','OFF'):
            fake=SimulatedCDC();original=fake.send
            def send(command):
                original(command)
                if command.startswith('PHOTO ') and wrong=='ACK':fake.queue[-1]=fake.queue[-1].replace('DURATION_MS=100','DURATION_MS=200')
                if command.startswith('PHOTO ') and wrong=='OFF':fake.failure='no_off'
            fake.send=send;engine=Experiment(fake,'SIM',self.root,fake.clock.now_ns)
            result=engine.run_sequence(short_scenario(repeats=1),dict.fromkeys(CONDITIONS,True),SHORT_NAME,dict(repeats=1))
            self.assertEqual(result['status'],'FAILED');self.assertEqual(len(result['measurements']),1)

    def test_no_confirmation_or_modified_plan_never_sends_any_command(self):
        fake=SimulatedCDC();engine=Experiment(fake,'SIM',self.root,fake.clock.now_ns)
        with self.assertRaises(ValueError):engine.run_sequence(short_scenario(),{},SHORT_NAME)
        stages=short_scenario();stages[1]=Stage('RED',1000,'SHORT_PULSE')
        with self.assertRaises(ValueError):engine.run_sequence(stages,dict.fromkeys(CONDITIONS,True),SHORT_NAME)
        for config in (dict(durations=[10]),dict(repeats=0),dict(color='WHITE'),dict(seed=-1)):
            with self.assertRaises(ValueError):short_scenario(**config)
        self.assertEqual(fake.commands,[])

    def test_future_pair_adapter_retains_missing_timing_and_never_assigns_pcb_id(self):
        rows=operations_from_probe(dict(simulation=True,records=[dict(source=14,sink=32,command_id=7,
            duration_ms=150,status='COMPLETED',current_avg_ua=1033,timestamp_utc='2026-11-18T00:00:00Z')]))
        self.assertEqual(rows[0]['operation_id'],7);self.assertIsNone(rows[0]['host_ack_s'])
        self.assertIsNone(rows[0]['pcb_led_id']);self.assertTrue(rows[0]['simulation'])
        with self.assertRaises(ValueError):operations_from_probe(dict(records=[dict(duration_ms=301)]))
