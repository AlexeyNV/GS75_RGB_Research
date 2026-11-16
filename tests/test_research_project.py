from pathlib import Path
import json
import shutil
import tempfile
import threading
import unittest
import numpy as np
from software.vision.calibration import create,Document
from software.vision.project_storage import write_image,image_hash
from software.vision.research_project import ResearchProject,batch,Cancelled
from software.vision.optical_signal import measure
from software.vision.led_detection import analyze
from vision_fixtures import board,illuminate


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        write_image(self.root/'reference.png',board());data,_=create(self.root/'reference.png',self.root)
        doc=Document(data);doc.add('LED49',None,490,350);doc.save(self.root/'map.json')
        self.project=ResearchProject.create(self.root/'session.vision-project.json')
        self.project.bind_calibration(self.root/'map.json',self.root)
        write_image(self.root/'off.png',board())
        self.off=self.project.add_media(self.root/'off.png','OFF')
        self.ons=[]
        for name,color in [('red',(0,0,255)),('green',(0,255,0)),('blue',(255,0,0))]:
            path=self.root/(name+'.png');write_image(path,illuminate(board(),[(490,350,color)]))
            self.ons.append(self.project.add_media(path,'ON'))

    def test_portable_roundtrip_roles_and_calibration_integrity(self):
        p=self.project;p.save();restored=ResearchProject.load(p.path)
        self.assertEqual(restored.checked_calibration()['leds'][0]['led_id'],'LED49')
        self.assertFalse(restored.missing_files());self.assertEqual(restored.data['media'],p.data['media'])
        self.assertFalse(Path(restored.data['reference']).is_absolute())
        restored.assign(self.ons[0]['id'],'OFF')
        self.assertEqual(sum(m['role']=='OFF' for m in restored.data['media']),1)
        self.assertEqual(len(restored.data['media']),4)
        restored.add_media(self.root/'red.png');self.assertEqual(len(restored.data['media']),4)
        data=json.loads((self.root/'map.json').read_text());data['metadata']['comment']='changed'
        (self.root/'map.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'изменена'):restored.checked_calibration()

    def test_batch_rgb_repeat_and_no_input_mutation(self):
        p=self.project;paths=[self.root/'map.json',self.root/'reference.png',self.root/'off.png']+[self.root/(c+'.png') for c in ('red','green','blue')]
        hashes=[image_hash(x) for x in paths]
        first=batch(p,self.off['id'],[m['id'] for m in self.ons]);self.assertEqual(first['state'],'COMPLETED')
        self.assertEqual([i['records'][0]['color'] for i in first['items']],['RED','GREEN','BLUE'])
        second=batch(p,self.off['id'],[self.ons[0]['id']]);self.assertNotEqual(first['id'],second['id'])
        self.assertTrue((p.resolve(first['report'])/'batch.csv').exists())
        self.assertTrue((p.resolve(first['items'][0]['report'])/'calibration_snapshot.json').exists())
        self.assertEqual(hashes,[image_hash(x) for x in paths])

    def test_cancel_preserves_completed_results_and_partial_history(self):
        event=threading.Event()
        def notify(*args):event.set()
        e=batch(self.project,self.off['id'],[m['id'] for m in self.ons],event,notify)
        self.assertEqual(e['state'],'CANCELLED');self.assertEqual(len(e['items']),1)
        self.assertTrue((self.project.resolve(e['items'][0]['report'])/'results.json').is_file())
        with self.assertRaises(Cancelled):batch(self.project,self.off['id'],[self.ons[0]['id']],event)

    def test_missing_files_relink_and_invalid_project(self):
        old=self.project.media(self.ons[0]['id'])['path'];new=self.root/'renamed.png'
        (self.root/'red.png').rename(new)
        self.assertIn(old,self.project.missing_files());self.project.relocate(old,new)
        self.assertFalse(self.project.missing_files())
        (self.root/'bad.json').write_text('{"schema_version": 99}')
        with self.assertRaises(ValueError):ResearchProject.load(self.root/'bad.json')

    def test_project_can_move_with_data_tree(self):
        self.project.save();target=self.root/'relocated'
        target.mkdir()
        for p in list(self.root.iterdir()):
            if p.is_file():shutil.copy2(p,target/p.name)
        moved=ResearchProject.load(target/self.project.path.name)
        self.assertEqual(moved.root,target);self.assertFalse(moved.missing_files())
        moved.checked_calibration()

    def test_color_confidence_single_mixed_ambiguous_and_clipped(self):
        for bgr,expected in [([134,37,6],'BLUE'),([0,255,255],'MIXED'),([255,255,0],'MIXED'),([255,0,255],'MIXED'),([200,115,0],'UNDEFINED')]:
            delta=np.array([[bgr,bgr]],dtype=np.uint8)
            r=measure(delta,delta,np.full((1,2),80),np.ones((1,2),bool))
            self.assertEqual(r['color'],expected);self.assertIn('color_reason',r)
            self.assertTrue(0<=r['color_confidence']<=1)
        # A clipped neutral core contributes no spectral vote.
        delta=np.array([[[255,255,255],[250,40,5]]],dtype=np.uint8)
        r=measure(delta,delta,np.full((1,2),80),np.ones((1,2),bool))
        self.assertEqual(r['color'],'BLUE')

    def test_ambiguous_color_remains_uncertain_in_pipeline(self):
        data=self.project.checked_calibration()
        # Background is 70: compensated B/G increments 130/75 are ambiguous.
        a=analyze(data,board(),illuminate(board(),[(490,350,(200,145,0))]))
        self.assertEqual(a.result['known_leds'][0]['status'],'UNCERTAIN')
        self.assertEqual(a.result['known_leds'][0]['color'],'UNDEFINED')
