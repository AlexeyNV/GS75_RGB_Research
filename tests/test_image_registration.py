from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from software.vision.calibration import create
from software.vision.project_storage import write_image
from software.vision.image_registration import register,transform_points
from vision_fixtures import board


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.reference=board(); write_image(self.root/'ref.png',self.reference)
        self.data,_=create(self.root/'ref.png',self.root)

    def test_translation_rotation_scale_perspective(self):
        rotation=np.vstack([cv2.getRotationMatrix2D((600,350),8,.88),[0,0,1]])
        rotation[:2,2]+=[180,130]
        perspective=cv2.getPerspectiveTransform(np.float32([[0,0],[1199,0],[1199,699],[0,699]]),np.float32([[120,60],[1400,160],[1300,860],[70,740]]))
        matrices=[np.array([[1.,0,150],[0,1,100],[0,0,1]]),rotation,perspective]
        for matrix in matrices:
            image=cv2.warpPerspective(self.reference,matrix,(1600,1000),borderValue=(30,30,30))
            registration=register(image,self.data)
            self.assertEqual(registration.status,'REGISTERED',registration.summary())
            points=np.array([[490.,350],[570,350],[600,500]])
            restored=transform_points(transform_points(points,matrix),registration.matrix)
            error=float(np.linalg.norm(restored-points,axis=1).max())
            print(f'Registration localization max={error:.4f} px, reprojection RMSE={registration.error_px:.4f} px')
            self.assertLess(error,1.5)

    def test_hidden_markers_and_failure(self):
        partial=self.reference.copy(); partial[50:210,1000:1160]=70
        self.assertEqual(register(partial,self.data).status,'REGISTERED')
        partial[520:680,60:220]=70
        self.assertEqual(register(partial,self.data).status,'DEGRADED')
        partial[520:680,1000:1160]=70
        self.assertEqual(register(partial,self.data).status,'FAILED')
        self.assertEqual(register(np.full_like(partial,90),self.data).status,'FAILED')

    def test_bad_correspondence_mirror_and_cluster(self):
        mirrored=deepcopy(self.data['markers'])
        for corners in mirrored.values():
            for point in corners: point[0]=1199-point[0]
        self.assertEqual(register(self.reference,self.data,mirrored).status,'FAILED')
        clustered=deepcopy(self.data)
        for corners in clustered['markers'].values():
            for point in corners: point[0]=100+point[0]*.01; point[1]=100+point[1]*.01
        self.assertEqual(register(self.reference,clustered,self.data['markers']).status,'FAILED')
        bad=deepcopy(self.data['markers']); bad['1']=bad['0']
        registration=register(self.reference,self.data,bad)
        self.assertTrue(registration.status=='FAILED' or '1' not in registration.inlier_ids)
