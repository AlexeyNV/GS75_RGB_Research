from pathlib import Path
import tempfile
import threading
import time
import unittest
import numpy as np
import cv2
from software.vision.frame_profile import FrameProfile,stats,STAGES
from software.vision.perf_fixture import generate_sequence
from software.vision.pts_video import SequentialVideoReader
from software.vision.off_background import build_off,from_photo,update_off
from software.vision.video_engine import VideoEngine,EventAggregator
from software.vision.video_benchmark import benchmark,compare_quality
from software.vision.calibration import load
from software.vision.project_storage import ROOT,read_image,image_hash


class PerfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.video,cls.data,cls.truth=generate_sequence(cls.root/'dataset',(1280,720))
        cls.off=build_off(cls.video,cls.data,threading.Event())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_exclusive_nanosecond_stages_and_percentiles(self):
        p=FrameProfile()
        with p.activate(),p.stage('FRAME_TOTAL'):
            with p.stage('LED_DETECTION'):
                with p.stage('COLOR_CLASSIFICATION'):time.sleep(.003)
        m=p.milliseconds();self.assertGreater(m['COLOR_CLASSIFICATION'],1)
        self.assertLess(m['LED_DETECTION'],m['COLOR_CLASSIFICATION'])
        s=stats([1,2,3,100]);self.assertEqual(s['p50_ms'],2.5);self.assertGreater(s['p99_ms'],s['p95_ms'])
        self.assertEqual(stats([])['count'],0)

    def test_auto_off_observations_geometry_and_bounded_storage(self):
        m=self.off.metadata
        self.assertGreaterEqual(m['retained_frames'],3);self.assertLessEqual(m['retained_frames'],5)
        self.assertEqual(m['source'],'automatic_video_median');self.assertGreater(m['valid_fraction'],.1)
        self.assertTrue(all(a['registration']['status']=='REGISTERED' for a in m['accepted']))
        self.assertTrue(np.any(self.off.mask==0));self.assertFalse(np.all(self.off.image==0))
        self.assertEqual(self.off.calibration_version,self.data['calibration_version'])
        self.assertEqual(len(self.data['leds']),1)

    def test_true_pts_and_offline_sequential_decoding(self):
        r=SequentialVideoReader();r.open(self.video)
        try:
            _,a=r.frame(0);_,b=r.frame(1)
            self.assertEqual(a['timestamp_source'],'pts');self.assertGreater(b['timestamp_ms'],a['timestamp_ms'])
            with self.assertRaises(ValueError):r.frame(5)
        finally:r.close()
        self.assertIsNone(r.container)

    def test_glowing_interval_and_missing_geometry_refuse_off(self):
        with self.assertRaisesRegex(ValueError,'OFF needs'):
            build_off(self.video,self.data,threading.Event(),start_s=2.,duration_s=.2)

    def test_update_is_explicit_and_never_during_light(self):
        with self.assertRaises(ValueError):update_off(self.off,self.off)
        with self.assertRaises(ValueError):update_off(self.off,self.off,True,True)
        m=update_off(self.off,self.off,True,False)
        self.assertTrue(np.array_equal(m.image,self.off.image));self.assertTrue(np.array_equal(m.mask,self.off.mask))

    def test_dark_moving_object_is_not_absorbed_into_off(self):
        path=self.root/'occlusion.mp4';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),30,(1280,720))
        reader=SequentialVideoReader();reader.open(self.video)
        try:
            for i in range(60):
                image,_=reader.frame(i)
                if i>=10:cv2.rectangle(image,(500,260),(900,480),(0,0,0),-1)
                writer.write(image)
        finally:reader.close();writer.release()
        with self.assertRaisesRegex(ValueError,'MOVING_OBJECT'):
            build_off(path,self.data,threading.Event())

    def test_variable_frame_pts_remain_variable(self):
        from fractions import Fraction
        import av
        path=self.root/'vfr.mp4'
        with av.open(str(path),'w') as container:
            stream=container.add_stream('mpeg4',rate=30);stream.width=120;stream.height=70;stream.pix_fmt='yuv420p'
            for pts in (0,1,3,6):
                frame=av.VideoFrame.from_ndarray(np.full((70,120,3),70,np.uint8),format='bgr24')
                frame.pts=pts;frame.time_base=Fraction(1,30)
                for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        reader=SequentialVideoReader();reader.open(path)
        try:times=[reader.frame(i)[1]['timestamp_ms'] for i in range(4)]
        finally:reader.close()
        self.assertGreater(np.ptp(np.diff(times)),20)
        self.assertAlmostEqual(times[-1]-times[0],200,delta=2)

    def test_architecture_quality_rgb_and_marker_loss(self):
        reader=SequentialVideoReader();reader.open(self.video);selected={}
        try:
            for i in range(106):
                image,info=reader.frame(i)
                if i in (5,65,85,88,105):selected[i]=image
        finally:reader.close()
        for variant in VideoEngine.VARIANTS:
            engine=VideoEngine(self.data,self.off,variant)
            for index,image in selected.items():
                result=engine.process(image)
                if index==85:self.assertEqual(result['registration_status'],'FAILED');continue
                records=result['records'];self.assertEqual(len(records),1)
                if index==5:self.assertEqual(records[0]['status'],'OFF')
                else:self.assertEqual(records[0]['color'],{65:'RED',88:'GREEN',105:'BLUE'}[index])

    def test_report_counts_warmup_separate_and_no_silent_skip(self):
        output=self.root/'report'
        report=benchmark(self.video,self.data,output,off=self.off,variants=('B_CACHED_FULL','C_HYBRID'),limit=6,warmup=2)
        for run in report['runs']:
            self.assertEqual([r['frame_index'] for r in run['frames']],list(range(6)))
            self.assertEqual(run['warmup_frames'],2);self.assertEqual(run['lost_frames'],0)
            self.assertEqual(set(STAGES)-set(run['stages']),set())
        self.assertEqual(report['quality']['C_HYBRID']['verdict'],'PASS')
        self.assertTrue((output/'frames.csv').exists());self.assertTrue((output/'benchmark.md').exists())
        with self.assertRaises(FileExistsError):benchmark(self.video,self.data,output,off=self.off)

    def test_event_confirmation_and_invalid_geometry_breaks(self):
        a=EventAggregator();on=dict(registration_status='REGISTERED',analysis_status='ANALYZED',records=[dict(led_id='LED49',status='ON',color='RED')])
        a.feed(on,10,0);self.assertFalse(a.events()[0]['confirmed'])
        a.feed(on,45,1);self.assertTrue(a.events()[0]['confirmed'])
        a.feed(dict(registration_status='FAILED',analysis_status='FAILED',records=[]),70,2)
        self.assertFalse(a.active);self.assertEqual(a.events()[0]['end_ms'],45)


@unittest.skipUnless(all((ROOT/'data'/f'{name}.jpg').is_file() for name in ('off','red','green','blue')) and (ROOT/'config/gs75_board_calibration.json').is_file(),'Real local photographs absent')
class RealPerfRegression(unittest.TestCase):
    def test_cached_hybrid_preserve_real_rgb_and_inputs(self):
        paths=[ROOT/'data'/f'{n}.jpg' for n in ('off','red','green','blue')]+[ROOT/'config/gs75_board_calibration.json']
        hashes=[image_hash(p) for p in paths];data=load(paths[-1]);off=from_photo(read_image(paths[0]),data)
        for variant in ('B_CACHED_FULL','C_HYBRID'):
            engine=VideoEngine(data,off,variant)
            for name,path in zip(('RED','GREEN','BLUE'),paths[1:4]):
                r=engine.process(read_image(path));self.assertEqual(r['registration_status'],'REGISTERED')
                self.assertEqual([(v['led_id'],v['status'],v['color']) for v in r['records']],[('LED49','ON',name)])
        self.assertEqual(hashes,[image_hash(p) for p in paths])
