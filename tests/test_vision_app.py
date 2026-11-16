"""Exercise the unified application with actual Qt widgets and background jobs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
from PySide6.QtCore import Qt,QPoint,QPointF,QUrl,QMimeData,QTimer,QThread
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog,QPushButton,QMessageBox
from software.gui.vision_window import VisionWindow
from software.vision.project_storage import ROOT,write_image,image_hash
from software.vision.calibration import create,Document
from software.vision.research_project import DEFAULTS
from vision_fixtures import board,illuminate
from test_video_source import make_video

APP=QApplication.instance() or QApplication([])


def wait_idle(window,timeout=45):
    end=time.monotonic()+timeout;stable=0
    while time.monotonic()<end:
        # QTest.qWait can retain the Python GIL while sleeping, starving a
        # Python QRunnable. Yield it explicitly, as QApplication.exec does.
        APP.processEvents();time.sleep(.005)
        if window.active_job is None and not window.pending_result and window.pool.activeThreadCount()==0:
            stable+=1
            if stable>=3:return
        else:stable=0
    raise AssertionError('GUI job timed out')


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.window=VisionWindow(remember=False);self.errors=[];self.window.error=self.errors.append
        self.window.show();APP.processEvents()
        self.window.new_project(self.root/'session.vision-project.json')
        write_image(self.root/'ref.png',board());data,_=create(self.root/'ref.png',self.root)
        doc=Document(data);doc.add('LED49',None,490,350);doc.save(self.root/'map.json')
        for name,color in [('off',None),('red',(0,0,255)),('green',(0,255,0)),('blue',(255,0,0))]:
            write_image(self.root/(name+'.png'),board() if color is None else illuminate(board(),[(490,350,color)]))

    def tearDown(self):
        self.window.playing=False;self.window.play_timer.stop()
        if self.window.active_job:self.window.active_job.cancel.set()
        wait_idle(self.window)
        if self.window.calibrator.document:self.window.calibrator.document.mark_saved()
        self.window.close();self.window.deleteLater();APP.processEvents()

    def click(self,text):
        button=next(b for b in self.window.findChildren(QPushButton) if b.text()==text)
        QTest.mouseClick(button,Qt.LeftButton);APP.processEvents()

    def load_map(self):
        self.window.load_calibration(self.root/'map.json',self.root);wait_idle(self.window)
        self.assertIsNotNone(self.window.calibrator.document)

    def import_fixture(self):
        paths=[str(self.root/(name+'.png')) for name in ('off','red','green','blue')]
        with patch.object(QFileDialog,'getOpenFileNames',return_value=(paths,'')):
            self.click('Добавить фотографии')
        wait_idle(self.window);self.assertEqual(self.window.media_list.count(),4)
        self.assign_rows([0],'OFF');self.assign_rows([1,2,3],'ON')

    def assign_rows(self,rows,role):
        w=self.window;w.media_list.clearSelection()
        for row in rows:w.media_list.item(row).setSelected(True)
        w.role.setCurrentText(role);self.click('Назначить роль')

    def test_project_map_import_roles_batch_history_and_restore(self):
        self.load_map();self.import_fixture();w=self.window
        self.click('Анализировать выбранные ON');wait_idle(w)
        e=w.project.data['experiments'][0]
        self.assertEqual([r['records'][0]['color'] for r in e['items']],['RED','GREEN','BLUE'])
        self.assertEqual(w.batch_table.rowCount(),3)
        self.assertEqual(w.result_pane.table.item(0,3).text(),'RED')
        self.assertFalse(w.calibrator.document.dirty)
        path=w.project.path;w.open_project(path);wait_idle(w)
        self.assertEqual(w.media_list.count(),4);self.assertEqual(w.history.count(),1)
        self.assertFalse(w.media_list.item(0).icon().isNull())
        self.click('Открыть');wait_idle(w)
        self.assertEqual(w.result_pane.records[0]['led_id'],'LED49')
        self.assertEqual(self.errors,[])

    def test_single_import_and_explorer_drop(self):
        w=self.window
        w.import_paths([str(self.root/'off.png')]);wait_idle(w)
        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(self.root/'red.png')),QUrl.fromLocalFile(str(self.root/'green.png'))])
        enter=QDragEnterEvent(QPoint(10,10),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        APP.sendEvent(w.media_list.viewport(),enter)
        drop=QDropEvent(QPointF(10,10),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        APP.sendEvent(w.media_list.viewport(),drop);wait_idle(w)
        self.assertTrue(drop.isAccepted());self.assertEqual(w.media_list.count(),3)
        self.assertTrue(all(m['role']=='UNASSIGNED' for m in w.project.data['media']))

    def test_missing_and_changed_calibration_are_explicit(self):
        self.load_map();w=self.window
        w.import_paths([str(self.root/'missing.jpg')]);wait_idle(w)
        self.assertTrue(self.errors);self.errors.clear()
        with (self.root/'map.json').open('a') as stream:stream.write(' ')
        w.open_project(w.project.path);wait_idle(w)
        self.assertTrue(any('изменена' in e for e in self.errors))
        self.assertIsNone(w.calibrator.document)

    def test_calibration_autosave_recovery_is_preserved(self):
        self.load_map();w=self.window
        w.calibrator.document.edit('LED49',key_name='Space');w.calibrator.autosave()
        w.calibrator.document.mark_saved()
        draft=Path(str(self.root/'map.json')+'.autosave.json')
        import os
        timestamp=(self.root/'map.json').stat().st_mtime+5
        os.utime(draft,(timestamp,timestamp))
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            w.load_calibration(self.root/'map.json',self.root)
        wait_idle(w)
        self.assertEqual(w.calibrator.document.data['leds'][0]['key_name'],'Space')
        self.assertTrue(w.calibrator.document.dirty)

    def test_cancel_job_and_keep_gui_responsive(self):
        w=self.window;ticks=[]
        timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
        def work(cancel,progress):
            while not cancel.wait(.01):pass
            return QThread.currentThread()!=APP.thread()
        result=[];w.start_job(work,result.append);QTest.qWait(60)
        self.click('Отмена');wait_idle(w);timer.stop()
        self.assertGreater(len(ticks),2);self.assertEqual(result,[True]);self.assertIsNone(w.active_job)

    def test_settings_are_saved_and_advanced_survives_reopen(self):
        w=self.window;w.profile.setCurrentIndex(1);w.setting_controls['threshold'].setValue(47)
        self.click('Применить настройки');w.open_project(w.project.path);wait_idle(w)
        self.assertEqual(w.setting_controls['threshold'].value(),47)
        self.assertEqual(w.profile.currentIndex(),1)

    def test_video_controls_and_selected_frames_reach_analysis(self):
        self.load_map();w=self.window;path=self.root/'test.mp4';make_video(path)
        w.open_video(path);wait_idle(w);self.assertEqual(w.frame_info['frame_index'],0)
        self.click('▶ / ❚❚')
        deadline=time.monotonic()+3
        while w.frame_info['frame_index']==0 and time.monotonic()<deadline:QTest.qWait(20)
        self.click('▶ / ❚❚');wait_idle(w)
        self.assertGreater(w.frame_info['frame_index'],0);self.assertFalse(w.playing)
        self.click('Кадр как OFF');wait_idle(w)
        w.video_slider.setValue(6);w.video_slider.sliderReleased.emit();wait_idle(w)
        self.assertEqual(w.frame_info['frame_index'],6)
        self.click('Предыдущий кадр');wait_idle(w);self.assertEqual(w.frame_info['frame_index'],5)
        self.click('Следующий кадр');wait_idle(w);self.assertEqual(w.frame_info['frame_index'],6)
        self.click('Кадр как ON');wait_idle(w)
        self.click('Анализировать выбранные ON');wait_idle(w)
        self.assertEqual(w.project.data['experiments'][0]['items'][0]['records'][0]['color'],'BLUE')
        capture=w.decoder.capture;w.close();self.assertFalse(capture.isOpened())
        self.assertEqual(self.errors,[])

    def test_result_image_selection_and_layers(self):
        self.load_map();self.import_fixture();w=self.window;self.click('Анализировать выбранные ON');wait_idle(w)
        pane=w.result_pane;pane.image_clicked(490,350)
        self.assertEqual(pane.table.currentRow(),0)
        self.assertIn('color_confidence',pane.details.toPlainText())
        for layer in ('Difference','Color mask','Original ON','Registered OFF','Detected LEDs','Rejected'):
            pane.layers.setCurrentText(layer);wait_idle(w)
            self.assertIsNotNone(pane.viewer.image_item)
        self.assertEqual(self.errors,[])


@unittest.skipUnless(all((ROOT/p).exists() for p in ('data/off.jpg','data/red.jpg','data/green.jpg','data/blue.jpg','config/gs75_board_calibration.json')),'Real RGB photographs absent')
class RealAppAcceptance(unittest.TestCase):
    def test_operator_workflow_three_real_colors_through_gui(self):
        root=ROOT/'build/vision_v03'/('gui_acceptance_'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
        w=VisionWindow(remember=False);errors=[];w.error=errors.append;w.show();APP.processEvents()
        try:
            paths=[ROOT/'data'/f'{name}.jpg' for name in ('off','red','green','blue')]+[ROOT/'config/gs75_board_calibration.json']
            hashes=[image_hash(p) for p in paths]
            w.new_project(root/'gs75_rgb_vision_project.json')
            # Exercise the same Windows file chooser action the operator uses.
            with patch.object(QFileDialog,'getOpenFileName',return_value=(str(paths[-1]),'')):
                w.choose_calibration()
            wait_idle(w)
            with patch.object(QFileDialog,'getOpenFileNames',return_value=([str(p) for p in paths[:4]],'')):
                w.import_dialog()
            wait_idle(w)
            w.media_list.item(0).setSelected(True);w.role.setCurrentText('OFF');w.assign_selected()
            for row in (1,2,3):w.media_list.item(row).setSelected(True)
            w.role.setCurrentText('ON');w.assign_selected()
            w.tabs.setCurrentWidget(w.photos_page);APP.processEvents();w.grab().save(str(root/'photos.png'))
            analyze=next(b for b in w.findChildren(QPushButton) if b.text()=='Анализировать выбранные ON')
            QTest.mouseClick(analyze,Qt.LeftButton);wait_idle(w,100)
            e=w.project.data['experiments'][0]
            self.assertEqual([i['records'][0]['color'] for i in e['items']],['RED','GREEN','BLUE'])
            self.assertTrue(all(i['records'][0]['status']=='ON' for i in e['items']))
            self.assertTrue(all(len([r for r in i['records'] if r['status']=='ON'])==1 for i in e['items']))
            w.result_pane.center_record(0);APP.processEvents();w.grab().save(str(root/'results_red.png'))
            w.open_report_row(2,0);wait_idle(w);w.result_pane.center_record(0);APP.processEvents();w.grab().save(str(root/'results_blue.png'))
            w.tabs.setCurrentWidget(w.calibrator);APP.processEvents();w.grab().save(str(root/'calibration.png'))
            off=next(m for m in w.project.data['media'] if m['role']=='OFF')
            w.run_batch(off['id'],[off['id']]);wait_idle(w,80)
            self.assertEqual(w.project.data['experiments'][-1]['items'][0]['records'][0]['status'],'OFF')
            self.assertEqual(hashes,[image_hash(p) for p in paths]);self.assertEqual(errors,[])
            print('Real GUI acceptance output:',root)
            (ROOT/'build/vision_v03/latest_gui_acceptance.txt').write_text(str(root),encoding='utf-8')
        finally:
            wait_idle(w,100)
            if w.calibrator.document:w.calibrator.document.mark_saved()
            w.close();w.deleteLater();APP.processEvents()
