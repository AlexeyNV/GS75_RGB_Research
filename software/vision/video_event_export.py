"""Portable event artifacts and operator decisions kept separate from automatic results."""
import csv
from datetime import datetime,timezone
import json
from pathlib import Path
from .project_storage import atomic_json


EVENT_FIELDS={'LED_ID':'led_id','KEY_NAME':'key_name','COLOR':'color','START_PTS':'start_pts',
    'END_PTS':'end_pts','DURATION_S':'duration_s','START_FRAME':'start_frame','END_FRAME':'end_frame',
    'CONFIDENCE':'confidence','STATUS':'status','COVERAGE':'coverage','UNCERTAINTY_FLAGS':'uncertainty_flags',
    'EVENT_ID':'event_id','ENTITY':'entity','OBSERVATION_FRAGMENTS':'observation_fragments',
    'MAX_CONSECUTIVE_GOOD':'max_consecutive_good_observations','POSITIVE_FRAME_INDICES':'positive_frame_indices'}


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


def plot_operation_timeline(report,operations,alignment,path,limits=None,timestamps=()):
    """Export the same separate evidence lanes, with explicit USB uncertainty."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig=Figure(figsize=(13,5));FigureCanvasAgg(fig);axes=fig.subplots(5,1,sharex=True)
    labels=['STM32 (USB projection)','Optical CONFIRMED','Optical CANDIDATE','UNKNOWN / INVALID','Reliable sampled OFF']
    for axis,label in zip(axes,labels):
        axis.set(yticks=[]);axis.set_ylabel(label,rotation=0,ha='right',va='center',labelpad=12,fontsize=9)
        axis.grid(axis='x',alpha=.25)
    colors=dict(RED='#df4545',GREEN='#32a85a',BLUE='#4388e8')
    offset=alignment.get('offset_s');margin=alignment.get('uncertainty_s') or 0.
    if offset is not None:
        for operation in operations:
            if operation.get('host_ack_s') is None:continue
            start=operation['host_ack_s']-offset;duration=(operation.get('measured_duration_ms') or operation['requested_duration_ms'])/1000
            axes[0].broken_barh([(start-margin,duration+2*margin)],(0,1),facecolors='none',edgecolors='#8ca6bc',hatch='///')
            axes[0].broken_barh([(start,duration)],(0,1),facecolors='#3e6c91')
    else:axes[0].text(.1,.5,'UNALIGNED / AMBIGUOUS',transform=axes[0].transAxes)
    for event in report.get('events',[]):
        if event['status'] not in ('CONFIRMED','CANDIDATE'):continue
        axis=axes[1 if event['status']=='CONFIRMED' else 2]
        if event['duration_s']:
            axis.broken_barh([(event['start_pts'],event['duration_s'])],(0,1),facecolors=colors.get(event['color'],'#aaa'),alpha=.9 if event['status']=='CONFIRMED' else .45)
        else:axis.plot([event['start_pts']],[.5],'o',color=colors.get(event['color'],'#aaa'))
    for interval in report.get('uncertainty_intervals',[]):
        axes[3].broken_barh([(interval['start_s'],max(.001,interval['end_s']-interval['start_s']))],(0,1),facecolors='none',edgecolors='#9a8f7b',hatch='////')
    for interval in report.get('off_intervals',[]):
        axes[4].broken_barh([(interval['start_s'],max(.001,interval['end_s']-interval['start_s']))],(0,1),facecolors='#6f7e88')
    if limits:
        axes[-1].set_xlim(*limits)
        for t in timestamps:
            if limits[0]<=t<=limits[1]:
                for axis in axes:axis.axvline(t,color='#bbb',linewidth=.4,linestyle=':')
    axes[-1].set_xlabel('Actual video PTS (s); optical span is not physical pulse duration')
    fig.suptitle('Independent optical evidence; electrical lane is an empirical USB/video projection',y=.99,fontsize=10)
    fig.tight_layout(rect=(0,0,1,.94));fig.savefig(path,dpi=130)


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
