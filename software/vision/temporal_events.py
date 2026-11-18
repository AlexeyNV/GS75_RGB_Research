"""PTS-based RGB hypotheses. Unknown observations never become OFF or ON."""
from dataclasses import dataclass,asdict
import math
from statistics import median,mean

VERSION='0.4.5'
UNKNOWN={'UNCERTAIN','INVALID_GEOMETRY','NO_COVERAGE'}
COLORS={'RED','GREEN','BLUE'}


@dataclass(frozen=True)
class TemporalSettings:
    profile: str='Reliable / Long Pulse'
    min_on_s: float=.10
    min_off_s: float=.067
    max_gap_s: float=.12
    min_samples: int=3
    min_chroma: float=40.
    min_brightness: float=45.
    min_color_confidence: float=.55
    spatial_radius_px: float=40.
    min_consecutive_good_samples: int=1
    def __post_init__(self):
        values=[self.min_on_s,self.min_off_s,self.max_gap_s,self.min_chroma,self.min_brightness,self.spatial_radius_px]
        if not all(math.isfinite(x) and x>=0 for x in values) or self.max_gap_s<=0 or self.min_samples<1 or self.min_consecutive_good_samples<1 or not 0<=self.min_color_confidence<=1:
            raise ValueError('Invalid temporal settings')


def profile_settings(short=False,**overrides):
    base=dict(profile='Short Pulse / Experimental',min_on_s=.02,min_off_s=.012,max_gap_s=.09,
              min_samples=2,min_chroma=30.,min_brightness=35.,min_consecutive_good_samples=2) if short else {}
    return TemporalSettings(**{**base,**overrides})


def observation(record,info,geometry,entity,led=None,off_coverage=1.):
    record=record or {};reasons=list(record.get('rejection_reasons',[]))+list(record.get('ambiguity_flags',[]))
    state=record.get('status','UNCERTAIN')
    if off_coverage<.9:state='NO_COVERAGE';reasons.append('OFF_MODEL_ROI_NOT_COVERED')
    elif geometry.get('status')!='REGISTERED':state='INVALID_GEOMETRY';reasons.append(geometry.get('reason','Geometry unavailable'))
    elif record and record.get('roi_coverage',0)<.9:
        state='INVALID_GEOMETRY';reasons.append('CURRENT_ROI_NOT_COVERED')
    elif state=='CANDIDATE':state='ON'
    if state not in {'ON','OFF',*UNKNOWN}:state='UNCERTAIN'
    if state=='ON' and record.get('color') not in COLORS:state='UNCERTAIN';reasons.append('AMBIGUOUS_COLOR')
    timestamp=info.get('timestamp_ms')
    if timestamp is None or not math.isfinite(timestamp):raise ValueError('Video temporal analysis needs real, finite PTS')
    return dict(entity=entity,led_id=(led or record).get('led_id'),key_name=(led or record).get('key_name'),
        frame_index=info['frame_index'],pts=info.get('pts'),time_base=info.get('time_base'),pts_s=timestamp/1000,
        state=state,raw_state=record.get('status'),color=record.get('color','UNDEFINED'),
        x_ref_px=record.get('signal_x_ref_px',record.get('x_ref_px',(led or {}).get('x_ref_px'))),
        y_ref_px=record.get('signal_y_ref_px',record.get('y_ref_px',(led or {}).get('y_ref_px'))),
        brightness=record.get('brightness',0.),chroma=record.get('chroma',0.),area_px=record.get('area_px',0),
        confidence=record.get('color_confidence',0.),registration=geometry.get('status','FAILED'),
        rmse_px=geometry.get('reprojection_rmse_px'),coverage=record.get('roi_coverage',0.),
        off_coverage=off_coverage,reasons=list(dict.fromkeys(reasons)),color_evidence_rgb=record.get('color_evidence_rgb',[]))


def missing_observation(info,geometry,entity,led=None,off_coverage=1.):
    row=observation(dict(status='UNCERTAIN',roi_coverage=1.,rejection_reasons=['NO_CANDIDATE_DOES_NOT_PROVE_OFF','ROI_NOT_REMEASURED']),
                    info,geometry,entity,led,off_coverage)
    row['coverage']=None
    return row


