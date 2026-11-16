from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from software.vision import calibration as c
from software.vision.project_storage import write_image,atomic_json
from vision_fixtures import board


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.image=self.root/'reference.png'; write_image(self.image,board())
        data,_=c.create(self.image,self.root); self.document=c.Document(data)

    def test_edit_history_and_roundtrip(self):
        d=self.document; d.add('LED49',None,490.123456789,350.987654321)
        d.add('LED50','Enter',570,350); d.edit('LED49',key_name='Enter',led_id='LED149')
        self.assertEqual(len(d.data['leds']),2)
        with self.assertRaises(ValueError): d.edit('LED50',led_id='LED149')
        self.assertEqual(d.data['leds'][1]['led_id'],'LED50')
        d.delete('LED50'); d.undo(); self.assertEqual(len(d.data['leds']),2)
        d.redo(); self.assertEqual(len(d.data['leds']),1)
        path=self.root/'map.json'; d.save(path); self.assertFalse(d.dirty)
        self.assertEqual(c.load(path,self.root),d.data)
        self.assertEqual(c.load(path,self.root)['leds'][0]['x_ref_px'],490.123456789)
        d.undo(); self.assertTrue(d.dirty); d.redo(); self.assertFalse(d.dirty)

    def test_many_leds_and_validation(self):
        d=self.document
        for i in range(1,201): d.add(f'LED{i}','Space',200+i,300+i/10)
        path=self.root/'many.json'; d.save(path); self.assertEqual(len(c.load(path,self.root)['leds']),200)
        for change in [dict(x_ref_px=float('nan')),dict(y_ref_px=-1),dict(led_id='LED0')]:
            with self.assertRaises(ValueError): d.edit('LED1',**change)
        modified=deepcopy(d.data); modified['schema_version']=99
        with self.assertRaises(ValueError): c.validate(modified)
        modified=deepcopy(d.data); modified['reference']['path']='../outside.jpg'
        with self.assertRaises(ValueError): c.validate(modified)

    def test_checksum_and_external_photo(self):
        path=self.root/'map.json'; self.document.save(path)
        with self.image.open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'): c.load(path,self.root)
        other=self.root/'project'; other.mkdir()
        data,_=c.create(self.image,other)
        self.assertTrue(data['reference']['path'].startswith('data/reference/'))
        self.assertFalse(Path(data['reference']['path']).is_absolute())

    def test_bad_markers_and_duplicate_json(self):
        data=deepcopy(self.document.data); data['markers']['0']=[[1,1]]*4
        with self.assertRaises(ValueError): c.validate(data)
        path=self.root/'duplicate.json'; path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError,'Duplicate'): c.load(path,self.root)

    def test_exif_orientation_and_camera_validation(self):
        from PIL import Image
        path=self.root/'oriented.jpg'; image=Image.new('RGB',(100,60)); exif=image.getexif(); exif[274]=6
        image.save(path,exif=exif)
        data,_=c.create(path,self.root)
        self.assertEqual([data['reference']['width'],data['reference']['height']],[60,100])
        self.assertEqual(data['reference']['source_exif_orientation'],6)
        data['camera_model']=dict(matrix=[[300,0,30],[0,300,50],[0,0,1]],distortion=[0,0,0,0,0],image_size=[60,100])
        c.validate(data)
        data['camera_model']['matrix'][0][0]=-1
        with self.assertRaises(ValueError): c.validate(data)
