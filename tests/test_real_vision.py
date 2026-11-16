"""Optional local real-data tests; missing private photos are explicit skips."""
import hashlib
from pathlib import Path
import unittest
from software.vision.calibration import load
from software.vision.led_detection import analyze_paths

ROOT=Path(__file__).resolve().parents[1]
FILES=[ROOT/p for p in ('config/gs75_board_calibration.json','data/off.jpg','data/red.jpg','data/reference/gs75_rgb_off.jpg')]


@unittest.skipUnless(all(p.exists() for p in FILES),'Real operator photos / calibration absent; no synthetic substitution')
class RealVisionTests(unittest.TestCase):
    def test_actual_off_red_and_read_only_inputs(self):
        hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in FILES]
        a=analyze_paths(load(FILES[0]),FILES[1],FILES[2],mode='KNOWN_LEDS')
        self.assertEqual(a.result['registration_status'],'REGISTERED')
        self.assertEqual([(r['led_id'],r['color']) for r in a.result['known_leds'] if r['status']=='ON'],[('LED49','RED')])
        r=a.result['known_leds'][0]
        self.assertGreater(r['roi_coverage'],.9)
        self.assertLess(abs(r['signal_x_ref_px']-r['x_ref_px']),r['roi_radius_px'])
        self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).hexdigest() for p in FILES])

    def test_actual_off_off_has_no_new_light(self):
        a=analyze_paths(load(FILES[0]),FILES[1],FILES[1])
        self.assertEqual(a.result['analysis_status'],'ANALYZED')
        self.assertEqual(a.result['detections'],[])
        self.assertTrue(all(r['status']=='OFF' for r in a.result['known_leds']))