class TemporalDetector:
    """One stream per mapped LED or optical track. Confirmation uses elapsed PTS."""
    def __init__(self,settings=None):
        self.settings=settings or TemporalSettings();self.streams={};self.completed=[];self.uncertainty=[]

    def _good(self,o):
        s=self.settings
        return o['state']=='ON' and o['color'] in COLORS and o['confidence']>=s.min_color_confidence and o['chroma']>=s.min_chroma and o['brightness']>=s.min_brightness

    def _segment(self,o,previous):
        return dict(points=[o],color=o['color'],previous=previous,gaps=[],flags=[],confirmed=False)

    def _confirm(self,segment):
        points=segment['points'];good=[p for p in points if self._good(p)]
        consecutive=maximum=0;previous=None
        for point in points:
            if self._good(point):
                consecutive=consecutive+1 if previous and self._good(previous) and point['frame_index']==previous['frame_index']+1 else 1
                maximum=max(maximum,consecutive)
            else:consecutive=0
            previous=point
        segment['max_consecutive_good']=maximum
        segment['confirmed']=(len(good)>=self.settings.min_samples and maximum>=self.settings.min_consecutive_good_samples
            and points[-1]['pts_s']-points[0]['pts_s']+1e-9>=self.settings.min_on_s)

    def _close(self,segment,next_observation,reason):
        if segment is None:return
        p=segment['points'];first,last=p[0],p[-1];self._confirm(segment)
        flags=set(segment['flags']);previous=segment['previous']
        if previous is None or previous['state']!='OFF':flags.add('START_NOT_BOUNDED_BY_CONFIRMED_OFF')
        if next_observation is None or next_observation['state']!='OFF':flags.add('END_NOT_BOUNDED_BY_CONFIRMED_OFF')
        if segment['gaps']:flags.add('HYPOTHESIS_BRIDGES_UNKNOWN_OBSERVATIONS')
        if len(p)<3:flags.add('DURATION_UNRESOLVED_AT_FRAME_CADENCE')
        status='CONFIRMED' if segment['confirmed'] else ('CANDIDATE' if len(p)>=self.settings.min_samples or self.settings.profile.startswith('Short') else 'REJECTED')
        if not segment['confirmed']:flags.add('INSUFFICIENT_PERSISTENCE_OR_SIGNAL_QUALITY')
        if segment['max_consecutive_good']<self.settings.min_consecutive_good_samples:flags.add('NO_CONSECUTIVE_GOOD_PAIR')
        duration=last['pts_s']-first['pts_s']
        # Observation endpoints, never fictitious subframe timestamps.
        signal_start=[previous['pts_s'] if previous else None,first['pts_s']]
        signal_end=[last['pts_s'],next_observation['pts_s'] if next_observation else None]
        physical_start=signal_start if previous and previous['state']=='OFF' else [None,first['pts_s']]
        physical_end=signal_end if next_observation and next_observation['state']=='OFF' else [last['pts_s'],None]
        duration_bounds=[duration if not segment['gaps'] else None,
                         physical_end[1]-physical_start[0] if physical_end[1] is not None and physical_start[0] is not None else None]
        duration_confirmed=not flags and duration>0 and duration_bounds[1] is not None and (duration_bounds[1]-duration)/duration<=.2
        gap_s=sum(max(0,g['end_s']-g['start_s']) for g in segment['gaps'])
        observability=max(0.,1-gap_s/max(duration,.001))
        confidence=mean(x['confidence']*x['coverage'] for x in p)*observability
        fragments=[]
        for point in p:
            if fragments and point['frame_index']==fragments[-1]['end_frame']+1:
                tail=fragments[-1];tail.update(end_frame=point['frame_index'],end_pts=point['pts_s'])
                tail['observations']+=1;tail['good_observations']+=int(self._good(point))
            else:fragments.append(dict(fragment_id=f"EV{len(self.completed)+1:05d}:F{len(fragments)+1:02d}",
                start_frame=point['frame_index'],end_frame=point['frame_index'],start_pts=point['pts_s'],end_pts=point['pts_s'],
                observations=1,good_observations=int(self._good(point))))
        event=dict(event_id=f'EV{len(self.completed)+1:05d}',entity=first['entity'],led_id=first['led_id'],key_name=first['key_name'],
            color=segment['color'],start_pts=first['pts_s'],end_pts=last['pts_s'],duration_s=duration,
            start_frame=first['frame_index'],end_frame=last['frame_index'],status=status,confidence=confidence,
            confidence_kind='heuristic_not_probability',coverage=mean(x['coverage'] for x in p),
            x_ref_px=median([x['x_ref_px'] for x in p if x['x_ref_px'] is not None]),
            y_ref_px=median([x['y_ref_px'] for x in p if x['y_ref_px'] is not None]),
            observations=len(p),good_observations=sum(self._good(x) for x in p),
            max_consecutive_good_observations=segment['max_consecutive_good'],observation_fragments=fragments,
            positive_frame_indices=[x['frame_index'] for x in p],
            signal_start_interval_s=signal_start,signal_end_interval_s=signal_end,
            physical_start_interval_s=physical_start,physical_end_interval_s=physical_end,
            duration_confirmed=duration_confirmed,duration_interval_s=duration_bounds,
            duration_semantics='span_of_positive_observations; continuity through unknown is a hypothesis',
            uncertainty_flags=sorted(flags),unknown_gaps=segment['gaps'],end_reason=reason,decision_source='ALGORITHM')
        self.completed.append(event)

    def _unknown(self,stream,o,reason=None):
        previous=stream['last'];start=previous['pts_s'] if previous else o['pts_s']
        state=o['state'];reasons=o['reasons']+([reason] if reason else [])
        # Keep individual source states while collecting readable contiguous intervals.
        last=stream.get('uncertainty_tail')
        if last and last['entity']==o['entity'] and last['state']==state and last['end_frame']+1==o['frame_index'] and not reason:
            last.update(end_s=o['pts_s'],end_frame=o['frame_index']);last['reasons']=sorted(set(last['reasons']+reasons))
        else:
            interval=dict(entity=o['entity'],state=state,start_s=start,end_s=o['pts_s'],
                start_frame=o['frame_index'],end_frame=o['frame_index'],reasons=reasons)
            self.uncertainty.append(interval);stream['uncertainty_tail']=interval

    def feed(self,o):
        t=o['pts_s'];s=self.settings
        if not math.isfinite(t):raise ValueError('Invalid PTS')
        stream=self.streams.setdefault(o['entity'],dict(last=None,active=None,other=None,unknown_start=None,state='UNKNOWN'))
        previous=stream['last'];active=stream['active']
        if previous and t<=previous['pts_s']:raise ValueError('PTS must increase within each stream')
        if previous and o['frame_index']>previous['frame_index']+1 and t-previous['pts_s']<=s.max_gap_s+1e-9:
            self._unknown(stream,dict(o,state='UNCERTAIN',reasons=['MISSING_FRAME']),reason='MISSING_FRAME')
            if active:active['gaps'].append(dict(start_s=previous['pts_s'],end_s=t,reason='MISSING_FRAME'))
        if previous and t-previous['pts_s']>s.max_gap_s+1e-9:
            synthetic=dict(o,state='UNCERTAIN',reasons=['PTS_OBSERVATION_GAP'])
            self._unknown(stream,synthetic,'PTS_OBSERVATION_GAP')
            if active:active['flags'].append('LONG_PTS_GAP');self._close(active,o,'LONG_PTS_GAP')
            if stream['other']:self._close(stream['other'],o,'UNCONFIRMED_COLOR_TRANSITION')
            stream.update(active=None,other=None,unknown_start=None);active=None
        pending_color_recent=stream['other'] and t-stream['other']['points'][-1]['pts_s']<=s.max_gap_s+1e-9
        if active and t-active['points'][-1]['pts_s']>s.max_gap_s+1e-9 and not pending_color_recent:
            active['flags'].append('LONG_OBSERVABILITY_LOSS');self._close(active,stream.get('unknown_start'),'LONG_OBSERVABILITY_LOSS')
            if stream['other']:self._close(stream['other'],o,'UNCONFIRMED_COLOR_TRANSITION')
            stream.update(active=None,other=None,unknown_start=None);active=None
        if o['state'] in UNKNOWN:
            self._unknown(stream,o)
            if active:
                if stream['unknown_start'] is None:stream['unknown_start']=o
                # Low chroma can end a COLOR hypothesis; it does NOT assert OFF.
                low=o['state']=='UNCERTAIN' and (o['coverage'] or 0.)>=.9 and o['chroma']<s.min_chroma*.5
                stream['state']='POSSIBLE_OFF' if low else 'UNKNOWN'
                if low and t-stream['unknown_start']['pts_s']>=s.min_off_s-1e-9:
                    active['flags'].append('UNCERTAIN_COLOR_SIGNAL_LOSS')
                    self._close(active,stream['unknown_start'],'UNCERTAIN_COLOR_SIGNAL_LOSS')
                    if stream['other']:self._close(stream['other'],o,'UNCONFIRMED_COLOR_TRANSITION')
                    stream.update(active=None,other=None,unknown_start=None)
            else:stream['state']='UNKNOWN'
        elif o['state']=='OFF':
            # A single reliable OFF is a hard barrier even for a short pulse profile.
            if active:self._close(active,o,'CONFIRMED_OFF')
            if stream['other']:self._close(stream['other'],o,'CONFIRMED_OFF')
            stream.update(active=None,other=None,unknown_start=None,state='OFF')
        elif o['state']=='ON':
            if active is None:
                active=self._segment(o,previous);stream['active']=active;stream['unknown_start']=None
            elif o['color']==active['color']:
                if stream['other']:
                    other=stream['other'];active['gaps'].append(dict(start_s=other['points'][0]['pts_s'],end_s=t,reason='TRANSIENT_COLOR_CONFLICT'))
                    interval=dict(entity=o['entity'],state='UNCERTAIN',start_s=other['points'][0]['pts_s'],end_s=t,
                        start_frame=other['points'][0]['frame_index'],end_frame=max(other['points'][0]['frame_index'],o['frame_index']-1),
                        reasons=['TRANSIENT_COLOR_CONFLICT'],origin='TEMPORAL_COLOR_CONFLICT')
                    self.uncertainty.append(interval);stream['uncertainty_tail']=interval
                    self._close(other,o,'TRANSIENT_COLOR_CONFLICT');stream['other']=None
                if stream['unknown_start']:
                    active['gaps'].append(dict(start_s=stream['unknown_start']['pts_s'],end_s=t,reason='SHORT_OBSERVABILITY_LOSS'))
                    stream['unknown_start']=None
                active['points'].append(o)
            else:
                if stream['other'] is None or stream['other']['color']!=o['color']:
                    if stream['other']:self._close(stream['other'],o,'TRANSIENT_COLOR_CONFLICT')
                    stream['other']=self._segment(o,active['points'][-1])
                else:stream['other']['points'].append(o)
                self._confirm(stream['other'])
                if stream['other']['confirmed']:
                    self._close(active,stream['other']['points'][0],'COLOR_TRANSITION_WITHOUT_OFF')
                    active=stream['other'];active['flags'].append('COLOR_TRANSITION_WITHOUT_OFF')
                    stream.update(active=active,other=None,unknown_start=None)
            self._confirm(active)
            stream['state']='ON' if active['confirmed'] else 'POSSIBLE_ON'
        else:raise ValueError('Unknown observation state')
        stream['last']=o

    def finish(self):
        for stream in self.streams.values():
            if stream['active']:self._close(stream['active'],None,'END_OF_VIDEO');stream['active']=None
            if stream['other']:self._close(stream['other'],None,'END_OF_VIDEO');stream['other']=None
        return sorted(self.completed,key=lambda e:(e['start_pts'],e['entity']))
