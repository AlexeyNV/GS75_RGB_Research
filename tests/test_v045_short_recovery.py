"""Real numeric replay and adversarial fragment association; no hardware/CV."""
from collections import Counter
from copy import deepcopy
import gzip,json,csv
from pathlib import Path
import tempfile
import unittest
from software.vision.temporal_events import TemporalDetector,TemporalSettings,profile_settings,observation
from software.vision.observation_diagnostics import categories,uncertainty_statistics
from software.vision.experiment_mapping import align_operations,build_tables,validate_bundle,save_association,load_associations
from software.hardware.electrical_operations import load_operations
from test_temporal_events import obs,detect


TRACE=Path(__file__).parent/'fixtures/v045_short_observations.json.gz'


def replay(data,settings=None):
    detector=TemporalDetector(settings or profile_settings(True));rows=[]
    for frame in data['frames']:
        geometry=frame['result']['registrations']['on']
        for led in data['leds']:
            record=next((r for r in frame['result']['records'] if r['led_id']==led['led_id']),None)
            row=observation(record,frame,geometry,led['led_id'],led,data['coverage'][led['led_id']])
            row['uncertainty_categories']=categories(row,geometry);rows.append(row);detector.feed(row)
    return detector.finish(),detector.uncertainty,rows


class RealShortRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(gzip.decompress(TRACE.read_bytes()))
        cls.events,cls.unknown,cls.rows=replay(cls.data)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.session=self.root/'session.json';self.session.write_text(json.dumps(self.data['session']),encoding='utf-8')
        _,self.ops=load_operations(self.session)

    def test_independent_1418_frames_29_confirmed_one_candidate_all_positive_evidence_preserved(self):
        events=self.events
        self.assertEqual(len(self.rows),1418);self.assertEqual(Counter(e['status'] for e in events),{'CONFIRMED':29,'CANDIDATE':1})
        self.assertEqual({e['color'] for e in events},{'RED'})
        positive={r['frame_index'] for r in self.rows if r['state']=='ON'}
        recovered=[i for e in events for i in e['positive_frame_indices']]
        self.assertEqual(len(positive),169);self.assertEqual(set(recovered),positive);self.assertEqual(len(recovered),169)
        candidate=next(e for e in events if e['status']=='CANDIDATE')
        self.assertEqual(candidate['positive_frame_indices'],[209,211]);self.assertEqual(candidate['max_consecutive_good_observations'],1)
        self.assertIn('NO_CONSECUTIVE_GOOD_PAIR',candidate['uncertainty_flags']);self.assertFalse(candidate['duration_confirmed'])
        self.assertLess(candidate['confidence'],.5)
        self.assertEqual(sum(bool(e['unknown_gaps']) for e in events),7)
        self.assertTrue(all(not e['duration_confirmed'] for e in events))

    def test_baseline_settings_reproduce_37_original_records_and_new_matcher_preserves_them(self):
        events,_,_=replay(self.data,TemporalSettings(**self.data['baseline_settings']))
        self.assertEqual(Counter(e['status'] for e in events),{'CONFIRMED':31,'CANDIDATE':6})
        keys=('event_id','status','start_pts','end_pts','confidence')
        self.assertEqual([{k:e[k] for k in keys} for e in events],[{k:e[k] for k in keys} for e in self.data['baseline_events']])
        before=deepcopy(events);alignment=align_operations(events,self.ops)
        self.assertEqual(events,before);self.assertEqual(len(alignment['associations']),37)
        self.assertEqual(len({p['operation_key'] for p in alignment['associations']}),30)
        self.assertEqual(sum(p['operation_key']=='OP0004' for p in alignment['associations']),2)

    def test_all_30_associate_without_promoting_candidate_or_confidence(self):
        before=deepcopy(self.events);report=dict(events=self.events,video=dict(fps=29.92),algorithm_version='0.4.5')
        result=build_tables(report,self.session,self.root/'tables')
        self.assertEqual(self.events,before);self.assertEqual(len(result['mapping']),30)
        self.assertEqual(Counter(r['optical_status'] for r in result['mapping']),{'CONFIRMED':29,'CANDIDATE':1})
        self.assertEqual(result['extra_optical_event_ids'],[])
        self.assertAlmostEqual(result['alignment']['video_minus_host_tx_s'],-1.81,delta=.01)
        self.assertEqual(len(result['alignment']['candidates'][0]['pairs']),27)
        for row in result['mapping']:
            e=next(e for e in self.events if e['event_id']==row['optical_event_id'])
            self.assertEqual(row['optical_confidence'],e['confidence'])
        self.assertTrue(all(r['association_kind']=='PARTIAL_OPTICAL_EVIDENCE' for r in result['mapping'] if r['operation_id'] in (4,12,14)))

    def test_exact_unknown_cause_counts_geometry_is_not_absence_of_light(self):
        stats=uncertainty_statistics(self.rows,self.events,self.unknown)
        self.assertEqual(stats['unique_unknown_frames'],1059)
        expected={'ARUCO_LOSS':(0,0),'BAD_HOMOGRAPHY':(5,5),'ROI_COVERAGE':(132,113),
                  'LOW_COLOR_SIGNAL':(922,237),'AMBIGUOUS_COLOR':(0,0),'TEMPORAL_CONTINUITY':(7,7),'OTHER':(0,0)}
        self.assertEqual({k:(v['frames'],v['intervals']) for k,v in stats['by_reason'].items()},expected)
        self.assertEqual(sum(r['state']=='OFF' for r in self.rows),190)

    def test_LED_name_and_translation_are_not_rules(self):
        data=deepcopy(self.data);data['leds'][0]['led_id']='LED777';data['coverage']['LED777']=data['coverage'].pop('LED49')
        for frame in data['frames']:
            for record in frame['result']['records']:
                record['led_id']='LED777'
                for key in ('x_ref_px','signal_x_ref_px'):
                    if key in record:record[key]+=123
        events,_,_=replay(data)
        self.assertEqual([(e['status'],e['start_pts'],e['end_pts']) for e in events],[(e['status'],e['start_pts'],e['end_pts']) for e in self.events])

    def test_stale_snapshot_is_rejected_and_manual_association_does_not_recalibrate(self):
        report=dict(events=self.events,video=dict(fps=29.92),algorithm_version='0.4.5')
        first=build_tables(report,self.session,self.root/'first');self.assertTrue(validate_bundle(self.root/'first',report)['valid'])
        changed=deepcopy(report);changed['events'][0]['status']='CANDIDATE'
        self.assertFalse(validate_bundle(self.root/'first',changed)['valid'])
        candidate=next(e for e in self.events if e['status']=='CANDIDATE')
        save_association(self.root,'OP0004',candidate['event_id'],'ACCEPTED','Synthetic review action on a numeric fixture only')
        second=build_tables(report,self.session,self.root/'second',manual_associations=load_associations(self.root))
        row=next(r for r in second['mapping'] if r['operation_key']=='OP0004')
        self.assertEqual(row['mapping_status'],'VERIFIED');self.assertEqual(row['optical_status'],'CANDIDATE')
        self.assertEqual(first['alignment'],second['alignment']);self.assertLess(row['optical_confidence'],.5)
        save_association(self.root,None,candidate['event_id'],'RESET')
        third=build_tables(report,self.session,self.root/'third',manual_associations=load_associations(self.root))
        self.assertEqual(next(r for r in third['mapping'] if r['operation_key']=='OP0004')['mapping_status'],'OPTICAL_CANDIDATE')

    def test_manual_association_without_clock_solution_keeps_pts_alignment_unknown(self):
        candidate=next(e for e in self.events if e['status']=='CANDIDATE')
        report=dict(events=[candidate],video=dict(fps=29.92),algorithm_version='0.4.5')
        result=build_tables(report,self.session,self.root/'manual_no_clock',manual_associations={candidate['event_id']:
            dict(operation_key='OP0004',decision='ACCEPTED')})
        self.assertEqual(result['alignment']['status'],'NO_MATCH');self.assertIsNone(result['alignment']['offset_s'])
        row=next(r for r in result['mapping'] if r['operation_key']=='OP0004')
        self.assertEqual(row['mapping_status'],'VERIFIED');self.assertEqual(row['optical_status'],'CANDIDATE')
        self.assertEqual(row['optical_confidence'],candidate['confidence']);self.assertEqual(result['boundary_residuals'],[])


