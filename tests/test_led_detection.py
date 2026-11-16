from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from software.vision.calibration import create,Document
from software.vision.project_storage import write_image
from software.vision.led_detection import analyze,export
from vision_fixtures import board,illuminate


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.off=board(); write_image(self.root/'ref.png',self.off)
        data,_=create(self.root/'ref.png',self.root); doc=Document(data)
        doc.add('LED49',None,490,350); doc.add('LED50','Space',570,350); self.data=doc.data

    def test_colors_and_multiple_leds(self):
        for bgr,color in [((0,0,255),'RED'),((0,255,0),'GREEN'),((255,0,0),'BLUE'),((0,255,255),'MIXED')]:
            result=analyze(self.data,self.off,illuminate(self.off,[(490,350,bgr)]))
            self.assertEqual(result.result['registration_status'],'REGISTERED')
            records=result.result['detections']; self.assertEqual(len(records),1)
            self.assertEqual(records[0]['led_id'],'LED49'); self.assertIsNone(records[0]['key_name'])
            self.assertEqual(records[0]['color'],color)
        result=analyze(self.data,self.off,illuminate(self.off,[(490,350,(0,0,255)),(570,350,(255,0,0))]))
        self.assertEqual({r['led_id'] for r in result.result['detections']},{'LED49','LED50'})

    def test_different_viewpoints_and_illumination(self):
        matrix=cv2.getPerspectiveTransform(np.float32([[0,0],[1199,0],[1199,699],[0,699]]),np.float32([[120,60],[1400,160],[1300,860],[70,740]]))
        off=cv2.warpPerspective(self.off,np.array([[1.,0,100],[0,1,100],[0,0,1]]),(1600,1000))
        lit=illuminate(self.off,[(490,350,(0,0,255))]); lit=np.clip(lit.astype(float)*1.05+8,0,255).astype(np.uint8)
        on=cv2.warpPerspective(lit,matrix,(1600,1000))
        result=analyze(self.data,off,on)
        self.assertNotEqual(result.result['registration_status'],'FAILED',result.result)
        record=next(r for r in result.result['detections'] if r['led_id']=='LED49')
        error=np.hypot(record['x_ref_px']-490,record['y_ref_px']-350)
        print(f'LED49 localization error={error:.4f} reference px')
        self.assertLess(error,2); self.assertEqual(record['color'],'RED')

    def test_no_light_saturation_unknown_and_sticker_reflection(self):
        self.assertEqual(analyze(self.data,self.off,self.off).result['detections'],[])
        changed=np.clip(self.off.astype(float)*1.05+8,0,255).astype(np.uint8)
        self.assertEqual(analyze(self.data,self.off,changed).result['detections'],[])
        white=analyze(self.data,self.off,illuminate(self.off,[(490,350,(255,255,255))]))
        self.assertEqual(white.result['detections'][0]['color'],'UNDEFINED')
        self.assertIn('SATURATED_WHITE',white.result['detections'][0]['ambiguity_flags'])
        unknown=analyze(self.data,self.off,illuminate(self.off,[(700,350,(0,255,0))]))
        self.assertIsNone(unknown.result['detections'][0]['led_id'])
        reflection=self.off.copy(); cv2.circle(reflection,(92,88),5,(255,255,255),-1)
        self.assertEqual(analyze(self.data,self.off,reflection).result['detections'],[])

    def test_failed_geometry_exports_no_invented_id(self):
        bad=np.full_like(self.off,70)
        result=analyze(self.data,self.off,bad)
        self.assertEqual(result.result['registration_status'],'FAILED'); self.assertEqual(result.result['detections'],[])
        output=self.root/'results'; export(result,output)
        self.assertTrue((output/'on_markers.png').exists())
        self.assertEqual(len((output/'results.csv').read_text().splitlines()),1)
        with self.assertRaises(FileExistsError): export(result,output)

    def test_overwrite_cannot_leave_previous_success_overlay(self):
        output=self.root/'results'; export(analyze(self.data,self.off,illuminate(self.off,[(490,350,(0,0,255))])),output)
        self.assertTrue((output/'annotated.png').exists())
        export(analyze(self.data,self.off,np.full_like(self.off,80)),output,True)
        self.assertFalse((output/'annotated.png').exists())

    def test_extreme_lighting_is_not_a_false_led(self):
        image=np.clip(self.off.astype(float)+70,0,255).astype(np.uint8)
        result=analyze(self.data,self.off,image)
        self.assertEqual(result.result['analysis_status'],'FAILED')
        self.assertEqual(result.result['detections'],[])
