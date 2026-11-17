"""Post-hoc optical/PHOTO association. This module never influences detection."""
import json
from pathlib import Path
from statistics import median
import re


def align_session(events,session_path):
    path=Path(session_path);session=json.loads(path.read_text(encoding='utf-8'))
    origin=session['monotonic_origin_ns'];commands=[]
    log=path.parent/'events.jsonl'
    tx=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.is_file() else []
    for row in session.get('measurements',[]):
        match=re.fullmatch(r'PHOTO (LED\d+) (RED|GREEN|BLUE) (\d+)',row.get('command',''))
        if not match or row.get('status')!='COMPLETED' or row.get('fault')!='NONE' or row.get('reason')!='TIMEOUT':continue
        ack=row.get('ack_ns');done=row.get('done_ns')
        if not isinstance(ack,int) or not isinstance(done,int) or done<ack:continue
        sent=[e['monotonic_ns'] for e in tx if e.get('direction')=='TX' and e.get('text')==row['command'] and e['monotonic_ns']<=ack]
        commands.append(dict(led_id=match[1],color=match[2],duration_s=int(match[3])/1000,id=row.get('id'),
            host_on_interval_s=[(max(sent)-origin)/1e9 if sent else None,(ack-origin)/1e9],
            host_done_s=(done-origin)/1e9))
    groups={}
    for event in events:
        if event['status']=='CONFIRMED':groups.setdefault(event['entity'],[]).append(event)
    candidates=[]
    for entity,observations in groups.items():
        observations=sorted(observations,key=lambda e:e['start_pts'])
        if len(observations)!=len(commands) or not commands:continue
        if any(e['color']!=c['color'] or abs(e['duration_s']-c['duration_s'])>.3 or
               (e['led_id'] is not None and e['led_id']!=c['led_id']) for e,c in zip(observations,commands)):continue
        pairs=[]
        for e,c in zip(observations,commands):
            start=e['signal_start_interval_s'];host=c['host_on_interval_s']
            bounds=[host[0]-start[1] if host[0] is not None else None,host[1]-start[0] if start[0] is not None else None]
            pairs.append(dict(event_id=e['event_id'],command_id=c['id'],color=e['color'],offset_interval_s=bounds,
                offset_from_ack_s=host[1]-e['start_pts'],optical_boundary_flags=e['uncertainty_flags']))
        candidates.append(dict(entity=entity,pairs=pairs))
    result=dict(schema_version=1,source_session=str(path.resolve()),session_id=session.get('session_id'),
        status='NO_MATCH',offset_s=None,uncertainty_s=None,candidates=candidates,
        relation='host_monotonic_relative_s = video_PTS_s + offset_s',
        warning='Empirical optical/USB association, not hardware synchronization. UTC was not used. Physical onset may be censored; exposure/rolling shutter are additional unknowns.')
    if len(candidates)==1:
        pairs=candidates[0]['pairs'];offset=median(p['offset_from_ack_s'] for p in pairs)
        limits=[b for p in pairs for b in p['offset_interval_s'] if b is not None]
        result.update(status='ESTIMATED_NOT_HARDWARE_SYNC',offset_s=offset,
            uncertainty_s=max(abs(offset-b) for b in limits) if limits else None,
            uncertainty_kind='observed_USB/video_bracket_envelope; does_not_bound_all_physical_latency',
            residual_offsets_s=[p['offset_from_ack_s']-offset for p in pairs])
    elif len(candidates)>1:result['status']='AMBIGUOUS'
    return result
