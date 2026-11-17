"""Portable real recorded trace regression; this test does not rerun OpenCV."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest
from software.vision.temporal_events import TemporalDetector,TemporalSettings,observation
from software.vision.optical_tracks import OpticalTracker


TRACE=Path(__file__).parent/'fixtures/v043_real_observations.json.gz'


def process(data,mode):
    detector=TemporalDetector();tracker=OpticalTracker(detector.settings);seen=[]
    for row in data['frames']:
        result=row['result'];geometry=result['registrations']['on']
        if mode=='known':
            led=data['calibration']['leds'][0]
            records=[observation(result['records'][0] if result['records'] else None,row,geometry,
                led['led_id'],led,next(iter(data['coverage'].values())))]
        else:records=tracker.feed(result,row)
        for record in records:detector.feed(record)
        seen.append(row['frame_index'])
    events=detector.finish();return events,detector.uncertainty,tracker.summary(events),seen


class RecordedRealTemporalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=json.loads(gzip.decompress(TRACE.read_bytes()))

    def test_922_frames_exactly_three_known_events_no_false_confirmed_LED(self):
        events,unknown,tracks,seen=process(self.data['known'],'known')
        confirmed=[e for e in events if e['status']=='CONFIRMED']
        self.assertEqual(seen,list(range(922)));self.assertEqual(len(confirmed),3)
        self.assertEqual([e['color'] for e in confirmed],['RED','GREEN','BLUE'])
        self.assertEqual({e['led_id'] for e in confirmed},{'LED49'})
        # Independently established optical intervals, used ONLY for validation.
        for event,(start,end) in zip(confirmed,[(3.35,8.40),(11.74,16.79),(20.10,25.14)]):
            self.assertLess(abs(event['start_pts']-start),.05)
            self.assertLess(abs(event['end_pts']-end),.05)
            self.assertLess(abs(event['duration_s']-(end-start)),.12)
            self.assertFalse(event['duration_confirmed']);self.assertTrue(event['unknown_gaps'])
            self.assertTrue(all(g['start_s']>=event['start_pts'] and g['end_s']<=event['end_pts'] for g in event['unknown_gaps']))
        self.assertEqual({u['state'] for u in unknown},{'UNCERTAIN','INVALID_GEOMETRY'})

    def test_blind_tracks_retain_weak_candidates_and_never_assign_PCB_ID(self):
        events,unknown,tracks,seen=process(self.data['discover'],'discover')
        self.assertEqual(len(seen),922)
        self.assertEqual(len([e for e in events if e['status']=='CONFIRMED']),3)
        self.assertEqual(len([t for t in tracks if t['status']=='CONFIRMED']),1)
        self.assertTrue(all(t['led_id'] is None for t in tracks))
        self.assertTrue(any(t['status']=='CANDIDATE' and t['observations']>10 for t in tracks))
        self.assertTrue(any(t['status']=='REJECTED' for t in tracks));self.assertTrue(unknown)

    def test_LED_name_and_coordinate_translation_do_not_change_detection(self):
        known=deepcopy(self.data['known']);known['calibration']['leds'][0]['led_id']='LED777'
        events,_,_,_=process(known,'known')
        self.assertEqual({e['led_id'] for e in events if e['status']=='CONFIRMED'},{'LED777'})
        shifted=deepcopy(self.data['discover'])
        for row in shifted['frames']:
            for r in row['result']['records']:
                for key in ('x_ref_px','signal_x_ref_px'):
                    if key in r:r[key]+=123
                for key in ('y_ref_px','signal_y_ref_px'):
                    if key in r:r[key]+=57
        baseline,_,_,_=process(self.data['discover'],'discover');actual,_,_,_=process(shifted,'discover')
        fields=lambda rows:[(e['color'],e['start_pts'],e['end_pts']) for e in rows if e['status']=='CONFIRMED']
        self.assertEqual(fields(baseline),fields(actual))
