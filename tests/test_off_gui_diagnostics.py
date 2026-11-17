import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from software.gui.vision_window import VisionWindow
from software.gui.off_diagnostics_dialog import OffDiagnosticsDialog
from software.vision.perf_fixture import generate_sequence
from software.vision.off_diagnostics import OffBuildError
from software.vision.project_storage import atomic_json
from test_vision_app import wait_idle

APP=QApplication.instance() or QApplication([])


class OffGuiDiagnosticsTests(unittest.TestCase):
    def test_failure_has_short_message_zero_progress_and_inspectable_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);video,_,_=generate_sequence(root/'dataset',(960,540),frames=18)
            window=VisionWindow(remember=False);errors=[];window.error=errors.append;window.show()
            try:
                window.new_project(root/'project.vision-project.json')
                window.load_calibration(root/'dataset/calibration.json',root/'dataset');wait_idle(window)
                pane=window.performance;pane.select_video(video);wait_idle(window)
                def fail(*args,**kwargs):
                    data=dict(status='FAILED',retained_frames=0,candidates=[dict(frame_index=0,reason='GEOMETRY',selected=False)])
                    path=kwargs['diagnostics_dir'];atomic_json(path/'off_diagnostics.json',data)
                    raise OffBuildError(data,path)
                with patch('software.gui.performance_pane.build_off',side_effect=fail),self.assertLogs(level='ERROR') as logs:
                    pane.build_model();wait_idle(window)
                self.assertEqual(window.progress.value(),0);self.assertIn('FAILED',pane.summary.text())
                self.assertIsNone(pane.off);self.assertIsNone(pane.off_key)
                self.assertIn('принято 0',errors[-1]);self.assertNotIn('Traceback',errors[-1])
                self.assertTrue(any('Traceback' in line for line in logs.output))
                dialog=OffDiagnosticsDialog(pane.diagnostics_path,window)
                self.assertEqual(dialog.table.rowCount(),1);dialog.close()
                # Cancelled search cannot leave a stale READY/100% message.
                def cancellable(cancel,progress):
                    from software.vision.research_project import checkpoint
                    while True:checkpoint(cancel);time.sleep(.005)
                pane.operation='OFF';window.start_job(cancellable,lambda _:None)
                window.cancel_job();wait_idle(window)
                self.assertEqual(window.progress.value(),0);self.assertIn('CANCELLED',pane.summary.text())
                self.assertIsNone(pane.off)
            finally:
                wait_idle(window)
                if window.calibrator.document:window.calibrator.document.mark_saved()
                window.close();window.deleteLater();APP.processEvents()
