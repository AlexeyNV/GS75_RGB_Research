"""Shared compact-observation adapter for video analysis and benchmark."""
from collections import Counter
import time
from .temporal_events import TemporalDetector,TemporalSettings,observation,missing_observation
from .optical_tracks import OpticalTracker
from .off_background import without_markers
from .off_diagnostics import roi_coverage
from .frame_profile import timed
from .observation_diagnostics import categories,uncertainty_statistics


class FrameTemporalAnalysis:
    def __init__(self,calibration,off,mode,settings=None):
        self.calibration,self.mode=calibration,mode
        self.detector=TemporalDetector(settings or TemporalSettings())
        self.tracker=OpticalTracker(self.detector.settings)
        self.coverage=roi_coverage(without_markers(off.mask,calibration),calibration)
        self.frame_count=0;self.state_counts=Counter();self.elapsed_ns=0;self.samples_ms=[]
        self.frame_state_counts=Counter()
        self.off_intervals=[];self.off_tail={}
        self.observations=[]

    @timed('EVENT_AGGREGATION')
    def feed(self,result,info):
        started=time.perf_counter_ns();geometry=result['registrations']['on']
        if self.mode=='KNOWN_LEDS':
            records={r['led_id']:r for r in result['records']}
            observations=[observation(records.get(led['led_id']),info,geometry,led['led_id'],led,
                self.coverage.get(led['led_id'],0.)) for led in self.calibration['leds']]
        else:observations=self.tracker.feed(result,info)
        if not observations:observations=[missing_observation(info,geometry,'FRAME')]
        states={row['state'] for row in observations}
        self.frame_state_counts[next(state for state in ('ON','UNCERTAIN','INVALID_GEOMETRY','NO_COVERAGE','OFF') if state in states)]+=1
        for row in observations:
            row['uncertainty_categories']=categories(row,geometry);self.observations.append(row)
            self.state_counts[row['state']]+=1
            if row['state']=='OFF':
                tail=self.off_tail.get(row['entity'])
                if tail and tail['end_frame']+1==row['frame_index']:
                    tail.update(end_s=row['pts_s'],end_frame=row['frame_index'])
                else:
                    tail=dict(entity=row['entity'],start_s=row['pts_s'],end_s=row['pts_s'],
                              start_frame=row['frame_index'],end_frame=row['frame_index'],state='OFF')
                    self.off_intervals.append(tail);self.off_tail[row['entity']]=tail
            if row['entity']!='FRAME':self.detector.feed(row)
        self.frame_count+=1
        elapsed=time.perf_counter_ns()-started;self.elapsed_ns+=elapsed;self.samples_ms.append(elapsed/1e6)
        return observations

    def finish(self):
        started=time.perf_counter_ns();events=self.detector.finish()
        tracks=self.tracker.summary(events) if self.mode=='DISCOVER' else []
        self.elapsed_ns+=time.perf_counter_ns()-started
        return dict(events=events,unknown_tracks=tracks,uncertainty_intervals=self.detector.uncertainty,
            state_counts=dict(self.state_counts),frame_count=self.frame_count,
            frame_state_counts=dict(self.frame_state_counts),
            temporal_ms=self.elapsed_ns/1e6,temporal_mean_ms=self.elapsed_ns/1e6/max(1,self.frame_count),
            temporal_frame_ms=self.samples_ms,
            off_intervals=self.off_intervals,
            uncertainty_statistics=uncertainty_statistics(self.observations,events,self.detector.uncertainty),
            policy='Unknown is preserved; short gaps keep a continuity hypothesis, never a confirmed OFF')
