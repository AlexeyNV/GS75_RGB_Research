"""OFF gates on independently registered synthetic images, with controlled defects."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import av
import cv2
import numpy as np
from software.vision.off_background import build_off
from software.vision.off_diagnostics import OffBuildError,quality_maps,masked_median_tile
from software.vision.pts_video import SequentialVideoReader
from software.vision.calibration import create,Document
from software.vision.project_storage import write_image
from software.vision.research_project import Cancelled
from software.vision.video_engine import EventAggregator
from vision_fixtures import board,illuminate


class ArrayReader:
    images=[]
    def open(self,path):self.index=0;self.count=len(self.images);return dict(frame_count=self.count,fps=30)
    def frame(self,index):
        if index>=len(self.images):raise StopIteration()
        return self.images[index],dict(frame_index=index,timestamp_ms=index*1000/30,estimated_ms=index*1000/30,pts=index,time_base='1/30')
    def close(self):pass


class RobustOffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.base=board()
        for y in range(250,460,45):cv2.putText(self.base,'LED49 WHITE SILK',(260,y),cv2.FONT_HERSHEY_SIMPLEX,.8,(220,220,220),2)
        write_image(self.root/'reference.png',self.base);data,_=create(self.root/'reference.png',self.root)
        doc=Document(data);doc.add('LED49',None,490,350);self.cal=doc.data

    def build(self,images,**kwargs):
        ArrayReader.images=images
        with patch('software.vision.off_background.SequentialVideoReader',ArrayReader):
            return build_off('ARRAY_ONLY',self.cal,kwargs.pop('cancel',threading.Event()),duration_s=1,**kwargs)

    def test_stable_moving_exposure_and_neutral_silk_residual_off(self):
        for variant in ('stable','movement','exposure','silk'):
            images=[]
            for i in range(30):
                image=self.base.copy()
                if variant=='movement':image=cv2.warpPerspective(image,np.array([[1,0,(i%4)*.3],[0,1,(i%3)*.2],[0,0,1.]]),(1200,700),borderValue=(70,70,70))
                if variant=='exposure':image=np.clip(image.astype(float)*(1+i*.002)+i*.05,0,255).astype(np.uint8)
                if variant=='silk':
                    image[200:480,240:720]=cv2.warpAffine(image[200:480,240:720],np.array([[1,0,.4*(i%3)],[0,1,.2]],np.float32),(480,280),borderValue=(70,70,70))
                images.append(image)
            with self.subTest(variant=variant):
                model=self.build(images);self.assertGreaterEqual(model.metadata['retained_frames'],3)
                self.assertGreaterEqual(model.metadata['coverage']['known_leds']['LED49'],.9)
                self.assertLessEqual(model.metadata['retained_frames'],5)

    def test_late_good_candidates_after_marker_loss(self):
        bad=np.full_like(self.base,70);images=[bad]*6+[self.base]*24
        model=self.build(images)
        self.assertTrue(model.metadata['rejected']);self.assertTrue(all(a['frame_index']>=6 for a in model.metadata['accepted']))

    def test_partial_marker_loss_still_requires_three_spatial_anchors(self):
        image=self.base.copy();image[510:690,980:1190]=70
        model=self.build([image]*30);self.assertGreaterEqual(model.metadata['retained_frames'],3)
        image[40:220,980:1190]=70
        with self.assertRaises(OffBuildError):self.build([image]*30)

    def test_contamination_even_after_enough_good_frames_refuses_interval(self):
        red=illuminate(self.base,[(490,350,(0,0,255))])
        reflection=self.base.copy();cv2.rectangle(reflection,(400,300),(600,410),(0,255,0),-1)
        occlusion=self.base.copy();cv2.rectangle(occlusion,(350,240),(750,460),(0,0,0),-1)
        bright=np.clip(self.base.astype(float)*1.8+20,0,255).astype(np.uint8)
        for name,images in [('persistent_led',[red]*30),('on_midway',[self.base]*15+[red]*15),
                            ('reflection',[reflection]*30),('object',[self.base]*15+[occlusion]*15),
                            ('exposure_jump',[self.base]*15+[bright]*15),
                            ('blur',[cv2.GaussianBlur(self.base,(31,31),6)]*30)]:
            with self.subTest(name=name),self.assertRaises(OffBuildError):self.build(images)

    def test_failed_diagnostics_and_cancellation_are_saved_without_ready_progress(self):
        notifications=[];path=self.root/'failed'
        with self.assertRaises(OffBuildError):self.build([np.full_like(self.base,70)]*30,diagnostics_dir=path,notify=lambda *a:notifications.append(a))
        data=json.loads((path/'off_diagnostics.json').read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'FAILED');self.assertTrue((path/'off_candidates.csv').exists())
        self.assertFalse(any(n[2].get('state')=='READY' for n in notifications))
        cancel=threading.Event();cancel.set();path=self.root/'cancelled'
        with self.assertRaises(Cancelled):self.build([self.base]*30,diagnostics_dir=path,cancel=cancel)
        self.assertEqual(json.loads((path/'off_diagnostics.json').read_text(encoding='utf-8'))['status'],'CANCELLED')

    def test_rotation_metadata_and_pts_preserved(self):
        path=self.root/'rotated.mp4';image=np.zeros((80,140,3),np.uint8);image[:30,:40]=(0,0,255)
        with av.open(str(path),'w') as container:
            stream=container.add_stream('mpeg4',rate=30);stream.width=140;stream.height=80;stream.pix_fmt='yuv420p'
            stream.set_display_rotation(-90)
            for pts in (0,1,3):
                frame=av.VideoFrame.from_ndarray(image,format='bgr24');frame.pts=pts;frame.time_base=Fraction(1,30)
                for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        reader=SequentialVideoReader();meta=reader.open(path)
        try:
            output,a=reader.frame(0);_,b=reader.frame(1);_,c=reader.frame(2)
            self.assertEqual(output.shape[:2],(140,80));self.assertEqual(meta['rotation_degrees'],-90)
            self.assertEqual((meta['coded_width'],meta['coded_height']),(140,80))
            self.assertGreater(output[:40,-30:,2].mean(),200)
            self.assertAlmostEqual(c['timestamp_ms']-a['timestamp_ms'],100,delta=2)
            self.assertGreater(c['timestamp_ms']-b['timestamp_ms'],b['timestamp_ms']-a['timestamp_ms'])
        finally:reader.close()

    def test_degraded_geometry_cannot_confirm_event(self):
        aggregator=EventAggregator()
        result=dict(registration_status='DEGRADED',analysis_status='ANALYZED',records=[dict(led_id='LED49',status='ON',color='RED')])
        aggregator.feed(result,0,0);aggregator.feed(result,33,1)
        self.assertEqual(aggregator.events(),[])

    def test_rank_median_is_exact_for_missing_even_and_odd_observations(self):
        import warnings
        rng=np.random.default_rng(73)
        for count in (3,4,5,9):
            observed=rng.integers(0,256,(count,11,13,3),dtype=np.uint8)
            masks=rng.random((count,11,13))>.4;masks[:,0,0]=False
            floating=observed.astype(float)
            floating[~masks]=np.nan
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning)
                expected=np.nan_to_num(np.nanmedian(floating,axis=0)).astype(np.uint8)
            np.testing.assert_array_equal(masked_median_tile(observed,masks),expected)
