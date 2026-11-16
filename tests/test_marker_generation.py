import hashlib
import json
import re
from pathlib import Path
import tempfile
import unittest
from software.vision.aruco_markers import generate, detect, marker_image


class MarkerTests(unittest.TestCase):
    def test_all_ids(self):
        for i in range(50):
            self.assertEqual(list(detect(marker_image(i))), [str(i)])

    def test_page_and_repeatability(self):
        with tempfile.TemporaryDirectory() as temporary:
            for size,count in [(10,10),(12,8),(15,12)]:
                a,b = Path(temporary)/f'a{size}',Path(temporary)/f'b{size}'
                manifest = generate(a,range(count),size)
                generate(b,range(count),size)
                for item in manifest['markers']:
                    x,y,w,h=item['page_box_mm']
                    self.assertLessEqual(x+w,210); self.assertLessEqual(y+h,297)
                    self.assertEqual(item['code_mm']+2*item['quiet_zone_mm'],size)
                for name in ['aruco_A4.pdf','aruco_A4.svg','markers_manifest.json']:
                    self.assertEqual(hashlib.sha256((a/name).read_bytes()).digest(),hashlib.sha256((b/name).read_bytes()).digest())
                self.assertIn('width="210mm" height="297mm"',(a/'aruco_A4.svg').read_text())
                bounds=re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]',(a/'aruco_A4.pdf').read_bytes())
                self.assertIsNotNone(bounds)
                self.assertAlmostEqual(float(bounds[1])*25.4/72,210,places=3)
                self.assertAlmostEqual(float(bounds[2])*25.4/72,297,places=3)
                with self.assertRaises(FileExistsError): generate(a)

    def test_invalid_ids(self):
        for ids in [[0]*10,range(7),range(13),range(45,55)]:
            with self.assertRaises(ValueError): generate('unused',ids)
