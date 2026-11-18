"""Actual Qt + injected CDC + encoded synthetic short-pulse MP4 end to end."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import csv
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import cv2
from PySide6.QtWidgets import QMessageBox,QFileDialog,QInputDialog
from software.gui.vision_window import VisionWindow
from software.hardware.scenario import CONDITIONS,SHORT_NAME
from software.hardware.simulator import SimulatedCDC
from software.hardware.electrical_operations import load_operations
from software.vision.perf_fixture import generate_sequence
from software.vision.project_storage import read_image,image_hash
from test_video_event_gui import APP,wait_all
from test_experiment_gui import until


def render_short_video(directory,session_path,calibration_path):
    """Synthetic LED emission from actual simulator TX; never real phone footage."""
    session,ops=load_operations(session_path)
    board=read_image(Path(calibration_path).parent/'reference.png')
    end=session['finished_ns']/1e9+2.3;fps=30.;path=directory/'synthetic_short.mp4'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),fps,(960,560))
    if not writer.isOpened():raise AssertionError('Synthetic MP4 encoder unavailable')
    try:
        for frame in range(int(end*fps)):
            t=frame/fps;image=board.copy()
            active=next((o for o in ops if o['host_tx_s']+2<=t<o['host_tx_s']+2+o['requested_duration_ms']/1000),None)
            if active:cv2.circle(image,(490,350),12,dict(RED=(0,0,255),GREEN=(0,255,0),BLUE=(255,0,0))[active['color']],-1,cv2.LINE_AA)
            writer.write(cv2.resize(image,(960,560)))
    finally:writer.release()
    return path


class ShortWorkflowGUI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        _,self.cal,_=generate_sequence(self.root/'dataset',(960,560),frames=1)
        self.window=VisionWindow(remember=False);self.window.show();self.errors=[];self.window.error=self.errors.append
        self.window.new_project(self.root/'research.vision-project.json')
        self.window.load_calibration(self.root/'dataset/calibration.json',self.root/'dataset');wait_all(self.window)
        self.pane=self.window.experiment;self.fake=SimulatedCDC();worker=self.pane.worker
        worker.root=self.root/'sessions';worker.factory=lambda port:self.fake;worker.clock_ns=self.fake.clock.now_ns

    def tearDown(self):
        self.pane.worker.shutdown();until(lambda:not self.pane.worker.isRunning())
        if self.window.active_job:self.window.cancel_job()
        wait_all(self.window)
        self.window.calibrator.document.mark_saved() if self.window.calibrator.document else None
        self.window.close();self.window.deleteLater();APP.processEvents()

    def run_series(self):
        self.pane.scenario_choice.setCurrentIndex(1)
        self.assertEqual(self.pane.scenario_choice.currentData(),SHORT_NAME)
        self.assertEqual(self.pane.repeats.value(),10);self.assertEqual(self.pane.controls['pause_ms'].value(),700)
        self.assertEqual(len([s for s in self.pane.stages if s.role=='SHORT_PULSE']),30)
        self.assertEqual(self.fake.commands,[])
        self.pane.repeats.setValue(1);self.pane.marker.setChecked(True)
        for key,value in [('initial_ms',2500),('pause_ms',150),('final_ms',100)]:self.pane.controls[key].setValue(value)
        self.pane.ports.setEditText('SIMULATED');self.pane.connect_button.click();until(lambda:self.pane.ready and not self.pane.busy)
        with patch.object(self.pane,'confirm_conditions',return_value=dict.fromkeys(CONDITIONS,True)),patch.object(QMessageBox,'question',return_value=QMessageBox.No):
            self.pane.start.click();until(lambda:self.pane.session_path is not None)
        self.assertIn('SIMULATION',self.pane.outcome.text())
        self.assertEqual(len([c for c in self.fake.commands if c.startswith('PHOTO ')]),4)
        return self.pane.session_path/'session.json'

    def test_experiment_video_analysis_timeline_tables_current_review_export_and_reopen_binding(self):
        session=self.run_series();video=render_short_video(self.root,session,self.root/'dataset/calibration.json')
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(video),'')):self.pane.attach.click()
        wait_all(self.window);self.assertTrue(self.pane.analyze.isEnabled())
        commands=list(self.fake.commands)
        self.pane.analyze.click();wait_all(self.window)
        self.assertEqual(self.window.video_events.profile.currentIndex(),1)
        self.assertIs(self.window.tabs.currentWidget(),self.window.video_page)
        result=self.window.video_events.windows[-1]
        self.assertEqual(result.report['status'],'COMPLETED',result.report.get('error'))
        self.assertEqual(len([e for e in result.events if e['status']=='CONFIRMED']),4)
        self.assertEqual(result.correspondence['alignment']['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
        self.assertEqual(sum(r['requested'] for r in result.correspondence['short_pulse_summary']),3)
        self.assertEqual(self.fake.commands,commands)  # analysis/export cannot touch transport
        result.select_event(1);result.layers.setCurrentText('ROI');wait_all(self.window)
        self.assertEqual(result.current_index,result.shown_events[1]['start_frame'])
        self.assertLessEqual(result.viewer.sceneRect().width(),201)
        self.assertIn('KP14→KP32',result.details.toPlainText());self.assertIn('1035',result.details.toPlainText())
        result.show_tables();tables=result.table_windows[-1]
        self.assertEqual(tables.tabs.count(),4);self.assertEqual(tables.tables[0].rowCount(),4)
        original=image_hash(result.path/'events.json');first=result.correspondence_path
        with patch.object(QInputDialog,'getText',return_value=('Synthetic operator test only',True)):result.review('ACCEPTED')
        wait_all(self.window)
        self.assertNotEqual(first,result.correspondence_path);self.assertTrue(first.is_dir())
        self.assertEqual(image_hash(result.path/'events.json'),original)
        self.assertTrue(any(r['mapping_status']=='VERIFIED' for r in result.correspondence['mapping']))
        destination=self.root/'export';destination.mkdir()
        with patch.object(QFileDialog,'getExistingDirectory',return_value=str(destination)):result.export()
        wait_all(self.window)
        self.assertTrue(list(destination.glob('*/correspondence_*/electrical_optical_mapping.csv')))
        tables.close();result.close()
        # Ordinary operation restores the bound project asynchronously; no JSON picker.
        bound=self.window.project.path;self.window.new_project(self.root/'other.vision-project.json')
        with patch.object(QFileDialog,'getOpenFileName',side_effect=AssertionError('Bound workflow must not request JSON')):
            self.pane.analyze.click();until(lambda:bool(self.window.video_events.windows) and self.window.video_events.windows[-1] is not result,timeout=40);wait_all(self.window)
        self.assertEqual(self.window.project.path,bound)
        self.assertFalse(self.window.video_events.windows[-1].report['opencv_rerun'])
        self.assertEqual(self.fake.commands,commands);self.assertEqual(self.errors,[])

    def test_missing_project_calibration_uses_gui_selection(self):
        session=self.run_series();video=render_short_video(self.root,session,self.root/'dataset/calibration.json')
        self.pane.import_video(video);wait_all(self.window)
        data=json.loads(session.read_text(encoding='utf-8'));data['project_binding']=None
        session.write_text(json.dumps(data),encoding='utf-8')
        self.window.new_project(self.root/'without_map.vision-project.json')
        choices=[(str(self.window.project.path),''),(str(self.root/'dataset/calibration.json'),'')]
        with patch.object(QFileDialog,'getOpenFileName',side_effect=choices) as choose:
            self.pane.analyze.click();until(lambda:bool(self.window.video_events.windows),timeout=50);wait_all(self.window)
        self.assertEqual(choose.call_count,2)
        self.assertTrue(self.window.video_events.windows[-1].correspondence)
        self.assertEqual(self.errors,[])

    def test_failed_calibration_load_stops_continuation_without_dialog_loop(self):
        session=self.run_series();video=render_short_video(self.root,session,self.root/'dataset/calibration.json')
        self.pane.import_video(video);wait_all(self.window)
        invalid=dict(self.cal,reference=dict(self.cal['reference'],sha256='0'*64))
        path=self.root/'invalid_map.json';path.write_text(json.dumps(invalid),encoding='utf-8')
        self.window.project.data['calibration']=None
        commands=list(self.fake.commands)
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(path),'')) as choose:
            self.pane.analyze.click();wait_all(self.window)
            until(lambda:bool(self.errors))
            for _ in range(20):APP.processEvents();time.sleep(.005)
        self.assertEqual(choose.call_count,1);self.assertEqual(len(self.errors),1)
        self.assertIn('checksum',self.errors[0]);self.assertFalse(self.window.video_events.windows)
        self.assertEqual(self.fake.commands,commands)
