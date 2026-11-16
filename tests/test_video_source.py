from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import cv2
from software.vision.video_source import VideoReader
from software.vision.research_project import ResearchProject,batch
from software.vision.calibration import create,Document
from software.vision.project_storage import write_image
from vision_fixtures import board,illuminate


def make_video(path):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),10,(1200,700))
    if not writer.isOpened():raise RuntimeError('MP4 writer unavailable')
    try:
        for index in range(8):
            writer.write(board() if index<4 else illuminate(board(),[(490,350,(255,0,0))]))
    finally:writer.release()


class VideoTests(unittest.TestCase):
    def test_mp4_seek_step_frame_analysis_and_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'test.mp4';make_video(path)
            reader=VideoReader();self.addCleanup(reader.close)
            meta=reader.open(path);self.assertEqual(meta['frame_count'],8)
            off,info0=reader.frame(0);on,info6=reader.frame(6)
            self.assertEqual(info6['frame_index'],6)
            _,back=reader.frame(5);self.assertEqual(back['frame_index'],5)
            _,forward=reader.frame(6);self.assertEqual(forward['frame_index'],6)
            self.assertIn(info6['timestamp_source'],('decoder_reported','unknown'))
            write_image(root/'ref.png',board());data,_=create(root/'ref.png',root)
            doc=Document(data);doc.add('LED49',None,490,350);doc.save(root/'map.json')
            p=ResearchProject.create(root/'session.vision-project.json');p.bind_calibration(root/'map.json',root)
            a=p.capture_frame(off,path,info0,'OFF');b=p.capture_frame(on,path,info6,'ON')
            e=batch(p,a['id'],[b['id']]);self.assertEqual(e['items'][0]['records'][0]['color'],'BLUE')
            self.assertEqual(p.media(b['id'])['metadata']['frame_index'],6)
            capture=reader.capture;reader.close();self.assertFalse(capture.isOpened());self.assertIsNone(reader.capture)
            with self.assertRaises(ValueError):reader.frame(0)

    def test_missing_video_and_bad_index(self):
        reader=VideoReader()
        with self.assertRaises(ValueError):reader.open('missing_video.mp4')
        self.assertIsNone(reader.capture)

    def test_unknown_decoder_timestamp_is_not_claimed_exact(self):
        reader=VideoReader();reader.capture=Mock();reader.count=20;reader.fps=30
        reader.capture.get.side_effect=lambda key:6 if key==cv2.CAP_PROP_POS_FRAMES else 0
        reader.capture.read.return_value=(True,board())
        _,info=reader.frame(5)
        self.assertIsNone(info['timestamp_ms']);self.assertEqual(info['timestamp_source'],'unknown')
        self.assertIsNotNone(info['estimated_ms']);reader.close()
