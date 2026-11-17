"""Optional acceptance on the user's MP4. Explicitly skipped when media is absent."""
from copy import deepcopy
import threading
import unittest
from software.vision.project_storage import ROOT,image_hash
from software.vision.calibration import load
from software.vision.off_background import build_off
from software.vision.pts_video import SequentialVideoReader
from software.vision.video_engine import VideoEngine

VIDEO=ROOT/'data/VID_20261117_101549.mp4'
MAP=ROOT/'config/gs75_board_calibration.json'


@unittest.skipUnless(VIDEO.is_file() and MAP.is_file(),'Real MP4/calibration absent; synthetic tests do not replace real acceptance')
class RealVideoOffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hashes=[image_hash(VIDEO),image_hash(MAP)]
        cls.cal=load(MAP);cls.off=build_off(VIDEO,cls.cal,threading.Event())

    @classmethod
    def tearDownClass(cls):
        if cls.hashes!=[image_hash(VIDEO),image_hash(MAP)]:raise AssertionError('Original media/map changed')

    def test_real_initial_off_covers_led49_without_accepting_first_uncovered_frame(self):
        m=self.off.metadata
        self.assertEqual(m['status'],'READY');self.assertEqual(m['retained_frames'],5)
        self.assertGreaterEqual(m['coverage']['known_leds']['LED49'],.9)
        # Different valid RANSAC supports can cover frame zero; never hardcode its rejection.
        for row in m['candidates']:
            if row['reason']=='ELIGIBLE':self.assertGreaterEqual(row['roi_min'],.9)
            if row.get('roi_min',1)<.9 and row['reason']=='ELIGIBLE':self.fail('Uncovered candidate accepted')
        self.assertEqual(m['video']['rotation_degrees'],-90)
        self.assertEqual((m['video']['width'],m['video']['height']),(1080,1920))
        self.assertEqual(m['video']['frame_count'],922)

    def test_real_RGB_known_and_blind_discovery_at_visible_frames(self):
        blind=deepcopy(self.cal);blind['leds']=[]
        known=VideoEngine(self.cal,self.off);discover=VideoEngine(blind,self.off,mode='DISCOVER')
        reader=SequentialVideoReader();reader.open(VIDEO);frames={150:'RED',400:'GREEN',650:'BLUE'}
        try:
            for i in range(651):
                image,info=reader.frame(i)
                if i not in frames:continue
                result=known.process(image)
                self.assertEqual([(r['led_id'],r['status'],r['color']) for r in result['records']],[('LED49','ON',frames[i])])
                result=discover.process(image)
                candidates=[r for r in result['records'] if (r['x_ref_px']-578.1096)**2+(r['y_ref_px']-1379.293)**2<60**2]
                self.assertTrue(any(r['status']=='CANDIDATE' and r['color']==frames[i] and r['led_id'] is None for r in candidates))
        finally:reader.close()
