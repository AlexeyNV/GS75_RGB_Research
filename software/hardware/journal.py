"""Incremental UTC / monotonic-nanosecond session journal; no media copies."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
from .scenario import NAME, VERSION, planned


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_session(path, data):
    path = Path(path)
    temporary = path / 'session.tmp'
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path / 'session.json')


class Journal:
    def __init__(self, root, stages, port, conditions, clock_ns=time.monotonic_ns):
        self.clock_ns = clock_ns
        self.start_ns = clock_ns()
        self.path = Path(root) / (datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S') + '_LED49_RGB_' + uuid.uuid4().hex[:12])
        self.path.mkdir(parents=True, exist_ok=False)
        self.data = dict(schema_version=1, application='GS75 RGB Vision', app_version=VERSION,
            session_id=self.path.name, utc_started=utc_now(), monotonic_origin_ns=self.start_ns,
            port=port, scenario=NAME, planned=planned(stages), actual=[], measurements=[],
            conditions=conditions, safety_check='OPERATOR_CONFIRMED_PHYSICAL_CONDITIONS',
            status='RUNNING', off_confirmed=False, diagnostics=None, video=None,
            synchronization=dict(status='UNALIGNED', offset_ms=None, uncertainty_ms=None,
                optical_transitions=[], anchors=['RED', 'GREEN', 'BLUE'],
                warning='USB TX/ACK/DONE are host observations, not optical edges. PC/phone UTC alone cannot align video.'),
            limitations=['IWDG_DISABLED; MCU hang may require physical power removal',
                'OFF/STATUS confirms reported EN, not measured physical EN',
                'New GUI has not yet been accepted on real hardware'])
        self.events = []
        self.save()

    def event(self, direction, text, **extra):
        event = dict(utc=utc_now(), monotonic_ns=self.clock_ns(), direction=direction, text=text, **extra)
        event['relative_ms'] = (event['monotonic_ns'] - self.start_ns) / 1e6
        self.events.append(event)
        with (self.path / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush()
        return event

    def save(self):
        save_session(self.path, self.data)
        columns = ['color', 'source', 'sink', 'command', 'id', 'duration_ms', 'current_avg_ua',
            'current_max_ua', 'samples', 'elapsed_ms', 'reason', 'fault', 'status', 'ack_ns', 'done_ns', 'warning']
        with (self.path / 'measurements.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
            writer.writeheader(); writer.writerows(self.data['measurements'])
        lines = [f"# {NAME} — {self.data['status']}", '', f"Session: {self.data['session_id']}",
            f"UTC: {self.data['utc_started']}; app {VERSION}; port {self.data['port']}",
            f"FW: {(self.data.get('diagnostics') or {}).get('info', {}).get('FW', 'unknown')}",
            f"OFF confirmed by protocol: {self.data['off_confirmed']}",
            f"Reason: {self.data.get('reason', '')}", '',
            'Physical conditions: operator declarations only. IWDG disabled; keep power accessible.',
            'TX/ACK/DONE timestamps include USB/host latency; optical synchronization is UNALIGNED.', '',
            'Plan and actual intervals (ns/ms):', '```json',
            json.dumps(dict(planned=self.data['planned'], actual=self.data['actual']), ensure_ascii=False, indent=2),
            '```', '', 'Electrical measurements: see measurements.csv; full TX/RX: events.jsonl.',
            'Safety / diagnostics / video / alignment: see session.json.']
        (self.path / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
