"""Real Qt interactions on synthetic optical/USB data; no physical transport."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import csv,json,shutil,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QFileDialog,QInputDialog
from software.gui.vision_window import VisionWindow
from software.gui.video_event_results import VideoEventResults
from software.vision.perf_fixture import generate_sequence
from software.vision.video_analysis import analyze_video
from software.vision.experiment_mapping import link_analysis,validate_bundle
from software.vision.project_storage import image_hash
from test_video_event_gui import APP,wait_all


class TimelineGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.video,cls.cal,_=generate_sequence(cls.root/'dataset',(960,540))
        cls.base=cls.root/'base';report=analyze_video(cls.video,cls.cal,cls.base)
        measurements=[]
        for index,event in enumerate(report['events']):
            ack=round((event['start_pts']+5)*1e9)
            measurements.append(dict(command=f"PHOTO LED49 {event['color']} 300",color=event['color'],source=14,
                sink={'RED':32,'GREEN':33,'BLUE':34}[event['color']],duration_ms=300,elapsed_ms=300,status='COMPLETED',
                fault='NONE',reason='TIMEOUT',id=index+1,tx_ns=ack-10_000_000,ack_ns=ack,done_ns=ack+300_000_000))
        cls.session=cls.root/'session.json';cls.session.write_text(json.dumps(dict(session_id='SYNTHETIC',
            monotonic_origin_ns=0,measurements=measurements,simulation=True)),encoding='utf-8')
        link_analysis(cls.base,cls.session)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.window=VisionWindow(remember=False);self.window.show();self.errors=[];self.window.error=self.errors.append
        self.path=self.root/uuid.uuid4().hex;shutil.copytree(self.base,self.path)
        self.result=VideoEventResults(self.window,self.path);self.window.video_events.windows.append(self.result)
        self.result.show();wait_all(self.window)

    def tearDown(self):
        wait_all(self.window);self.result.close();self.window.close();self.window.deleteLater();APP.processEvents()

    def test_separate_lanes_electrical_selection_frame_zoom_filter_totals_and_export(self):
        r=self.result
        self.assertEqual({kind for kind,_,_ in r.timeline.lanes()},{'STM32','CONFIRMED','CANDIDATE','UNKNOWN','OFF'})
        r.timeline.operation_selected.emit('OP0001');wait_all(self.window)
        self.assertEqual(r.current_index,r.events[0]['start_frame']);self.assertIn('STM32 ID=1',r.details.toPlainText())
        self.assertLess(r.timeline.view_end-r.timeline.view_start,1.)
        r.timeline.zoom(10000);self.assertAlmostEqual(r.timeline.view_end-r.timeline.view_start,1/30,places=5)
        r.timeline.pan(.5);self.assertGreater(r.timeline.view_start,0);r.timeline.reset_view()
        r.filter.setCurrentText('CANDIDATE');self.assertEqual(r.event_table.rowCount(),0)
        self.assertIn('CONFIRMED=3',r.summary.text());self.assertIn('показано 0',r.summary.text())
        destination=self.root/uuid.uuid4().hex;destination.mkdir()
        with patch.object(QFileDialog,'getExistingDirectory',return_value=str(destination)):r.export()
        wait_all(self.window)
        manifest=json.loads(next(destination.glob('*/export_manifest.json')).read_text(encoding='utf-8'))
        self.assertEqual(manifest['all_event_counts']['CONFIRMED'],3);self.assertEqual(manifest['display_filter'],'CANDIDATE')
        self.assertEqual(self.errors,[])

    def test_stale_csv_blocked_then_new_immutable_bundle_restores_consistency(self):
        r=self.result;old=r.correspondence_path;file=old/'optical_events.csv'
        with file.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        rows[0]['status']='CANDIDATE'
        with file.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        r.show_tables();self.assertTrue(self.errors);self.assertIn('CSV',self.errors[-1]);self.assertFalse(r.table_windows)
        r.export();self.assertEqual(len(self.errors),2)
        r.refresh_correspondence();wait_all(self.window)
        self.assertNotEqual(r.correspondence_path,old);self.assertTrue(old.is_dir())
        self.assertTrue(validate_bundle(r.correspondence_path,r.report)['valid']);self.assertFalse(r.snapshot_error)

    def test_manual_operation_link_history_keeps_optical_file_and_clock_unchanged(self):
        r=self.result;r.select_event(0);wait_all(self.window)
        original=image_hash(r.path/'events.json');clock=dict(r.correspondence['alignment']);r.target=r.events[0]['event_id']
        label=f"OP0001: ID 1 KP14→KP32 300 мс"
        with patch.object(QInputDialog,'getItem',return_value=(label,True)):r.manual_link()
        wait_all(self.window)
        self.assertEqual(image_hash(r.path/'events.json'),original);self.assertEqual(r.correspondence['alignment'],clock)
        self.assertTrue((r.path/'manual_associations.jsonl').is_file())
        self.assertEqual(next(row for row in r.correspondence['mapping'] if row['operation_key']=='OP0001')['association_source'],'OPERATOR')
        r.manual_link(reset=True);wait_all(self.window)
        self.assertEqual(next(row for row in r.correspondence['mapping'] if row['operation_key']=='OP0001')['association_source'],'ALGORITHM')
