"""Simulated CDC acceptance: virtual 31-second scenario, no hardware access."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from software.hardware.experiment import Experiment
from software.hardware.journal import Journal
from software.hardware.scenario import CONDITIONS, scenario
from software.hardware.simulator import SimulatedCDC
from software.hardware.video_link import attach_video
from test_video_source import make_video


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def execute(self, failure=None, hook=None, stages=None):
        fake = SimulatedCDC(failure=failure, hook=hook)
        abort = threading.Event(); updates = []
        engine = Experiment(fake, 'SIMULATED', self.root, fake.clock.now_ns, updates.append, abort)
        result = engine.run_sequence(stages or scenario(), dict.fromkeys(CONDITIONS, True))
        return fake, engine, result, updates

    def test_default_sequence_arm_ids_currents_timing_and_final_safe_state(self):
        fake, engine, result, _ = self.execute()
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertEqual([s['color'] for s in result['actual']], ['OFF','RED','OFF','GREEN','OFF','BLUE','OFF'])
        self.assertEqual(sum(p['duration_ms'] for p in result['planned']), 31000)
        photos = [c for c in fake.commands if c.startswith('PHOTO')]
        self.assertEqual(photos, [f'PHOTO LED49 {color} 5000' for color in ('RED','GREEN','BLUE')])
        self.assertEqual([c for c in fake.commands if c.startswith('ARM')], ['ARM 10']*3)
        for command in photos:
            i = fake.commands.index(command); self.assertEqual(fake.commands[i-1], 'ARM 10')
        self.assertEqual([m['id'] for m in result['measurements']], [1,2,3])
        self.assertEqual([int(m['elapsed_ms']) for m in result['measurements']], [5000]*3)
        self.assertEqual([int(m['current_avg_ua']) for m in result['measurements']], [1035,886,797])
        for stage in result['actual']:
            self.assertGreaterEqual(stage['host_elapsed_ms'], stage['duration_ms'])
            if stage['color'] == 'OFF':
                self.assertGreaterEqual(stage['end_ns']-stage['off_confirmed_ns'], stage['duration_ms']*1_000_000)
        self.assertTrue(result['off_confirmed']); self.assertEqual(fake.state,'DISARMED'); self.assertIsNone(fake.active)
        self.assertEqual(fake.commands[-2:], ['OFF','STATUS'])
        self.assertTrue(all((engine.journal.path/name).exists() for name in ('session.json','events.jsonl','measurements.csv','report.md')))
        events = [json.loads(line) for line in (engine.journal.path/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all('monotonic_ns' in e and 'utc' in e for e in events))
        self.assertEqual(result['synchronization']['status'], 'UNALIGNED')

    def test_diagnostics_never_arm_or_light(self):
        fake=SimulatedCDC(); engine=Experiment(fake,'SIM',self.root,fake.clock.now_ns)
        engine.preflight()
        self.assertEqual(fake.commands, ['PING','INFO','STATUS','ADCSTATUS','SELFTEST'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_physical_confirmation_and_invalid_controls(self):
        fake=SimulatedCDC(); engine=Experiment(fake,'SIM',self.root,fake.clock.now_ns)
        with self.assertRaises(ValueError): engine.run_sequence(conditions={})
        for duration in (99,10001,True,1.5):
            with self.assertRaises(ValueError): scenario(photo_ms=duration)
        self.assertEqual(fake.commands, [])

    def test_preflight_failures_do_not_enable(self):
        for failure in ('version','capability','adc','stale','ovr','selftest','active','en'):
            with self.subTest(failure=failure):
                fake,engine,result,_=self.execute(failure)
                self.assertEqual(result['status'],'FAILED')
                self.assertFalse(any(c.startswith(('ARM','PHOTO')) for c in fake.commands))
                self.assertIn('OFF',fake.commands)
                self.assertEqual(json.loads((engine.journal.path/'session.json').read_text(encoding='utf-8'))['status'],'FAILED')

    def test_failures_stop_after_first_photo_without_rearm_and_preserve_partial_log(self):
        for failure in ('id','noack','missing','current','low_current','samples','elapsed','expired','fault','usb','adc_active','no_current'):
            with self.subTest(failure=failure):
                fake,engine,result,_=self.execute(failure)
                self.assertEqual(result['status'],'FAILED',result)
                self.assertEqual(len([c for c in fake.commands if c.startswith('PHOTO')]),1)
                self.assertEqual(len([c for c in fake.commands if c.startswith('ARM')]),1)
                self.assertNotIn('CLEARFAULT',fake.commands)
                self.assertTrue((engine.journal.path/'events.jsonl').stat().st_size>0)
                self.assertEqual(result['measurements'][0]['status'],'FAILED')
                if failure=='usb': self.assertFalse(result['off_confirmed'])

    def test_abort_during_photo_sends_off_before_done_or_timeout(self):
        fake=SimulatedCDC(); abort=threading.Event()
        def hook(device):
            if device.active and device.clock.ns-device.active['start_ns']>=50_000_000: abort.set()
        fake.hook=hook
        engine=Experiment(fake,'SIM',self.root,fake.clock.now_ns,abort=abort)
        result=engine.run_sequence(conditions=dict.fromkeys(CONDITIONS,True))
        self.assertEqual(result['status'],'ABORTED');self.assertTrue(result['off_confirmed'])
        photo=next(t for t,c in fake.command_times if c.startswith('PHOTO'))
        off=next(t for t,c in fake.command_times if t>photo and c=='OFF')
        self.assertLess(off-photo,150_000_000)
        self.assertEqual(len([c for c in fake.commands if c.startswith('PHOTO')]),1)
        self.assertIn('REASON=OFF',result['measurements'][0]['done'])

    def test_ctrl_c_also_stops(self):
        _,_,result,_=self.execute('ctrlc')
        self.assertEqual(result['status'],'ABORTED');self.assertTrue(result['off_confirmed'])

    def test_current_deviation_is_logged_without_false_fault(self):
        _,_,result,_=self.execute('deviation')
        self.assertEqual(result['status'],'COMPLETED')
        self.assertTrue(any(m['warning'] for m in result['measurements']))

    def test_unconfirmed_off_blocks_first_photo(self):
        fake,_,result,_=self.execute('no_off')
        self.assertEqual(result['status'],'FAILED');self.assertFalse(result['off_confirmed'])
        self.assertFalse(any(c.startswith('PHOTO') for c in fake.commands))

    def test_repeated_sessions_do_not_overwrite(self):
        _,a,_,_=self.execute(stages=scenario(100,100,100,100))
        original=(a.journal.path/'session.json').read_bytes()
        _,b,_,_=self.execute(stages=scenario(100,100,100,100))
        self.assertNotEqual(a.journal.path,b.journal.path)
        self.assertEqual((a.journal.path/'session.json').read_bytes(),original)

    def test_post_run_diagnostics_and_disconnect_do_not_append_to_closed_session(self):
        fake,engine,_,_=self.execute(stages=scenario(100,100,100,100))
        path=engine.journal.path
        original={p.name:p.read_bytes() for p in path.iterdir()}
        engine.preflight();engine.safe_off()
        engine.run_sequence(stages=scenario(100,100,100,100),conditions=dict.fromkeys(CONDITIONS,True))
        self.assertNotEqual(path,engine.journal.path)
        self.assertEqual({p.name:p.read_bytes() for p in path.iterdir()},original)

    def test_disk_failure_still_turns_off(self):
        fake=SimulatedCDC();engine=Experiment(fake,'SIM',self.root,fake.clock.now_ns)
        original=Journal.event
        def event(journal,*args,**kwargs):
            if fake.active:raise OSError('Disk full')
            return original(journal,*args,**kwargs)
        with patch.object(Journal,'event',event):
            result=engine.run_sequence(conditions=dict.fromkeys(CONDITIONS,True))
        self.assertEqual(result['status'],'FAILED');self.assertTrue(result['off_confirmed']);self.assertIsNone(fake.active)

    def test_import_mp4_replacement_keeps_external_media_and_unknown_alignment(self):
        _,engine,_,_=self.execute(stages=scenario(100,100,100,100))
        video=self.root/'capture.mp4';make_video(video)
        original=video.read_bytes(); meta=attach_video(engine.journal.path,video)
        self.assertEqual((meta['width'],meta['height']),(1200,700))
        self.assertEqual(meta['fps'],10);self.assertIsNotNone(meta['first_frame_pts'])
        attach_video(engine.journal.path,video)
        data=json.loads((engine.journal.path/'session.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['video_history']),2);self.assertIsNone(data['synchronization']['offset_ms'])
        self.assertEqual(video.read_bytes(),original)
        self.assertFalse(list(engine.journal.path.glob('*.mp4')))
