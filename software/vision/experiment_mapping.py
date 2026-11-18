"""Post-hoc electrical/optical association, immutable table snapshots.

The detector's events are input only. No nominal experiment times are passed
to OpenCV or TemporalDetector. Unknown evidence stays unknown.
"""
import csv
import json
from pathlib import Path
from statistics import median, mean
import math
from .project_storage import atomic_json, image_hash
from .video_event_export import load_decisions
from software.hardware.electrical_operations import load_operations


MAPPING_FIELDS = ['experiment_id','operation_key','operation_id','role','source_kp','sink_kp',
    'requested_duration_ms','measured_duration_ms','current_avg_ua','current_max_ua','adc_samples','fault',
    'electrical_status','optical_event_id','optical_track_id','pcb_led_id','key_name','color',
    'optical_start_pts','optical_end_pts','optical_confidence','roi_coverage','signal_mean','chroma_mean',
    'alignment_confidence','alignment_uncertainty_s','operator_confirmation','mapping_status',
    'optical_status','rejection_or_uncertainty_reason','simulation']
WARNING = ('Empirical post-hoc association, not hardware synchronization. USB ACK/DONE and optical frame PTS '
           'are distinct observations; exposure/rolling shutter and physical edge latency are not bounded.')


def compatible(operation, event, cadence):
    if event.get('status') not in ('CONFIRMED','CANDIDATE'): return False
    if operation.get('color') and operation['color'] != event['color']: return False
    if event.get('led_id') and operation.get('pcb_led_id') and event['led_id'] != operation['pcb_led_id']: return False
    requested = operation.get('requested_duration_ms')
    if requested is None: return False
    # Observed first/last positive samples normally shorten the measured span.
    # Large missing portions must not become timing anchors.
    return abs(event['duration_s']-requested/1000) <= max(2.5*cadence, .2*requested/1000)


def align_operations(events, operations, fps=30.):
    cadence = 1/(fps or 30.)
    tolerance = max(.04, 2*cadence)
    valid = [o for o in operations if o['electrical_status']=='COMPLETED' and o.get('host_ack_s') is not None
             and o.get('host_done_s') is not None and o['host_done_s'] >= o['host_ack_s']]
    pairs = [(o,e,o['host_ack_s']-e['start_pts']) for o in valid for e in events if compatible(o,e,cadence)]
    hypotheses = {}
    for _,_,offset in pairs:
        matching = [(o,e,d) for o,e,d in pairs if abs(d-offset) <= tolerance]
        # One event cannot belong to two operations; two overlapping sources may
        # belong to one operation. Competing same-entity events stay ambiguous.
        by_event = {}; by_entity_operation = {}
        for o,e,_ in matching:
            by_event.setdefault(e['event_id'],set()).add(o['operation_key'])
            by_entity_operation.setdefault((o['operation_key'],e['entity']),set()).add(e['event_id'])
        if any(len(v)>1 for v in [*by_event.values(),*by_entity_operation.values()]): continue
        unique = {o['operation_key'] for o,_,_ in matching}
        if len(unique)<3: continue
        markers = {o['operation_key'] for o,_,_ in matching if o.get('role')=='SYNC_MARKER'}
        key = tuple(sorted((o['operation_key'],e['event_id']) for o,e,_ in matching))
        hypotheses[key] = dict(score=(len(markers),len(unique)),matching=matching)
    result = dict(schema_version=1,status='NO_MATCH',offset_s=None,uncertainty_s=None,
        relation='host_monotonic_relative_s = video_PTS_s + offset_s',warning=WARNING,
        confidence=None,drift_s_per_s=None,drift_status='NOT_FITTED_NO_INDEPENDENT_DRIFT_CALIBRATION',candidates=[])
    if not hypotheses: return result
    score = max(h['score'] for h in hypotheses.values())
    best = [h for h in hypotheses.values() if h['score']==score]
    result['candidates'] = [dict(matched_operations=h['score'][1],marker_anchors=h['score'][0],
        pairs=[dict(operation_key=o['operation_key'],command_id=o['operation_id'],event_id=e['event_id']) for o,e,_ in h['matching']]) for h in best]
    if len(best)!=1:
        result['status']='AMBIGUOUS';return result
    matching=best[0]['matching'];offset=median(d for _,_,d in matching)
    usb=max([o['host_ack_s']-o['host_tx_s'] for o,_,_ in matching if o.get('host_tx_s') is not None]+[0.])
    envelope=max(abs(d-offset) for _,_,d in matching)+cadence+usb
    result.update(status='ESTIMATED_NOT_HARDWARE_SYNC',offset_s=offset,uncertainty_s=envelope,
        uncertainty_kind='observed_residual_plus_frame_cadence_plus_USB_bracket_not_physical_bound',
        confidence='UNIQUE_SEQUENCE_WITH_MARKER' if score[0] else 'UNIQUE_SEQUENCE',
        residual_offsets_s=[d-offset for _,_,d in matching])
    return result


