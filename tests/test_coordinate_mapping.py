import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PySide6.QtCore import QPointF,Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication
from software.gui.board_calibrator import Calibrator
from software.vision.project_storage import write_image
from vision_fixtures import board

APP=QApplication.instance() or QApplication([])


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); write_image(self.root/'reference.png',board())
        self.window=Calibrator(self.root); self.window.set_reference(self.root/'reference.png')
        self.window.show(); APP.processEvents()
        self.assertTrue(QFontMetrics(self.window.font()).inFont('A'))

    def tearDown(self):
        self.window.document.mark_saved(); self.window.close(); self.window.deleteLater(); APP.processEvents()

    def test_zoom_pan_coordinates_and_table(self):
        w=self.window; w.document.add('LED49',None,490.123456789,350.98765); w.refresh()
        for zoom in [1,2,4,8]:
            w.viewer.set_zoom(zoom); w.viewer.centerOn(490,350); APP.processEvents()
            point=QPointF(490.12345,350.98765)
            actual=w.viewer.mapToScene(w.viewer.mapFromScene(point))
            self.assertLess(abs(actual.x()-point.x()),1/zoom+1e-6)
            self.assertLess(abs(actual.y()-point.y()),1/zoom+1e-6)
        self.assertEqual(w.document.data['leds'][0]['x_ref_px'],490.123456789)
        w.select_led('LED49'); w.editor.key.setText('Enter'); w.apply_edit()
        self.assertEqual(w.document.data['leds'][0]['key_name'],'Enter')
        self.assertEqual(w.document.data['leds'][0]['x_ref_px'],490.123456789)
        w.move_led('LED49',500.25,360.125); w.undo(); self.assertEqual(w.document.data['leds'][0]['x_ref_px'],490.123456789)
        w.redo(); w.delete_led(); self.assertEqual(len(w.document.data['leds']),0); w.undo()
        w.search.setText('no match'); self.assertTrue(w.table.isRowHidden(0))

    def test_click_mapping_and_save_load(self):
        w=self.window; w.viewer.add_mode=True; received=[]
        w.viewer.pointClicked.disconnect(); w.viewer.pointClicked.connect(lambda x,y:received.append((x,y)))
        w.viewer.set_zoom(4); w.viewer.centerOn(490,350); APP.processEvents()
        expected=QPointF(495,353); pixel=w.viewer.mapFromScene(expected)
        QTest.mouseClick(w.viewer.viewport(),Qt.LeftButton,pos=pixel)
        self.assertAlmostEqual(received[0][0],495,delta=.26); self.assertAlmostEqual(received[0][1],353,delta=.26)
        w.document.add('LED49',None,*received[0]); w.refresh()
        path=self.root/'map.json'; w.document.save(path); w.load_map(path)
        self.assertEqual(w.document.data['leds'][0]['led_id'],'LED49')
        w.document.edit('LED49',note='draft'); w.project_path=path; w.autosave()
        self.assertTrue(Path(str(path)+'.autosave.json').exists())

    def test_high_resolution_image(self):
        # Actual 48 MP loading/display, not a scaled-down proxy.
        path=self.root/'large.png'; write_image(path,np.full((6000,8000,3),120,np.uint8))
        self.window.set_reference(path)
        self.assertEqual(self.window.document.data['reference']['width'],8000)
        self.assertEqual(self.window.viewer.sceneRect().height(),6000)

    def test_actual_add_dialog_and_dense_table(self):
        w=self.window; self.assertFalse(w.autonumber.isChecked())
        def accept_dialog():
            dialog=APP.activeModalWidget(); dialog.editor.id.setText('LED49'); dialog.editor.key.setText(''); dialog.accept()
        QTimer.singleShot(0,accept_dialog); w.add_at(490.25,350.5)
        self.assertEqual(w.document.data['leds'][0]['led_id'],'LED49')
        self.assertIsNone(w.document.data['leds'][0]['key_name'])
        for i in range(50,200): w.document.add(f'LED{i}','Space',200+i,400)
        w.refresh(); self.assertEqual(w.table.rowCount(),151)
        self.assertEqual(sum(label.isVisible() for label in w.viewer.labels.values()),1)
        self.assertIn('LED49',w.viewer.led_items['LED49'].toolTip())

    def test_analysis_review_opens(self):
        from software.gui.image_comparator import AnalysisDialog
        from software.vision.led_detection import analyze
        from vision_fixtures import illuminate
        self.window.document.add('LED49',None,490,350)
        analysis=analyze(self.window.document.data,board(),illuminate(board(),[(490,350,(0,0,255))]))
        dialog=AnalysisDialog(analysis,self.window); dialog.show(); APP.processEvents()
        self.assertEqual(dialog.table.rowCount(),1); dialog.toggle_overlay(); dialog.show_image('Original ON')
        dialog.close(); dialog.deleteLater(); APP.processEvents()

    def test_drag_and_middle_button_pan(self):
        w=self.window; w.document.add('LED49',None,490,350); w.refresh()
        w.viewer.set_zoom(4); w.viewer.centerOn(490,350); APP.processEvents()
        old=w.viewer.mapFromScene(QPointF(490,350)); new=old+type(old)(40,20)
        QTest.mousePress(w.viewer.viewport(),Qt.LeftButton,pos=old)
        QTest.mouseMove(w.viewer.viewport(),new,10); QTest.mouseRelease(w.viewer.viewport(),Qt.LeftButton,pos=new)
        APP.processEvents()
        led=w.document.data['leds'][0]
        self.assertAlmostEqual(led['x_ref_px'],500,delta=.5); self.assertAlmostEqual(led['y_ref_px'],355,delta=.5)
        before=w.viewer.horizontalScrollBar().value()
        QTest.mousePress(w.viewer.viewport(),Qt.MiddleButton,pos=old)
        QTest.mouseMove(w.viewer.viewport(),new,10); QTest.mouseRelease(w.viewer.viewport(),Qt.MiddleButton,pos=new)
        self.assertNotEqual(before,w.viewer.horizontalScrollBar().value())
