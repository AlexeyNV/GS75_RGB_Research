import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QFileDialog
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from software.gui.vision_window import VisionWindow
from software.vision.perf_fixture import generate_sequence
from test_vision_app import wait_idle

APP=QApplication.instance() or QApplication([])


class BenchmarkGuiTests(unittest.TestCase):
    def test_choose_video_build_off_measure_export_without_console(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);video,data,_=generate_sequence(root/'dataset',(960,540),frames=18)
            window=VisionWindow(remember=False);errors=[];window.error=errors.append;window.show()
            try:
                window.new_project(root/'project.vision-project.json')
                window.load_calibration(root/'dataset/calibration.json',root/'dataset');wait_idle(window)
                pane=window.performance;window.tabs.setCurrentWidget(pane)
                with patch.object(QFileDialog,'getOpenFileName',return_value=(str(video),'')):
                    QTest.mouseClick(pane.choose,Qt.LeftButton)
                wait_idle(window);self.assertIn('960',pane.info.text())
                pane.duration.setValue(.4);pane.frames.setValue(6);pane.warmup.setValue(1)
                QTest.mouseClick(pane.build,Qt.LeftButton);wait_idle(window)
                self.assertIsNotNone(pane.off)
                QTest.mouseClick(pane.run,Qt.LeftButton);wait_idle(window,60)
                self.assertEqual(len(pane.report['runs']),4);self.assertTrue(pane.report['gui_open'])
                self.assertGreater(pane.table.rowCount(),4)
                self.assertTrue((pane.output/'frame_times.png').is_file())
                self.assertEqual(window.batch_table.rowCount(),0)
                export=root/'exports';export.mkdir()
                with patch.object(QFileDialog,'getExistingDirectory',return_value=str(export)):
                    QTest.mouseClick(pane.export,Qt.LeftButton)
                wait_idle(window);self.assertTrue((export/pane.output.name/'frames.csv').is_file())
                self.assertEqual(errors,[])
            finally:
                wait_idle(window)
                if window.calibrator.document:window.calibrator.document.mark_saved()
                window.close();window.deleteLater();APP.processEvents()