def read_observations(path):
    if not path or not Path(path).is_file(): return []
    with Path(path).open(encoding='utf-8',newline='') as stream:
        rows=list(csv.DictReader(stream))
    for row in rows:
        for key in ('pts_s','coverage','brightness','chroma'):
            row[key]=float(row[key]) if row.get(key) not in (None,'','None') else None
    return rows


def observability(operation, alignment, observations, entities, fps):
    if alignment['offset_s'] is None: return 'UNALIGNED','No unique USB/video alignment'
    if operation.get('host_ack_s') is None: return 'UNOBSERVABLE','No operation timing anchor'
    start=operation['host_ack_s']-alignment['offset_s'];end=start+operation['requested_duration_ms']/1000
    margin=alignment['uncertainty_s'] or 0.;cadence=1/(fps or 30.)
    rows=[r for r in observations if start-margin<=r['pts_s']<=end+margin and
          ((r.get('led_id') and r['led_id']==operation.get('pcb_led_id')) or r.get('entity') in entities)]
    if not rows: return 'UNOBSERVABLE','No measured target ROI; absence of DISCOVER candidate is not OFF'
    by_entity={}
    for row in rows:by_entity.setdefault(row['entity'],[]).append(row)
    for rows in by_entity.values():
        rows=sorted(rows,key=lambda r:r['pts_s']);times=[r['pts_s'] for r in rows]
        if (len(rows)>=2 and times[0]<=start+cadence and times[-1]>=end-cadence
            and all(b-a<=1.6*cadence for a,b in zip(times,times[1:]))
            and all(r['state']=='OFF' and (r['coverage'] or 0)>=.9 for r in rows)):
            return 'MISSED','Reliable sampled ROI OFF; unobserved exposure intervals remain a limitation'
    return 'UNOBSERVABLE','Geometry/coverage/uncertain signal/frame gaps prevent a reliable negative optical result'


def _write_csv(path, rows, fields=None):
    fields=fields or list(dict.fromkeys(key for row in rows for key in row)) or ['status']
    with Path(path).open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})


def rate_interval(successes, trials):
    """Wilson 95% interval; describes sampled trials, never a capture guarantee."""
    if not trials:return None
    z=1.959963984540054;p=successes/trials;den=1+z*z/trials
    center=(p+z*z/(2*trials))/den
    radius=z*math.sqrt(p*(1-p)/trials+z*z/(4*trials*trials))/den
    return [max(0.,center-radius),min(1.,center+radius)]


