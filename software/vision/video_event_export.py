"""Portable event artifacts and operator decisions kept separate from automatic results."""
import csv
from datetime import datetime,timezone
import json
from pathlib import Path
from .project_storage import atomic_json


EVENT_FIELDS={'LED_ID':'led_id','KEY_NAME':'key_name','COLOR':'color','START_PTS':'start_pts',
    'END_PTS':'end_pts','DURATION_S':'duration_s','START_FRAME':'start_frame','END_FRAME':'end_frame',
    'CONFIDENCE':'confidence','STATUS':'status','COVERAGE':'coverage','UNCERTAINTY_FLAGS':'uncertainty_flags',
    'EVENT_ID':'event_id','ENTITY':'entity'}


def export_analysis(report,output):
    output=Path(output);atomic_json(output/'events.json',report)
    atomic_json(output/'unknown_tracks.json',dict(tracks=report.get('unknown_tracks',[]),requires_manual_PCB_ID=True))
    atomic_json(output/'uncertainty_intervals.json',report.get('uncertainty_intervals',[]))
    with (output/'events.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(EVENT_FIELDS));writer.writeheader()
        for event in report.get('events',[]):writer.writerow({key:json.dumps(event[value]) if isinstance(event.get(value),list) else event.get(value) for key,value in EVENT_FIELDS.items()})
    lines=['# Video events — '+report['status'],'',
        f"Algorithm {report['algorithm_version']}; mode {report['mode']}; frames {report['processed_frames']}",
        f"State counts: {report.get('state_counts',{})}",
        f"Temporal elapsed section ms: {report.get('temporal_ms')}; mean/frame: {report.get('temporal_mean_ms')}",
        f"Reason: {report.get('error','')}",'',
        '| Entity | Color | Start PTS | End PTS | Observed span s | Status | Confidence |',
        '|---|---|---:|---:|---:|---|---:|']
    for e in report.get('events',[]):lines.append(f"| {e['entity']} | {e['color']} | {e['start_pts']:.6f} | {e['end_pts']:.6f} | {e['duration_s']:.6f} | {e['status']} | {e['confidence']:.3f} |")
    lines+=['','Endpoints are observed frame PTS, not subframe/electrical switching times.',
        'UNKNOWN gaps remain in uncertainty_intervals.json. Continuity across a short gap is only a hypothesis.',
        'CONFIRMED means optical evidence persists; it does not confirm PCB identity for unknown tracks or an exact physical duration.',
        'Automatic results are immutable. Operator decisions: manual_decisions.jsonl, separate from events.json.',
        'Original compact VideoEngine results: frame_results.jsonl. No firmware or hardware is accessed.']
    (output/'validation_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def plot_timeline(report,path):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig=Figure(figsize=(12,4));FigureCanvasAgg(fig);axis=fig.add_subplot()
    entities=sorted({e['entity'] for e in report.get('events',[])}|{u['entity'] for u in report.get('uncertainty_intervals',[])}|{o['entity'] for o in report.get('off_intervals',[])})
    colors=dict(RED='#e44949',GREEN='#32a852',BLUE='#4388e8',MIXED='#a44ccc')
    for i,entity in enumerate(entities):
        for o in report.get('off_intervals',[]):
            if o['entity']==entity:axis.broken_barh([(o['start_s'],max(.01,o['end_s']-o['start_s']))],(i-.35,.7),facecolors='#6f7e88')
        for e in report.get('events',[]):
            if e['entity']==entity:axis.broken_barh([(e['start_pts'],max(.01,e['duration_s']))],(i-.22,.44),facecolors=colors.get(e['color'],'#aaa'),alpha=.9 if e['status']=='CONFIRMED' else .35)
        for u in report.get('uncertainty_intervals',[]):
            if u['entity']==entity:axis.broken_barh([(u['start_s'],max(.01,u['end_s']-u['start_s']))],(i-.35,.7),facecolors='none',hatch='////',edgecolors='#999')
    axis.set(yticks=list(range(len(entities))),yticklabels=entities,xlabel='Video PTS (s)',title='Optical hypotheses; grey hatch = uncertainty (not OFF)')
    axis.grid(axis='x',alpha=.3);fig.tight_layout();fig.savefig(path,dpi=130)


def save_decision(output,target,decision,note='',pcb_led_id=None):
    if decision not in ('ACCEPTED','REJECTED','RESET'):raise ValueError('Invalid manual decision')
    row=dict(utc=datetime.now(timezone.utc).isoformat(),target=target,decision=decision,note=note,
             pcb_led_id=pcb_led_id,decision_source='OPERATOR')
    with (Path(output)/'manual_decisions.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    return row


def load_decisions(output):
    path=Path(output)/'manual_decisions.jsonl';result={}
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            row=json.loads(line);result[row['target']]=row
    return result