class FragmentNegatives(unittest.TestCase):
    def test_encoded_mp4_without_light_produces_no_events(self):
        from software.vision.perf_fixture import generate_sequence
        from software.vision.video_analysis import analyze_video
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);video,cal,_=generate_sequence(root/'off_video',(960,540),frames=60)
            report=analyze_video(video,cal,root/'analysis',settings=profile_settings(True))
            self.assertEqual(report['status'],'COMPLETED');self.assertEqual(report['processed_frames'],60)
            self.assertEqual(report['events'],[]);self.assertEqual(report['state_counts'].get('ON',0),0)

    def test_two_isolated_glints_with_unknown_between_remain_candidate(self):
        rows=[obs(i/30,'ON' if i in (1,3) else ('INVALID_GEOMETRY' if i==2 else 'OFF'),frame=i) for i in range(6)]
        _,events=detect(rows,profile_settings(True))
        self.assertEqual(len(events),1);self.assertEqual(events[0]['status'],'CANDIDATE');self.assertTrue(events[0]['unknown_gaps'])
        rows[2]['state']='OFF'
        _,events=detect(rows,profile_settings(True))
        self.assertEqual(len(events),2);self.assertTrue(all(e['status']=='CANDIDATE' for e in events))

    def test_time_limit_still_splits_long_geometry_loss(self):
        rows=[obs(i/30,'ON' if i in (1,2,6,7) else ('INVALID_GEOMETRY' if 3<=i<=5 else 'OFF'),frame=i) for i in range(10)]
        _,events=detect(rows,profile_settings(True))
        self.assertEqual(len(events),2);self.assertTrue(all(e['status']=='CONFIRMED' for e in events))

    def test_multiple_temporal_fragments_and_spatial_sources_one_operation(self):
        ops=[];events=[]
        for i,color in enumerate(('RED','GREEN','BLUE','RED')):
            start=i*2;duration=1000 if i<3 else 300
            ops.append(dict(operation_key=f'OP{i}',operation_id=i,host_ack_s=start+5.,host_tx_s=start+4.99,
                host_done_s=start+5.+duration/1000,electrical_status='COMPLETED',requested_duration_ms=duration,color=color,pcb_led_id=None,role='SHORT_PULSE'))
            if i<3:events.append(dict(event_id=f'EV{i}',entity='TRACK1',status='CONFIRMED',led_id=None,color=color,start_pts=start,end_pts=start+.967,duration_s=.967))
        for event_id,entity,start,end,status in [('FA','TRACK1',6.,6.033,'CANDIDATE'),('FB','TRACK1',6.1,6.267,'CANDIDATE'),('SECOND','TRACK2',6.,6.267,'CONFIRMED')]:
            events.append(dict(event_id=event_id,entity=entity,status=status,led_id=None,color='RED',start_pts=start,end_pts=end,duration_s=end-start))
        before=deepcopy(events);result=align_operations(events,ops)
        self.assertEqual(events,before);self.assertEqual(result['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
        self.assertEqual({p['event_id'] for p in result['associations'] if p['operation_key']=='OP3'},{'FA','FB','SECOND'})

    def test_no_confirmation_from_a_journal_without_optical_evidence(self):
        result=align_operations([],[]);self.assertEqual(result['status'],'NO_MATCH');self.assertEqual(result['associations'],[])

    def test_secondary_fragment_between_nearby_operations_is_not_assigned_to_nearest(self):
        ops=[];events=[]
        for i,color in enumerate(('RED','GREEN','BLUE')):
            ops.append(dict(operation_key=f'ANCHOR{i}',operation_id=i,electrical_status='COMPLETED',host_ack_s=5.+i*2,
                host_tx_s=4.99+i*2,host_done_s=6.+i*2,requested_duration_ms=1000,color=color,pcb_led_id=None,role='SHORT_PULSE'))
            events.append(dict(event_id=f'A{i}',entity='LED7',status='CONFIRMED',color=color,led_id=None,start_pts=i*2,end_pts=i*2+.967,duration_s=.967))
        for key,ack in [('LEFT',11.),('RIGHT',11.11)]:
            ops.append(dict(ops[0],operation_key=key,operation_id=key,host_ack_s=ack,host_tx_s=ack-.01,host_done_s=ack+.1,requested_duration_ms=100))
        events.append(dict(event_id='BETWEEN',entity='LED7',status='CANDIDATE',color='RED',led_id=None,start_pts=6.09,end_pts=6.123,duration_s=.033))
        result=align_operations(events,ops)
        self.assertEqual(result['status'],'ESTIMATED_NOT_HARDWARE_SYNC')
        self.assertFalse(any(p['event_id']=='BETWEEN' for p in result['associations']))
        self.assertEqual(result['ambiguous_associations'][0]['operation_keys'],['LEFT','RIGHT'])
