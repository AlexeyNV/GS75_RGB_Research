"""MP4 integration, immutable raw results, cancellation and operator provenance."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from software.vision.video_analysis import analyze_video,reaggregate_video
from software.vision.temporal_events import TemporalSettings
from software.vision.video_event_export import save_decision,load_decisions
from software.vision.event_alignment import align_session
from software.vision.perf_fixture import generate_sequence
from software.vision.project_storage import image_hash


class EventPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.video,cls.cal,cls.truth=generate_sequence(cls.root/'dataset',(960,540))
        cls.output=cls.root/'known';cls.report=analyze_video(cls.video,cls.cal,cls.output)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_all_frames_RGB_and_originals_preserved(self):
        r=self.report;self.assertEqual(r['status'],'COMPLETED',r.get('error'))
        self.assertEqual(r['processed_frames'],120)
        events=[e for e in r['events'] if e['status']=='CONFIRMED']
        self.assertEqual([e['color'] for e in events],['RED','GREEN','BLUE'])
        self.assertEqual(len(events),3)
        self.assertEqual(len((self.output/'frame_results.jsonl').read_text(encoding='utf-8').splitlines()),120)
        with (self.output/'frame_observations.csv').open(encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),120);self.assertTrue(any(row['state']=='INVALID_GEOMETRY' for row in rows))
        self.assertEqual({int(row['frame_index']) for row in rows},set(range(120)))
        self.assertEqual(r['source_sha256'],image_hash(self.video));self.assertGreater(r['temporal_ms'],0)
        self.assertTrue((self.output/'timeline.png').is_file());self.assertTrue((self.output/'off_coverage.png').is_file())
        with self.assertRaises(FileExistsError):analyze_video(self.video,self.cal,self.output)

    def test_reaggregate_never_calls_OpenCV_and_keeps_raw(self):
        before={name:image_hash(self.output/name) for name in ('events.json','frame_results.jsonl')}
        with patch('software.vision.video_analysis.VideoEngine',side_effect=AssertionError('OpenCV rerun forbidden')), \
             patch('software.vision.video_analysis.build_off',side_effect=AssertionError('OFF rerun forbidden')):
            report=reaggregate_video(self.output,self.root/'reliable_again',TemporalSettings(min_on_s=.12))
        self.assertEqual(report['status'],'COMPLETED');self.assertFalse(report['opencv_rerun'])
        self.assertEqual(report['processed_frames'],120)
        self.assertEqual(before,{name:image_hash(self.output/name) for name in before})
        self.assertEqual(image_hash(self.root/'reliable_again/frame_results.jsonl'),before['frame_results.jsonl'])

    def test_blind_discovery_has_no_automatic_pcb_id(self):
        report=analyze_video(self.video,self.cal,self.root/'discover',mode='DISCOVER')
        self.assertEqual(report['status'],'COMPLETED');self.assertFalse(report['known_led_coordinates_used'])
        self.assertEqual([e['color'] for e in report['events'] if e['status']=='CONFIRMED'],['RED','GREEN','BLUE'])
        self.assertTrue(all(e['led_id'] is None for e in report['events']))
        self.assertTrue(any(t['status']=='CONFIRMED' for t in report['unknown_tracks']))

    def test_cancel_keeps_partial_observations(self):
        cancel=threading.Event()
        def progress(current,total,value):
            if value.get('name')=='VIDEO_ANALYSIS' and current>=10:cancel.set()
        report=analyze_video(self.video,self.cal,self.root/'cancelled',cancel=cancel,notify=progress)
        self.assertEqual(report['status'],'CANCELLED');self.assertEqual(report['processed_frames'],10)
        self.assertEqual(len((self.root/'cancelled/frame_results.jsonl').read_text(encoding='utf-8').splitlines()),10)
        self.assertTrue((self.root/'cancelled/events.json').exists())

    def test_OFF_error_is_saved_without_fabricated_frames(self):
        with patch('software.vision.video_analysis.build_off',side_effect=ValueError('No reliable background')),self.assertLogs(level='ERROR'):
            report=analyze_video(self.video,self.cal,self.root/'failed')
        self.assertEqual(report['status'],'FAILED');self.assertEqual(report['processed_frames'],0)
        self.assertTrue((self.root/'failed/validation_report.md').exists())

    def test_operator_decisions_do_not_mutate_automatic_results(self):
        before=image_hash(self.output/'events.json')
        save_decision(self.output,'TRACK0001','ACCEPTED','Visually inspected','LED777')
        save_decision(self.output,'TRACK0001','REJECTED','Reconsidered')
        save_decision(self.output,'TRACK0001','RESET')
        self.assertEqual(load_decisions(self.output)['TRACK0001']['decision'],'RESET')
        self.assertEqual(image_hash(self.output/'events.json'),before)
        self.assertEqual(len((self.output/'manual_decisions.jsonl').read_text(encoding='utf-8').splitlines()),3)

    def test_benchmark_still_measures_video_without_pts_but_does_not_invent_temporal_time(self):
        from software.vision.pts_video import SequentialVideoReader
        from software.vision.off_background import OffModel,identity_registration
        from software.vision.project_storage import read_image
        from software.vision.video_benchmark import run_variant
        class NoPTS(SequentialVideoReader):
            def frame(self,index):
                image,info=super().frame(index);return image,dict(info,timestamp_ms=None)
        metadata=json.loads((self.output/'off_model/off_model.json').read_text(encoding='utf-8'))
        image=read_image(self.output/'off_model/off.png');mask=read_image(self.output/'off_model/valid_mask.png')[:,:,0]
        off=OffModel(image,mask,identity_registration(image,mask,metadata),self.cal['calibration_version'],metadata,image)
        with patch('software.vision.video_benchmark.SequentialVideoReader',NoPTS):
            report=run_variant(self.video,self.cal,off,'C_HYBRID',threading.Event(),limit=2,warmup=0)
        self.assertEqual(report['decoded_measured'],2)
        self.assertEqual(report['temporal']['status'],'UNAVAILABLE_MISSING_PTS')
        self.assertEqual(report['temporal']['events'],[])


class AlignmentTests(unittest.TestCase):
    def test_unique_posthoc_alignment_without_changing_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);events=[];measurements=[];tx=[]
            for i,color in enumerate(['BLUE','RED','GREEN']):
                t=1+i*3
                events.append(dict(event_id=str(i),entity='OPTICAL',led_id=None,status='CONFIRMED',color=color,
                    start_pts=t,end_pts=t+.97,duration_s=.97,signal_start_interval_s=[t-.033,t],uncertainty_flags=[]))
                command=f'PHOTO LED123 {color} 1000';ack=int((t+5.01)*1e9)
                measurements.append(dict(command=command,status='COMPLETED',fault='NONE',reason='TIMEOUT',id=i,ack_ns=ack,done_ns=ack+10**9))
                tx.append(dict(direction='TX',text=command,monotonic_ns=ack-20_000_000))
            (root/'session.json').write_text(json.dumps(dict(monotonic_origin_ns=0,measurements=measurements)),encoding='utf-8')
            (root/'events.jsonl').write_text('\n'.join(map(json.dumps,tx)),encoding='utf-8')
            original=deepcopy(events);result=align_session(events,root/'session.json')
            self.assertEqual(events,original);self.assertEqual(result['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
            self.assertAlmostEqual(result['offset_s'],5.01);self.assertGreater(result['uncertainty_s'],0.)
            ambiguous=events+[dict(e,entity='SECOND') for e in events]
            self.assertEqual(align_session(ambiguous,root/'session.json')['status'],'AMBIGUOUS')
            events[0]['color']='GREEN';self.assertEqual(align_session(events,root/'session.json')['status'],'NO_MATCH')
