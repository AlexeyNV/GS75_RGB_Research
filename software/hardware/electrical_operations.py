"""Read-only normalization of PHOTO journals and future PAIR probe imports.

No transport, arming, optical detection or inference from current lives here.
UTC-only legacy probe records intentionally have no monotonic alignment anchors.
"""
import json
from pathlib import Path
import re


def load_operations(session_path):
    path = Path(session_path)
    session = json.loads(path.read_text(encoding='utf-8'))
    log = path.parent/'events.jsonl'
    events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.is_file() else []
    origin = session.get('monotonic_origin_ns')
    measurements = list(session.get('measurements', []))
    plan = [s for s in session.get('planned', []) if s.get('color') != 'OFF']
    if not plan: plan = [dict(index=i+1, **{k: r[k] for k in ('color', 'duration_ms', 'role') if k in r}) for i, r in enumerate(measurements)]
    operations = []
    for index, stage in enumerate(plan):
        row = next((m for m in measurements if m.get('stage_index') == stage['index']), None)
        if row is None and index < len(measurements) and 'stage_index' not in measurements[index]: row = measurements[index]
        row = row or {}
        command = row.get('command', '')
        match = re.fullmatch(r'PHOTO (LED\d+) (RED|GREEN|BLUE) (\d+)', command)
        color = row.get('color', stage.get('color'))
        source = row.get('source', 14 if match else None)
        sink = row.get('sink', {'RED': 32, 'GREEN': 33, 'BLUE': 34}.get(color) if match else None)
        ack, done, sent = row.get('ack_ns'), row.get('done_ns'), row.get('tx_ns')
        if sent is None and ack is not None:
            preceding = [e['monotonic_ns'] for e in events if e.get('direction') == 'TX' and e.get('text') == command
                         and e.get('monotonic_ns') is not None and e['monotonic_ns'] <= ack]
            sent = max(preceding) if preceding else None
        relative = lambda value: (value-origin)/1e9 if value is not None and origin is not None else None
        status = row.get('status', 'NOT_EXECUTED')
        if status == 'COMPLETED' and (row.get('fault') != 'NONE' or row.get('reason') != 'TIMEOUT'): status = 'FAILED'
        operations.append(dict(experiment_id=session.get('session_id'), operation_key=f'OP{index+1:04d}',
            operation_id=row.get('id'), mode='PHOTO', stage_index=stage['index'],
            role=row.get('role', stage.get('role', 'EXPERIMENT')), source_kp=source, sink_kp=sink,
            pcb_led_id=match[1] if match else ('LED49' if session.get('scenario', '').startswith('LED49_') else None),
            color=color, requested_duration_ms=row.get('duration_ms', stage.get('duration_ms')),
            measured_duration_ms=row.get('elapsed_ms'), current_avg_ua=row.get('current_avg_ua'),
            current_max_ua=row.get('current_max_ua'), adc_samples=row.get('samples'), fault=row.get('fault'),
            electrical_status=status, reason=row.get('reason'), command=command or None,
            host_tx_s=relative(sent), host_ack_s=relative(ack), host_done_s=relative(done),
            tx_ns=sent, ack_ns=ack, done_ns=done, off_confirmed=row.get('off_confirmed'),
            simulation=session.get('simulation', False), utc_started=session.get('utc_started')))
    return session, operations


def operations_from_probe(report):
    """Adapter contract for PAIR 10..300 ms; never executes the supplied plan.

    Legacy rgb_probe has UTC but no monotonic anchors. Preserve that absence;
    a future scanner must supply host_tx_s/ack_s/done_s in one clock domain.
    """
    result = []
    for index, row in enumerate(report.get('records', [])):
        duration = row.get('duration_ms')
        if duration is not None and not 10 <= duration <= 300: raise ValueError('PAIR duration outside FW limits')
        result.append(dict(experiment_id=report.get('experiment_id'), operation_key=f'PAIR{index+1:04d}',
            operation_id=row.get('command_id'), mode='PAIR', role='SCAN_PAIR', source_kp=row.get('source'),
            sink_kp=row.get('sink'), requested_duration_ms=duration, measured_duration_ms=row.get('elapsed_ms'),
            current_avg_ua=row.get('current_avg_ua'), current_max_ua=row.get('current_max_ua'),
            adc_samples=row.get('samples'), fault=row.get('fault'), reason=row.get('reason'),
            electrical_status=row.get('status'), pcb_led_id=None, color=None,
            host_tx_s=row.get('host_tx_s'), host_ack_s=row.get('host_ack_s'), host_done_s=row.get('host_done_s'),
            utc_started=row.get('timestamp_utc'), ack_utc=row.get('ack_utc'), done_utc=row.get('done_utc'),
            current_candidate=row.get('current_candidate'), simulation=report.get('simulation', False)))
    return result
