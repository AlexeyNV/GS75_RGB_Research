"""Independent PTS scenarios; expected video times never enter production code."""
from copy import deepcopy
import math
import unittest
from software.vision.temporal_events import TemporalDetector,TemporalSettings,profile_settings,observation
from software.vision.optical_tracks import OpticalTracker


def obs(t,state='ON',color='RED',frame=None,entity='LED7',**changes):
    value=dict(entity=entity,led_id=entity,key_name=None,frame_index=round(t*30) if frame is None else frame,
        pts_s=t,state=state,raw_state=state,color=color,x_ref_px=200.,y_ref_px=300.,
        brightness=120.,chroma=90.,area_px=100,confidence=.9,registration='REGISTERED',
        rmse_px=.5,coverage=1.,off_coverage=1.,reasons=[])
    value.update(changes);return value


def detect(rows,settings=None):
    detector=TemporalDetector(settings)
    for row in rows:detector.feed(row)
    return detector,detector.finish()


class TemporalTests(unittest.TestCase):
    def test_off_and_reflection_have_no_confirmed_event(self):
        for reflection in (False,True):
            rows=[obs(i/30,'ON' if reflection and i==15 else 'OFF',frame=i) for i in range(60)]
            _,events=detect(rows)
            self.assertFalse(any(e['status']=='CONFIRMED' for e in events))
            if reflection:self.assertEqual(events[0]['status'],'REJECTED')

    def test_single_pulse_and_RGB(self):
        rows=[]
        for i in range(150):
            t=i/30;color='RED' if .5<=t<1.5 else ('GREEN' if 2<=t<3 else 'BLUE')
            state='ON' if .5<=t<1.5 or 2<=t<3 or 3.5<=t<4.5 else 'OFF'
            rows.append(obs(t,state,color,frame=i))
        detector,events=detect(rows)
        self.assertEqual([e['color'] for e in events],['RED','GREEN','BLUE'])
        self.assertTrue(all(e['status']=='CONFIRMED' for e in events))
        self.assertTrue(all(e['duration_confirmed'] for e in events));self.assertFalse(detector.uncertainty)
        for e,expected in zip(events,[.5,2.,3.5]):self.assertAlmostEqual(e['start_pts'],expected)

    def test_reliable_off_is_never_bridged_even_for_one_frame(self):
        rows=[obs(i/30,'OFF' if i in (0,16,33) else 'ON',frame=i) for i in range(34)]
        _,events=detect(rows)
        self.assertEqual(len(events),2);self.assertTrue(all(e['status']=='CONFIRMED' for e in events))
        self.assertLess(events[0]['end_frame'],16);self.assertGreater(events[1]['start_frame'],16)

    def test_unknown_is_not_off_and_short_losses_remain_visible(self):
        rows=[obs(i/30,'OFF' if i in (0,50) else 'ON',frame=i) for i in range(51)]
        rows[15]['state']='INVALID_GEOMETRY';rows[16]['state']='NO_COVERAGE'
        original=deepcopy(rows);detector,events=detect(rows)
        self.assertEqual(rows,original);self.assertEqual(len(events),1);self.assertEqual(events[0]['status'],'CONFIRMED')
        self.assertTrue(events[0]['unknown_gaps']);self.assertFalse(events[0]['duration_confirmed'])
        self.assertEqual({u['state'] for u in detector.uncertainty},{'INVALID_GEOMETRY','NO_COVERAGE'})

    def test_long_geometry_loss_splits_and_censors(self):
        rows=[obs(i/30,'OFF' if i in (0,80) else ('INVALID_GEOMETRY' if 25<=i<=40 else 'ON'),frame=i) for i in range(81)]
        detector,events=detect(rows)
        self.assertEqual(len(events),2);self.assertTrue(all(e['status']=='CONFIRMED' for e in events))
        self.assertIn('LONG_OBSERVABILITY_LOSS',events[0]['uncertainty_flags'])
        self.assertIsNone(events[0]['physical_end_interval_s'][1]);self.assertIsNone(events[1]['physical_start_interval_s'][0])

    def test_ambiguous_photometry_is_preserved_and_can_end_only_color_hypothesis(self):
        rows=[obs(i/30,'ON' if 5<=i<20 else ('OFF' if i<5 else 'UNCERTAIN'),frame=i,
                  chroma=0 if i>=20 else 90.,brightness=0 if i>=20 else 120.) for i in range(45)]
        detector,events=detect(rows)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['status'],'CONFIRMED')
        self.assertEqual(events[0]['end_frame'],19);self.assertIn('END_NOT_BOUNDED_BY_CONFIRMED_OFF',events[0]['uncertainty_flags'])
        self.assertTrue(all(u['state']=='UNCERTAIN' for u in detector.uncertainty))
        self.assertFalse(events[0]['duration_confirmed'])

    def test_new_event_does_not_inherit_uncertainty_from_previous_color(self):
        rows=[]
        for i in range(140):
            active=5<=i<35 or 80<=i<110
            rows.append(obs(i/30,'ON' if active else 'UNCERTAIN',color='RED' if i<60 else 'GREEN',frame=i,
                chroma=90. if active else 0.,brightness=120. if active else 0.))
        _,events=detect(rows)
        self.assertEqual(len(events),2)
        for e in events:
            self.assertFalse(e['unknown_gaps'])
            self.assertGreater(e['confidence'],.8)

    def test_sustained_color_change_without_off_and_brightness_change(self):
        rows=[obs(i/30,'OFF' if i in (0,90) else 'ON',color='RED' if i<30 else ('GREEN' if i<60 else 'BLUE'),
                  frame=i,brightness=90+i%20) for i in range(91)]
        _,events=detect(rows)
        self.assertEqual([e['color'] for e in events],['RED','GREEN','BLUE'])
        self.assertTrue(all(e['status']=='CONFIRMED' for e in events))
        self.assertEqual(events[1]['start_frame'],30);self.assertEqual(events[2]['start_frame'],60)
        self.assertEqual(events[0]['end_frame'],29)

    def test_short_color_artifact_does_not_create_confirmed_transition(self):
        rows=[obs(i/30,'OFF' if i in (0,60) else 'ON','GREEN' if i==30 else 'RED',frame=i) for i in range(61)]
        detector,events=detect(rows)
        self.assertEqual([(e['color'],e['status']) for e in events if e['status']=='CONFIRMED'],[('RED','CONFIRMED')])
        self.assertTrue(any(e['color']=='GREEN' and e['status']=='REJECTED' for e in events))
        self.assertTrue(any('TRANSIENT_COLOR_CONFLICT' in u['reasons'] for u in detector.uncertainty))

    def test_missing_frame_and_vfr_use_pts_not_count(self):
        times=[0,.02,.08,.11,.16,.18,.24,.3,.35,.41,.5]
        rows=[obs(t,'OFF' if i in (0,10) else 'ON',frame=i) for i,t in enumerate(times)]
        del rows[5]
        detector,events=detect(rows)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['status'],'CONFIRMED')
        self.assertAlmostEqual(events[0]['duration_s'],.39)
        self.assertTrue(any('MISSING_FRAME' in u['reasons'] for u in detector.uncertainty))
        # Many tightly spaced frames do not satisfy a minimum elapsed duration.
        _,events=detect([obs(i*.001,'OFF' if i in (0,30) else 'ON',frame=i) for i in range(31)])
        self.assertFalse(any(e['status']=='CONFIRMED' for e in events))

    def test_short_pulse_detection_and_duration_are_distinct(self):
        for ms in (33,67,100,200,300,1000,5000):
            for phase in (0.,.0001,.011,.025):
                start=.5+phase;end=start+ms/1000
                rows=[obs(i/30,'ON' if start<=i/30<end else 'OFF',frame=i) for i in range(math.ceil((end+.2)*30))]
                _,events=detect(rows,profile_settings(short=True));on=[r for r in rows if r['state']=='ON']
                confirmed=[e for e in events if e['status']=='CONFIRMED']
                with self.subTest(ms=ms,phase=phase):
                    self.assertEqual(bool(confirmed),len(on)>=2)
                    if events:
                        e=events[0];self.assertGreaterEqual(e['start_pts'],start)
                        self.assertLess(e['end_pts'],end)
                        self.assertLessEqual(abs(e['duration_s']-ms/1000),2/30+.001)
                        if len(on)<=2:self.assertFalse(e['duration_confirmed'])
        # 10 ms may fall entirely between exposures. The detector cannot invent it.
        _,events=detect([obs(i/30,'OFF',frame=i) for i in range(10)],profile_settings(short=True));self.assertEqual(events,[])

    def test_adapter_invalid_geometry_and_no_coverage_never_become_off(self):
        record=dict(status='ON',color='RED',roi_coverage=1.,brightness=100,chroma=80,color_confidence=.9,x_ref_px=200,y_ref_px=300)
        info=dict(frame_index=0,timestamp_ms=0,pts=0,time_base='1/30')
        geometry=dict(status='FAILED',reason='No ArUco')
        self.assertEqual(observation(record,info,geometry,'LED7',off_coverage=1.)['state'],'INVALID_GEOMETRY')
        geometry['status']='REGISTERED'
        self.assertEqual(observation(record,info,geometry,'LED7',off_coverage=.5)['state'],'NO_COVERAGE')
        for invalid in (float('nan'),None):
            with self.assertRaises(ValueError):observation(record,dict(info,timestamp_ms=invalid),geometry,'LED7')

    def test_nonincreasing_pts_and_invalid_settings_are_refused(self):
        detector=TemporalDetector();detector.feed(obs(1))
        with self.assertRaises(ValueError):detector.feed(obs(1))
        with self.assertRaises(ValueError):TemporalSettings(max_gap_s=0)

    def test_two_short_pulses_with_observed_small_off_pause_remain_separate(self):
        rows=[obs(i/30,'ON' if .2<=i/30<.26 or .3<=i/30<.36 else 'OFF',frame=i) for i in range(20)]
        _,events=detect(rows,profile_settings(short=True))
        confirmed=[e for e in events if e['status']=='CONFIRMED']
        self.assertEqual(len(confirmed),2)
        self.assertLess(confirmed[0]['end_pts'],confirmed[1]['start_pts'])
        self.assertTrue(all(not e['duration_confirmed'] for e in confirmed))

    def test_exposure_ambiguity_and_other_LED_do_not_create_false_events(self):
        detector=TemporalDetector()
        for i in range(60):
            detector.feed(obs(i/30,'OFF' if i in (0,59) else 'ON',frame=i))
            detector.feed(obs(i/30,'ON' if i==30 else 'UNCERTAIN',frame=i,entity='LED99',
                color='RED' if i==30 else 'UNDEFINED',chroma=90. if i==30 else 0.,brightness=120. if i==30 else 0.))
        events=detector.finish()
        self.assertEqual([(e['entity'],e['color']) for e in events if e['status']=='CONFIRMED'],[('LED7','RED')])


class OpticalTrackTests(unittest.TestCase):
    def test_spatial_tracking_has_no_pcb_id_and_rejects_single_glints(self):
        settings=TemporalSettings();tracker=OpticalTracker(settings);detector=TemporalDetector(settings)
        for i in range(50):
            records=[]
            if 3<=i<30:records.append(dict(status='CANDIDATE',led_id=None,color='GREEN',x_ref_px=250+i%3,y_ref_px=170,
                brightness=100,chroma=80,area_px=100,color_confidence=.8,roi_coverage=1.))
            if i==15:records.append(dict(records[0],x_ref_px=900,y_ref_px=600))
            result=dict(records=records,registrations={'on':dict(status='REGISTERED',reprojection_rmse_px=.5)})
            for o in tracker.feed(result,dict(frame_index=i,timestamp_ms=i*1000/30,pts=i,time_base='1/30')):detector.feed(o)
        events=detector.finish();tracks=tracker.summary(events)
        self.assertEqual(len(tracks),2);self.assertEqual(sum(t['status']=='CONFIRMED' for t in tracks),1)
        self.assertTrue(all(t['led_id'] is None for t in tracks))
        self.assertEqual(sum(e['status']=='CONFIRMED' for e in events),1)
