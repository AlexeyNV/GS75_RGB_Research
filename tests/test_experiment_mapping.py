"""Independent sampled optical pulses, missing evidence and many-to-one clocks."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from software.hardware.experiment import Experiment
from software.hardware.scenario import CONDITIONS,SHORT_NAME,short_scenario
from software.hardware.simulator import SimulatedCDC
from software.hardware.electrical_operations import load_operations
from software.vision.temporal_events import TemporalDetector,profile_settings
from software.vision.experiment_mapping import build_tables,align_operations
from test_temporal_events import obs


def fixture(root,repeats=3,marker=True,phase=0.,fps=30.,missing=None,geometry=None,drop_frames=(),extra=False,two=False):
    fake=SimulatedCDC();engine=Experiment(fake,'SIMULATED',root,fake.clock.now_ns)
    config=dict(repeats=repeats,marker=marker,order='shuffled',seed=173)
    session=engine.run_sequence(short_scenario(**config),dict.fromkeys(CONDITIONS,True),SHORT_NAME,config)
    if session['status']!='COMPLETED':raise AssertionError(session)
    path=engine.journal.path/'session.json';_,operations=load_operations(path)
    pulses=[(o['host_tx_s']+2,o['host_tx_s']+2+o['requested_duration_ms']/1000,o) for o in operations]
    rows=[];detector=TemporalDetector(profile_settings(True));end=fake.clock.now_ns()/1e9+2.5
    for frame in range(int(end*fps)):
        if frame in drop_frames:continue
        t=frame/fps+phase;active=next((o for a,b,o in pulses if a<=t<b),None)
        state='ON' if active and active['operation_key']!=missing else 'OFF'
        if any(o['operation_key']==geometry and a-.1<=t<=b+.1 for a,b,o in pulses):state='INVALID_GEOMETRY'
        if extra and 1.<=t<1.+1/fps:state='ON'
        row=obs(t,state,frame=frame,entity='LED49');rows.append(row);detector.feed(row)
    events=detector.finish()
    if two:
        events += [dict(e,event_id='SECOND_'+e['event_id'],entity='TRACK_TWO',led_id=None) for e in list(events)]
    report=dict(events=events,video=dict(fps=fps),processed_frames=len(rows),uncertainty_intervals=detector.uncertainty)
    observations=root/'observations.csv'
    with observations.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return path,operations,report,observations


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_phase_100_200_300_30fps_and_60fps_detection_is_separate_from_duration(self):
        for fps in (30.,60.):
            for phase in (0.,.0001,.011,.025):
                with self.subTest(fps=fps,phase=phase):
                    root=self.root/f'{fps}_{phase}';root.mkdir()
                    path,ops,report,observations=fixture(root,phase=phase,fps=fps)
                    before=deepcopy(report['events']);result=build_tables(report,path,root/'tables',observations)
                    self.assertEqual(report['events'],before)
                    self.assertEqual(result['alignment']['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
                    self.assertAlmostEqual(result['alignment']['offset_s'],-2.,delta=1/fps)
                    self.assertEqual(len(result['mapping']),10)
                    self.assertEqual([r['requested'] for r in result['short_pulse_summary']],[3,3,3])
                    self.assertTrue(all(r['detected_operations']==3 for r in result['short_pulse_summary']))
                    self.assertTrue(all(r['mapping_status']=='OPTICAL_CANDIDATE' for r in result['mapping']))
                    self.assertIsNone(result['minimum_reliable_duration_ms'])
                    for r in result['boundary_residuals']:
                        self.assertLessEqual(abs(r['start_residual_s']),1/fps+.003)
                        self.assertLessEqual(abs(r['end_residual_s']),2/fps+.003)

    def test_missed_vs_unobservable_geometry_and_marker_excluded_from_summary(self):
        path,ops,report,observations=fixture(self.root,missing='OP0003',geometry='OP0005')
        result=build_tables(report,path,self.root/'tables',observations)
        self.assertEqual(result['alignment']['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
        by_op={r['operation_key']:r for r in result['mapping']}
        self.assertEqual(by_op['OP0003']['optical_status'],'MISSED')
        self.assertEqual(by_op['OP0005']['optical_status'],'UNOBSERVABLE')
        self.assertIsNone(by_op['OP0005']['optical_start_pts']);self.assertIsNone(by_op['OP0005']['optical_confidence'])
        self.assertEqual(sum(r['requested'] for r in result['short_pulse_summary']),9)
        self.assertEqual(sum(r['missed'] for r in result['short_pulse_summary']),1)
        self.assertEqual(sum(r['unobservable'] for r in result['short_pulse_summary']),1)

    def test_partial_frames_and_extra_candidate_are_not_forced_into_operations(self):
        path,ops,report,observations=fixture(self.root,drop_frames=(256,257),extra=True)
        result=build_tables(report,path,self.root/'tables',observations)
        self.assertEqual(result['alignment']['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
        self.assertEqual(len(result['extra_optical_event_ids']),1)
        self.assertTrue(all(r['false_detections_unreviewed'] is None for r in result['short_pulse_summary']))
        self.assertTrue(any(u['state']=='UNCERTAIN' for u in report['uncertainty_intervals']))

    def test_two_optical_positions_one_operation_and_manual_verification_separate(self):
        path,ops,report,observations=fixture(self.root,two=True)
        result=build_tables(report,path,self.root/'first',observations)
        self.assertEqual(result['alignment']['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
        self.assertEqual(len(result['mapping']),20)
        tracks=[r for r in result['mapping'] if r['optical_track_id']]
        self.assertTrue(all(r['pcb_led_id'] is None for r in tracks))
        second=build_tables(report,path,self.root/'reviewed',observations,
            dict(TRACK_TWO=dict(decision='ACCEPTED',pcb_led_id='LED123')))
        self.assertTrue(all(r['mapping_status']=='VERIFIED' and r['pcb_led_id']=='LED123' for r in second['mapping'] if r['optical_track_id']))
        self.assertTrue((self.root/'first/electrical_optical_mapping.csv').is_file())
        with self.assertRaises(FileExistsError):build_tables(report,path,self.root/'first',observations)

    def test_ambiguous_periodic_sequence_never_chooses_nearest_or_uses_utc(self):
        ops=[dict(operation_key=f'OP{i}',operation_id=i,electrical_status='COMPLETED',host_ack_s=i+5.,
             host_tx_s=i+4.99,host_done_s=i+5.1,requested_duration_ms=100,color='RED',pcb_led_id=None,role='SHORT_PULSE') for i in range(4)]
        events=[dict(event_id=f'EV{i}',entity='TRACK1',led_id=None,status='CONFIRMED',color='RED',
                start_pts=i,end_pts=i+.067,duration_s=.067) for i in range(5)]
        result=align_operations(events,ops)
        self.assertEqual(result['status'],'AMBIGUOUS');self.assertIsNone(result['offset_s'])
        self.assertGreaterEqual(len(result['candidates']),2)

    def test_no_alignment_no_observations_and_failed_operation_do_not_fabricate_zeros(self):
        path,ops,report,observations=fixture(self.root,repeats=1)
        report['events']=[]
        result=build_tables(report,path,self.root/'tables')
        self.assertEqual(result['alignment']['status'],'NO_MATCH')
        self.assertTrue(all(r['mapping_status']=='ELECTRICAL_ONLY' for r in result['mapping']))
        self.assertTrue(all(r['optical_start_pts'] is None for r in result['mapping']))
        self.assertEqual(sum(r['unaligned'] for r in result['short_pulse_summary']),3)

    def test_ten_trials_report_empirical_minimum_with_statistical_limits_not_hardware_claim(self):
        path,ops,report,observations=fixture(self.root,repeats=10)
        result=build_tables(report,path,self.root/'tables',observations)
        self.assertEqual(result['series_minimum_all_confirmed_ms'],100)
        self.assertIsNone(result['minimum_reliable_duration_ms']);self.assertTrue(result['simulation'])
        for row in result['short_pulse_summary']:
            self.assertEqual(row['confirmed_operations'],10);self.assertEqual(row['confirmation_rate'],1.)
            self.assertAlmostEqual(row['confirmation_rate_wilson95'][0],.7224672,places=5)
            self.assertTrue(row['signal_means']);self.assertTrue(row['start_residuals_s'])

    def test_uncertain_exposure_is_unobservable_not_missed(self):
        path,ops,report,observations=fixture(self.root,missing='OP0003')
        operation=ops[2];start=operation['host_tx_s']+2
        with observations.open(encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
        for row in rows:
            if start-.1<=float(row['pts_s'])<=start+operation['requested_duration_ms']/1000+.1:row['state']='UNCERTAIN'
        with observations.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        result=build_tables(report,path,self.root/'tables',observations)
        row=next(r for r in result['mapping'] if r['operation_key']=='OP0003')
        self.assertEqual(row['optical_status'],'UNOBSERVABLE')
