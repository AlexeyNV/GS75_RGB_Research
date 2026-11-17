"""Actual Qt widgets and CDC worker; every transport is injected, no real ports."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QThread
from software.gui.vision_window import VisionWindow
from software.hardware.scenario import CONDITIONS
from software.hardware.simulator import SimulatedCDC
from test_video_source import make_video

APP=QApplication.instance() or QApplication([])


def until(predicate, timeout=12):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        APP.processEvents();time.sleep(.003)
        if predicate(): return
    raise AssertionError('Qt / worker timed out')


class ExperimentGUI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.window=VisionWindow(remember=False);self.window.show();APP.processEvents()
        self.pane=self.window.experiment;self.worker=self.pane.worker
        self.fake=SimulatedCDC();self.worker.root=self.root/'experiments'
        self.worker.clock_ns=self.fake.clock.now_ns
        self.threads=[]
        def factory(port):
            self.threads.append(QThread.currentThread());return self.fake
        self.worker.factory=factory
        self.errors=[];self.window.error=self.errors.append

    def tearDown(self):
        self.worker.shutdown()
        until(lambda:not self.worker.isRunning())
        if self.window.active_job:
            self.window.cancel_job();until(lambda:self.window.active_job is None)
        self.window.close();self.window.deleteLater();APP.processEvents()

    def connect(self):
        self.pane.ports.setEditText('SIMULATED');self.pane.connect_button.click()
        until(lambda:self.pane.ready and not self.pane.busy)

    def run_short(self):
        for control in self.pane.controls.values():control.setValue(100)
        with patch.object(self.pane,'confirm_conditions',return_value=dict.fromkeys(CONDITIONS,True)), \
             patch.object(QMessageBox,'question',return_value=QMessageBox.No):
            self.pane.start.click()
            until(lambda:self.pane.session_path is not None)

    def test_open_connect_only_diagnostics_and_thread_ownership(self):
        self.assertEqual(self.fake.commands,[]);self.assertFalse(self.worker.isRunning())
        self.connect()
        self.assertEqual(self.fake.commands,['PING','INFO','STATUS','ADCSTATUS','SELFTEST'])
        self.assertTrue(self.pane.start.isEnabled())
        self.assertIsNot(self.threads[0],APP.thread())

    def test_explicit_confirmation_rejected_never_lights(self):
        self.connect()
        with patch.object(self.pane,'confirm_conditions',return_value=None):
            self.pane.start.click();until(lambda:not self.pane.preparing)
        self.assertFalse(any(c.startswith(('ARM','PHOTO')) for c in self.fake.commands))
        self.assertIsNone(self.pane.session_path)

    def test_completed_sequence_gui_and_import_benchmark_handoff(self):
        self.connect();self.run_short()
        self.assertIn('COMPLETED',self.pane.outcome.text());self.assertTrue(self.pane.off.isEnabled())
        self.assertEqual(self.pane.progress.value(),self.pane.progress.maximum())
        video=self.root/'external.mp4';make_video(video)
        self.pane.import_video(video);until(lambda:self.pane.video is not None and self.window.active_job is None)
        self.assertTrue(self.pane.benchmark.isEnabled())
        self.pane.benchmark.click();until(lambda:self.window.active_job is None)
        self.assertEqual(self.window.performance.video,video)
        self.assertIs(self.window.tabs.currentWidget(),self.window.performance)
        self.pane.view.click();until(lambda:self.window.active_job is None)
        self.assertEqual(self.window.video_path,video)
        self.assertIs(self.window.tabs.currentWidget(),self.window.video_page)
        self.assertEqual(self.errors,[])

    def test_busy_port_is_reported_and_start_disabled(self):
        def busy(port):raise OSError('Access denied: busy COM19')
        self.worker.factory=busy;self.pane.ports.setEditText('COM19');self.pane.connect_button.click()
        until(lambda:'busy COM19' in self.pane.outcome.text())
        self.assertFalse(self.pane.start.isEnabled());self.assertFalse(self.pane.connected)
        self.assertIn('PuTTY',self.pane.outcome.text())

    def test_incompatible_fw_blocks_start(self):
        self.fake.failure='version';self.pane.ports.setEditText('SIM');self.pane.connect_button.click()
        until(lambda:'0.1.2' in self.pane.outcome.text() and not self.pane.busy)
        self.assertFalse(self.pane.start.isEnabled())
        self.assertFalse(any(c.startswith('ARM') for c in self.fake.commands))

    def test_off_during_photo_is_not_queued_behind_done(self):
        self.connect()
        original=self.fake.read
        def read(timeout):time.sleep(.001);return original(timeout)
        self.fake.read=read
        for key in ('initial_ms','pause_ms','final_ms'):self.pane.controls[key].setValue(100)
        with patch.object(self.pane,'confirm_conditions',return_value=dict.fromkeys(CONDITIONS,True)):
            self.pane.start.click();until(lambda:self.fake.active is not None)
        self.assertTrue(self.pane.off.isEnabled());self.pane.off.click()
        until(lambda:self.pane.session_path is not None)
        self.assertIn('ABORTED',self.pane.outcome.text())
        self.assertIsNone(self.fake.active);self.assertEqual(self.fake.state,'DISARMED')
        self.assertEqual(len([c for c in self.fake.commands if c.startswith('PHOTO')]),1)

    def test_closing_gui_during_photo_stops_worker_and_outputs(self):
        self.connect()
        original=self.fake.read
        def read(timeout):time.sleep(.001);return original(timeout)
        self.fake.read=read
        self.pane.controls['initial_ms'].setValue(100)
        with patch.object(self.pane,'confirm_conditions',return_value=dict.fromkeys(CONDITIONS,True)):
            self.pane.start.click();until(lambda:self.fake.active is not None)
        self.window.close()
        until(lambda:not self.worker.isRunning() and not self.window.isVisible())
        self.assertTrue(self.fake.closed);self.assertIsNone(self.fake.active)
        self.assertTrue(self.worker.last_off_confirmed)
        self.assertEqual(len([c for c in self.fake.commands if c.startswith('PHOTO')]),1)

    def test_closing_with_lost_usb_warns_physical_state_unknown(self):
        self.connect();self.fake.disconnected=True
        with patch.object(QMessageBox,'warning') as warning:
            self.window.close()
            until(lambda:not self.worker.isRunning() and not self.window.isVisible())
            self.assertTrue(warning.called)
            self.assertIn('питание',warning.call_args.args[2])
        self.assertFalse(self.worker.last_off_confirmed)
