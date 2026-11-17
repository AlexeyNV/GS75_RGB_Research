"""Qt offscreen: analyze from Video, review, seek, diagnostics, history and cancel."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
from PySide6.QtWidgets import QApplication,QInputDialog,QFileDialog
from software.gui.vision_window import VisionWindow
from software.vision.perf_fixture import generate_sequence
from software.vision.project_storage import image_hash

APP=QApplication.instance() or QApplication([])


def wait_all(window,timeout=60):
    end=time.monotonic()+timeout;stable=0
    while time.monotonic()<end:
        APP.processEvents();time.sleep(.005)
        controls=window.video_events
        busy=window.active_job is not None or window.pool.activeThreadCount()>0 or any(w.loading or w.pending is not None for w in controls.windows if not w.closed)
        stable=0 if busy else stable+1
        if stable>=5:return
    raise AssertionError('Video GUI timed out')


class VideoEventGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.video,cls.cal,_=generate_sequence(cls.root/'dataset',(960,540))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.window=VisionWindow(remember=False);self.errors=[];self.window.error=self.errors.append;self.window.show()
        self.project=self.root/(uuid.uuid4().hex+'.vision-project.json');self.window.new_project(self.project)
        self.window.load_calibration(self.root/'dataset/calibration.json',self.root/'dataset');wait_all(self.window)
        self.window.open_video(self.video);wait_all(self.window);self.controls=self.window.video_events

    def tearDown(self):
        if self.window.active_job:self.window.cancel_job()
        wait_all(self.window)
        for window in self.controls.windows:window.close()
        if self.window.calibrator.document:self.window.calibrator.document.mark_saved()
        self.window.close();self.window.deleteLater();APP.processEvents()

    def test_video_analysis_timeline_seek_layers_history_and_reuse(self):
        self.controls.run.click();wait_all(self.window)
        result=self.controls.windows[-1]
        self.assertEqual(result.report['status'],'COMPLETED');self.assertEqual(result.event_table.rowCount(),3)
        self.assertEqual(result.report['processed_frames'],120)
        result.select_event(0);wait_all(self.window)
        self.assertEqual(result.current_index,result.shown_events[0]['start_frame'])
        result.layers.setCurrentText('ROI');wait_all(self.window)
        self.assertLessEqual(result.viewer.sceneRect().width(),201)
        result.layers.setCurrentText('Coverage');wait_all(self.window)
        self.assertEqual(result.viewer.sceneRect().width(),1200)
        result.timeline.seek.emit(result.shown_events[1]['start_pts']);wait_all(self.window)
        self.assertEqual(result.current_index,result.shown_events[1]['start_frame'])
        result.close();self.assertFalse(result.decoder.capture)
        self.controls.settings=type(self.controls.settings)(min_on_s=.12)
        with patch('software.vision.video_analysis.VideoEngine',side_effect=AssertionError('Cache must skip OpenCV')):
            self.controls.run.click();wait_all(self.window)
        cached=self.controls.windows[-1]
        self.assertFalse(cached.report['opencv_rerun']);self.assertEqual(cached.event_table.rowCount(),3)
        cached.close();self.window.save_project();self.window.open_project(self.project);wait_all(self.window)
        self.assertEqual(self.controls.history.count(),2)
        self.controls.history.setCurrentIndex(0);self.controls.open_history();wait_all(self.window)
        self.assertEqual(self.controls.windows[-1].event_table.rowCount(),3)
        self.assertEqual(self.errors,[])

    def test_blind_tracks_manual_review_export_and_raw_immutability(self):
        self.controls.mode.setCurrentText('DISCOVER');self.controls.run.click();wait_all(self.window)
        result=self.controls.windows[-1]
        self.assertTrue(result.tracks);self.assertTrue(all(t['led_id'] is None for t in result.tracks))
        result.select_track(0);wait_all(self.window)
        original=image_hash(result.path/'events.json');count=len(self.window.calibrator.document.data['leds'])
        with patch.object(QInputDialog,'getText',return_value=('Checked optically',True)):result.review('ACCEPTED')
        with patch.object(QInputDialog,'getText',return_value=('LED888',True)):result.identify()
        self.assertEqual(image_hash(result.path/'events.json'),original)
        self.assertEqual(len(self.window.calibrator.document.data['leds']),count)
        self.assertEqual(result.track_table.item(0,4).text(),'LED888')
        self.window.calibrator.autonumber.setChecked(True)
        with patch('software.gui.board_calibrator.LEDDialog') as dialog:
            dialog.return_value.exec.return_value=False;result.add_to_map()
            self.assertEqual(dialog.call_args.args[2],'')
        folder=self.root/('export_'+uuid.uuid4().hex);folder.mkdir()
        with patch.object(QFileDialog,'getExistingDirectory',return_value=str(folder)):result.export();wait_all(self.window)
        self.assertTrue(list(folder.glob('*/manual_decisions.jsonl')))
        self.assertEqual(self.errors,[])

    def test_cancel_and_failure_never_show_success_progress(self):
        self.controls.run.click()
        end=time.monotonic()+30
        while time.monotonic()<end:
            APP.processEvents();time.sleep(.003)
            if 'Кадр ' in self.controls.status.text():break
        self.window.cancel_job();wait_all(self.window)
        result=self.controls.windows[-1]
        self.assertEqual(result.report['status'],'CANCELLED')
        self.assertLess(result.report['processed_frames'],120);self.assertEqual(self.window.progress.value(),0)
        result.close()
        with patch('software.vision.video_analysis.build_off',side_effect=ValueError('No OFF')),self.assertLogs(level='ERROR'):
            self.controls.run.click();wait_all(self.window)
        self.assertEqual(self.controls.windows[-1].report['status'],'FAILED')
        self.assertEqual(self.window.progress.value(),0)
