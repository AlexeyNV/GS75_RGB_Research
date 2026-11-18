"""Read-only operation/frame audit from saved optical results, no serial/CV."""
import json
from pathlib import Path
from collections import Counter
from .experiment_mapping import build_tables,_write_csv,compatible
from .project_storage import atomic_json,image_hash
from software.hardware.electrical_operations import load_operations


def operation_diagnostics(analysis,session_path,output,baseline=None):
    analysis,output=Path(analysis),Path(output)
    report=json.loads((analysis/'events.json').read_text(encoding='utf-8'))
    result=build_tables(report,session_path,output,analysis/'frame_observations.csv')
    session,operations=load_operations(session_path)
    import csv
    with (analysis/'frame_observations.csv').open(encoding='utf-8-sig',newline='') as stream:observations=list(csv.DictReader(stream))
    raw={r['frame_index']:r for r in (json.loads(line) for line in (analysis/'frame_results.jsonl').read_text(encoding='utf-8').splitlines())}
    previous=None;previous_mapping=None
    if baseline:
        baseline=Path(baseline);previous=json.loads((baseline/'events.json').read_text(encoding='utf-8'))
        link=baseline/'correspondence_link.json'
        if link.is_file():
            bundle=json.loads(link.read_text(encoding='utf-8'))['directory']
            previous_mapping=json.loads((baseline/bundle/'experiment_mapping.json').read_text(encoding='utf-8'))
    offset=result['alignment']['offset_s'];margin=result['alignment']['uncertainty_s'] or 0.
    cadence=1/((report.get('video') or {}).get('fps') or 30.)
    operation_rows=[];frame_rows=[]
    for operation in operations:
        opid=operation['operation_id'];key=operation['operation_key']
        tx=operation.get('host_tx_s');ack=operation.get('host_ack_s');done=operation.get('host_done_s')
        start=tx-offset if offset is not None and tx is not None else None
        end=done-offset if offset is not None and done is not None else None
        linked=[r for r in result['mapping'] if r['operation_key']==key]
        ids={r['optical_event_id'] for r in linked if r['optical_event_id']}
        optical=[e for e in report['events'] if e['event_id'] in ids]
        before_events=[e for e in (previous or {}).get('events',[]) if start is not None and end is not None and e['end_pts']>=start-margin and e['start_pts']<=end+margin]
        before_rows=[r for r in (previous_mapping or {}).get('mapping',[]) if r['operation_id']==opid]
        selected=[r for r in observations if start is not None and end is not None and start-margin<=float(r['pts_s'])<=end+margin
                  and (r.get('led_id')==operation.get('pcb_led_id') or r.get('entity') in {e['entity'] for e in optical})]
        counts=Counter(r['state'] for r in selected)
        for row in selected:
            source=raw[int(row['frame_index'])];geometry=source['result']['registrations']['on']
            frame_rows.append(dict(operation_id=opid,operation_key=key,**row,
                geometry_reason=geometry.get('reason'),geometry_common_ids=geometry.get('common_ids'),
                geometry_inlier_ids=geometry.get('inlier_ids'),geometry_anchor_coverage=geometry.get('anchor_coverage'),
                temporal_event_ids=[e['event_id'] for e in optical if int(row['frame_index']) in e.get('positive_frame_indices',[])],
                matcher_status=[r['mapping_status'] for r in linked],host_tx_s=tx,host_ack_s=ack,host_done_s=done))
        operation_rows.append(dict(operation_id=opid,operation_key=key,duration_ms=operation['requested_duration_ms'],
            host_tx_s=tx,host_ack_s=ack,host_done_s=done,video_tx_estimate_s=start,
            video_ack_estimate_s=ack-offset if ack is not None and offset is not None else None,video_done_estimate_s=end,
            alignment_envelope_s=margin,current_avg_ua=operation['current_avg_ua'],current_max_ua=operation['current_max_ua'],
            electrical_status=operation['electrical_status'],before_event_ids=[e['event_id'] for e in before_events],
            before_event_statuses=[e['status'] for e in before_events],
            before_fragment_checks=[dict(event_id=e['event_id'],observed_span_ms=e['duration_s']*1000,
                span_error_ms=abs(e['duration_s']-operation['requested_duration_ms']/1000)*1000,
                old_span_tolerance_ms=max(2.5*cadence,.2*operation['requested_duration_ms']/1000)*1000,
                old_span_compatible=compatible(operation,e,cadence)) for e in before_events],
            before_matched=any(r['optical_event_id'] for r in before_rows),
            before_matcher_statuses=[r['optical_status'] for r in before_rows],
            event_ids=[e['event_id'] for e in optical],event_statuses=[e['status'] for e in optical],
            fragments=[f for e in optical for f in e.get('observation_fragments',[])],
            positive_frame_indices=[f for e in optical for f in e.get('positive_frame_indices',[])],
            first_on_pts=min([e['start_pts'] for e in optical],default=None),
            last_on_pts=max([e['end_pts'] for e in optical],default=None),
            confidence=[e['confidence'] for e in optical],duration_confirmed=[e['duration_confirmed'] for e in optical],
            uncertainty_flags=sorted({f for e in optical for f in e['uncertainty_flags']}),
            temporal_end_reasons=[e['end_reason'] for e in optical],
            unknown_gaps=[g for e in optical for g in e.get('unknown_gaps',[])],
            matcher_kinds=[r['association_kind'] for r in linked],matcher_statuses=[r['optical_status'] for r in linked],
            frame_states_in_expanded_window=dict(counts),
            reason='; '.join(r['rejection_or_uncertainty_reason'] for r in linked)))
    _write_csv(output/'operation_diagnostics.csv',operation_rows)
    _write_csv(output/'operation_frame_observations.csv',frame_rows)
    summary=dict(analysis_id=report.get('analysis_id'),algorithm_version=report['algorithm_version'],settings=report['settings'],
        video_sha256=report['source_sha256'],raw_sha256=image_hash(analysis/'frame_results.jsonl'),
        processed_frames=report['processed_frames'],optical_event_counts=dict(Counter(e['status'] for e in report['events'])),
        matched_operations=len({r['operation_key'] for r in result['mapping'] if r['optical_event_id']}),
        unobservable_operations=len({r['operation_key'] for r in result['mapping'] if r['optical_status']=='UNOBSERVABLE'}),
        reliable_off_frames=report['state_counts'].get('OFF',0),reliable_off_intervals=len(report.get('off_intervals',[])),
        unknown_frames=report.get('uncertainty_statistics'),uncertainty_intervals=len(report['uncertainty_intervals']),
        extra_optical_events=result['extra_optical_event_ids'],alignment=result['alignment'],operations=operation_rows,
        note='Expanded windows are diagnostic USB/video projections, not physical light boundaries; cache replay does not rerun OpenCV')
    atomic_json(output/'diagnostic_summary.json',summary)
    return summary