def build_tables(report, session_path, output, observations_path=None, decisions=None):
    """New snapshot directory required. Re-running after review keeps old exports."""
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    session,operations=load_operations(session_path);events=report['events'];decisions=decisions or {}
    fps=(report.get('video') or {}).get('fps') or (report.get('video') or {}).get('average_fps') or 30.
    alignment=align_operations(events,operations,fps)
    alignment.update(source_session=str(Path(session_path).resolve()),session_id=session.get('session_id'))
    observations=read_observations(observations_path)
    pairs=alignment['candidates'][0]['pairs'] if alignment['status']=='ESTIMATED_NOT_HARDWARE_SYNC' else []
    linked={};event_by_id={e['event_id']:e for e in events}
    for pair in pairs:linked.setdefault(pair['operation_key'],[]).append(event_by_id[pair['event_id']])
    mapped=[];outcomes={};matched=set();boundary=[]
    for op in operations:
        entities={e['entity'] for pair in pairs for e in [event_by_id[pair['event_id']]]
                  if next(o for o in operations if o['operation_key']==pair['operation_key']).get('pcb_led_id')==op.get('pcb_led_id')}
        optical=linked.get(op['operation_key'],[])
        rows=[]
        for event in optical or [None]:
            row={k:op.get(k) for k in MAPPING_FIELDS};row.update(optical_event_id=None,optical_track_id=None,
                pcb_led_id=None,key_name=None,color=op.get('color'),alignment_confidence=alignment['confidence'],
                alignment_uncertainty_s=alignment['uncertainty_s'],operator_confirmation=None)
            if op['electrical_status']!='COMPLETED':
                status='FAILED_OPERATION';opt_status='NOT_EVALUATED';reason=op['electrical_status']
            elif alignment['status']=='AMBIGUOUS':
                status='AMBIGUOUS';opt_status='UNALIGNED';reason='Several equally supported clock associations'
            elif event is None:
                opt_status,reason=observability(op,alignment,observations,entities,fps)
                status='NO_OPTICAL_OBSERVATION' if opt_status=='MISSED' else 'ELECTRICAL_ONLY'
            else:
                matched.add(event['event_id']);manual=decisions.get(event['event_id'],decisions.get(event['entity'],{}))
                decision=manual.get('decision');opt_status=event['status']
                status='VERIFIED' if decision=='ACCEPTED' else ('REJECTED' if decision=='REJECTED' else 'OPTICAL_CANDIDATE')
                reason='Operator-confirmed association' if status=='VERIFIED' else ('Operator rejected optical association' if status=='REJECTED' else 'Algorithm association; operator confirmation pending')
                signal=[r for r in observations if r['entity']==event['entity'] and event['start_pts']<=r['pts_s']<=event['end_pts'] and r['state']=='ON']
                row.update(optical_event_id=event['event_id'],optical_track_id=event['entity'] if event.get('led_id') is None else None,
                    pcb_led_id=manual.get('pcb_led_id') or event.get('led_id'),key_name=event.get('key_name'),color=event['color'],
                    optical_start_pts=event['start_pts'],optical_end_pts=event['end_pts'],optical_confidence=event.get('confidence'),
                    roi_coverage=event.get('coverage'),operator_confirmation=decision,
                    signal_mean=mean(r['brightness'] for r in signal) if signal else None,
                    chroma_mean=mean(r['chroma'] for r in signal) if signal else None)
                predicted=op['host_ack_s']-alignment['offset_s'];duration=(op.get('measured_duration_ms') or op['requested_duration_ms'])/1000
                boundary.append(dict(operation_key=op['operation_key'],event_id=event['event_id'],role=op['role'],
                    requested_duration_ms=op['requested_duration_ms'],start_residual_s=event['start_pts']-predicted,
                    end_residual_s=event['end_pts']-(predicted+duration),optical_confidence=event.get('confidence')))
            row.update(mapping_status=status,optical_status=opt_status,rejection_or_uncertainty_reason=reason)
            mapped.append(row);rows.append(opt_status)
        outcomes[op['operation_key']]=rows
    extras=[e for e in events if e['event_id'] not in matched and e['status'] in ('CONFIRMED','CANDIDATE')]
    # Extra optical evidence is unassociated, not automatically declared false.
    false_count=sum(decisions.get(e['event_id'],decisions.get(e['entity'],{})).get('decision')=='REJECTED' for e in extras)
    summary=[]
    for duration in sorted({o['requested_duration_ms'] for o in operations if o['role']!='SYNC_MARKER' and o.get('requested_duration_ms') is not None}):
        group=[o for o in operations if o['role']!='SYNC_MARKER' and o['requested_duration_ms']==duration]
        keys={o['operation_key'] for o in group};detected=[e for o in group for e in linked.get(o['operation_key'],[])]
        residuals=[b for b in boundary if b['operation_key'] in keys]
        vals=lambda key:[r[key] for r in residuals]
        confirmed_operations=sum(any(e['status']=='CONFIRMED' for e in linked.get(o['operation_key'],[])) for o in group)
        completed=sum(o['electrical_status']=='COMPLETED' for o in group)
        mapped_group=[r for r in mapped if r['operation_key'] in keys and r['optical_event_id']]
        signals=[r['signal_mean'] for r in mapped_group if r['signal_mean'] is not None]
        chroma=[r['chroma_mean'] for r in mapped_group if r['chroma_mean'] is not None]
        summary.append(dict(requested_duration_ms=duration,requested=len(group),
            completed=completed,confirmed_operations=confirmed_operations,
            confirmation_rate=confirmed_operations/completed if completed else None,
            confirmation_rate_wilson95=rate_interval(confirmed_operations,completed),
            detected_operations=sum(bool(linked.get(o['operation_key'])) for o in group),optical_events=len(detected),
            confirmed=sum(e['status']=='CONFIRMED' for e in detected),candidate=sum(e['status']=='CANDIDATE' for e in detected),
            missed=sum(outcomes[o['operation_key']]==['MISSED'] for o in group),
            unobservable=sum(outcomes[o['operation_key']]==['UNOBSERVABLE'] for o in group),
            unaligned=sum(outcomes[o['operation_key']]==['UNALIGNED'] for o in group),
            failed_or_not_executed=sum(o['electrical_status']!='COMPLETED' for o in group),
            start_residuals_s=vals('start_residual_s'),end_residuals_s=vals('end_residual_s'),
            start_residual_mean_s=mean(vals('start_residual_s')) if residuals else None,
            end_residual_mean_s=mean(vals('end_residual_s')) if residuals else None,
            confidence_mean=mean(e.get('confidence',0) for e in detected) if detected else None,
            signal_means=signals,chroma_means=chroma,signal_mean=mean(signals) if signals else None,
            chroma_mean=mean(chroma) if chroma else None,
            extra_optical_events_global=len(extras),operator_rejected_extras_global=false_count,
            false_detections=false_count if false_count==len(extras) else None,
            false_detections_unreviewed=None if false_count<len(extras) else 0,simulation=session.get('simulation',False)))
    optical_rows=[dict(e,optical_track_id=e['entity'] if e.get('led_id') is None else None,
                       operator_confirmation=decisions.get(e['event_id'],decisions.get(e['entity'],{})).get('decision')) for e in events]
    _write_csv(output/'electrical_operations.csv',operations)
    _write_csv(output/'optical_events.csv',optical_rows)
    _write_csv(output/'electrical_optical_mapping.csv',mapped,MAPPING_FIELDS)
    _write_csv(output/'short_pulse_summary.csv',summary)
    empirical=[r['requested_duration_ms'] for r in summary if r['requested']>=10 and r['completed']==r['requested']
               and r['confirmed_operations']==r['requested'] and not extras]
    result=dict(schema_version=1,source_session_sha256=image_hash(session_path),session_id=session.get('session_id'),
        simulation=session.get('simulation',False),alignment=alignment,mapping=mapped,short_pulse_summary=summary,
        extra_optical_event_ids=[e['event_id'] for e in extras],boundary_residuals=boundary,
        warning=WARNING,minimum_reliable_duration_ms=None,
        series_minimum_all_confirmed_ms=min(empirical) if empirical else None,
        series_minimum_semantics='At least 10 completed trials, all optically confirmed, no unassociated candidates; conditional empirical result, not general reliability',
        reliability_status='NOT_ESTABLISHED_BY_SYNTHETIC_OR_SINGLE_SERIES; inspect repeated real series and exposure')
    atomic_json(output/'experiment_mapping.json',result)
    return result


def link_analysis(path, session_path):
    """Called by GUI/worker only after optical results have been written."""
    import uuid
    path=Path(path);target=path/('correspondence_'+uuid.uuid4().hex)
    report=json.loads((path/'events.json').read_text(encoding='utf-8'))
    result=build_tables(report,session_path,target,path/'frame_observations.csv',load_decisions(path))
    atomic_json(path/'correspondence_link.json',dict(directory=target.name,session=str(Path(session_path).resolve())))
    atomic_json(path/'alignment.json',result['alignment'])
    return result
