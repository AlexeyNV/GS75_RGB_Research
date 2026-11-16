"""Decode-inclusive offline experiments; reports never infer realtime from average FPS alone."""
import csv
import gc
import json
from pathlib import Path
import threading
import time
import numpy as np
from .frame_profile import FrameProfile,STAGES,AUX_STAGES,stats,machine_info,rss_bytes
from .pts_video import SequentialVideoReader
from .off_background import build_off
from .video_engine import VideoEngine,EventAggregator
from .project_storage import atomic_json
from .research_project import checkpoint
from .image_registration import transform_points


class MemorySampler:
    def __init__(self):self.peak=0;self.stop=threading.Event()
    def sample(self):
        while not self.stop.is_set():
            value=rss_bytes()
            if value is not None:self.peak=max(self.peak,value)
            self.stop.wait(.01)
    def __enter__(self):
        self.thread=threading.Thread(target=self.sample,daemon=True);self.thread.start();return self
    def __exit__(self,*args):self.stop.set();self.thread.join()


def frame_signature(result):
    if result['registration_status']=='FAILED' or result['analysis_status']=='FAILED':return []
    return sorted((r.get('led_id') or 'UNKNOWN',r['status'],r['color']) for r in result['records'])


def run_variant(video,calibration,off,variant,cancel,limit=120,warmup=3,mode='KNOWN_LEDS',notify=lambda *args:None):
    engine=VideoEngine(calibration,off,variant,mode)
    reader=SequentialVideoReader();rows=[];aggregator=EventAggregator()
    warm_count=0;decode_errors=[]
    try:
        meta=reader.open(video)
        for i in range(warmup):
            checkpoint(cancel)
            try:image,_=reader.frame(i)
            except StopIteration:break
            engine.process(image);warm_count+=1
        reader.close();reader.open(video)  # measured pass starts at frame zero, with fresh decoding
        cpu_start=time.process_time_ns();wall_start=time.perf_counter_ns()
        with MemorySampler() as memory:
            index=0
            while not limit or index<limit:
                checkpoint(cancel);profile=FrameProfile()
                try:
                    with profile.activate(),profile.stage('FRAME_TOTAL'):
                        with profile.stage('VIDEO_DECODE'):image,info=reader.frame(index)
                        result=engine.process(image)
                        aggregator.feed(result,info['timestamp_ms'],info['frame_index'])
                except StopIteration:break
                except Exception as exc:
                    # A decoder/processing error stops this pass; no silent seeks or dropped frames.
                    if cancel.is_set():raise
                    decode_errors.append(dict(frame=index,error=str(exc)));break
                row=dict(**info,**profile.milliseconds(),registration=result['registration_status'],
                    analysis=result['analysis_status'],signature=frame_signature(result),
                    records=result['records'],fallback=result['fallback'],warnings=result.get('warnings',[]),
                    geometry=result['registrations']['on'])
                rows.append(row);index+=1
                if index%5==0:notify(index,limit or meta['frame_count'] or index,dict(benchmark_frame_ms=row['FRAME_TOTAL'],variant=variant))
        wall_ns=time.perf_counter_ns()-wall_start;cpu_ns=time.process_time_ns()-cpu_start
    finally:reader.close()
    stage={name:stats([r[name] for r in rows]) for name in STAGES+AUX_STAGES}
    total=stage['FRAME_TOTAL']
    process_ms=[max(0,r['FRAME_TOTAL']-r['VIDEO_DECODE']) for r in rows]
    budgets={}
    for fps in (10,15,25,30,60):
        delay=0.;peak=0.
        for r in rows:delay=max(0.,delay+r['FRAME_TOTAL']-1000/fps);peak=max(peak,delay)
        fits=bool(rows) and total['p95_ms']<=1000/fps and total['mean_ms']<=(25 if fps==30 else 1000/fps)
        budgets[str(fps)]=dict(budget_ms=1000/fps,p95_fits=fits,simulated_queue_peak_ms=peak,
            note='Short offline sample, not a realtime guarantee; queue uses fixed target cadence')
    slowest=max((k for k in STAGES if k!='FRAME_TOTAL'),key=lambda k:stage[k]['mean_ms'] or 0)
    return dict(variant=variant,mode=mode,video=meta,frames=rows,stages=stage,
        decoded_measured=len(rows),warmup_frames=warm_count,warmup_restarted=True,
        registered_frames=sum(r['registration']=='REGISTERED' for r in rows),
        degraded_frames=sum(r['registration']=='DEGRADED' for r in rows),
        invalid_frames=sum(r['registration']=='FAILED' or r['analysis']=='FAILED' for r in rows),
        errors=decode_errors,lost_frames=max(0,(meta['frame_count'] or len(rows))-len(rows)) if decode_errors else 0,
        limited_to_frames=limit,full_video=not decode_errors and (not limit or len(rows)==meta['frame_count']),
        processing=stats(process_ms),decode=stage['VIDEO_DECODE'],end_to_end=total,
        wall_fps=len(rows)*1e9/wall_ns if wall_ns else None,wall_seconds=wall_ns/1e9,
        cpu_core_percent=100*cpu_ns/wall_ns,cpu_machine_percent=100*cpu_ns/wall_ns/max(1,machine_info()['logical_cpus']),
        peak_observed_rss_bytes=memory.peak or None,ram_measurement='Sampled process RSS every 10 ms, includes GUI/model; not isolated allocator peak',
        slowest_stage=slowest,budgets=budgets,events=aggregator.events())


def compare_quality(runs):
    reference=next((r for r in runs if r['variant']=='B_CACHED_FULL'),runs[0] if runs else None)
    if reference is None:return {}
    baseline={row['frame_index']:row for row in reference['frames']};out={}
    for run in runs:
        comparisons=[];marker_loss=0;max_error=0.;missing=[];max_centroid=0.;max_geometry_delta=0.
        for row in run['frames']:
            base=baseline.get(row['frame_index'])
            if base is None:missing.append(row['frame_index']);continue
            # Registration failures with no observations are compared explicitly.
            if row['signature']!=base['signature'] or row['registration']!=base['registration']:
                comparisons.append(dict(frame=row['frame_index'],reference=base['signature'],actual=row['signature'],
                    reference_registration=base['registration'],actual_registration=row['registration']))
            marker_loss+=len(set(base['geometry']['common_ids'])-set(row['geometry']['common_ids']))
            error=row['geometry']['reprojection_rmse_px']
            if error is not None:max_error=max(max_error,error)
            remaining=list(row['records'])
            for record in base['records']:
                matches=[r for r in remaining if r.get('led_id')==record.get('led_id') and r['color']==record['color']]
                if not matches:continue
                match=min(matches,key=lambda r:(r['x_ref_px']-record['x_ref_px'])**2+(r['y_ref_px']-record['y_ref_px'])**2)
                remaining.remove(match)
                a=[record.get('signal_x_ref_px',record['x_ref_px']),record.get('signal_y_ref_px',record['y_ref_px'])]
                b=[match.get('signal_x_ref_px',match['x_ref_px']),match.get('signal_y_ref_px',match['y_ref_px'])]
                max_centroid=max(max_centroid,float(np.linalg.norm(np.asarray(a)-b)))
                matrix,other=base['geometry']['matrix'],row['geometry']['matrix']
                if matrix is not None and other is not None:
                    source=transform_points([a],np.linalg.inv(matrix))
                    max_geometry_delta=max(max_geometry_delta,float(np.linalg.norm(transform_points(source,other)[0]-a)))
        out[run['variant']]=dict(reference_variant=reference['variant'],signature_mismatches=comparisons,
            marker_id_losses=marker_loss,uncompared_frames=missing,max_reprojection_rmse_px=max_error,
            same_measured_frame_count=len(run['frames'])==len(reference['frames']),
            max_signal_centroid_delta_px=max_centroid,max_local_geometry_delta_px=max_geometry_delta,
            verdict='PASS' if not comparisons and not marker_loss and not run['errors'] and run['registered_frames']>0
                and max_centroid<=3 and max_geometry_delta<=3 and len(run['frames'])==len(reference['frames']) else 'REVIEW_REQUIRED')
    return out


def benchmark(video,calibration,output,cancel=None,variants=VideoEngine.VARIANTS,limit=120,warmup=3,
              off=None,start_s=0.,duration_s=2.,mode='KNOWN_LEDS',notify=lambda *args:None,gui_open=False):
    cancel=cancel or threading.Event();output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError('Choose a new report directory')
    output.mkdir(parents=True,exist_ok=True)
    setup_start=time.perf_counter_ns()
    with MemorySampler() as setup_memory:
        if off is None:off=build_off(video,calibration,cancel,start_s,duration_s,notify=notify)
        off.save(output/'off_model')
    report=dict(schema_version=1,source=str(Path(video).resolve()),machine=machine_info(),gui_open=gui_open,
        mode=mode,off_setup_ms=(time.perf_counter_ns()-setup_start)/1e6,off_setup_peak_observed_rss_bytes=setup_memory.peak,
        off=off.metadata,
        calibration_version=calibration['calibration_version'],runs=[],quality={},cancelled=False,
        separate_costs_ms=dict(DIAGNOSTIC_PNG=0.,GUI_UPDATE=0.,RESULT_WRITE=0.))
    try:
        for variant in variants:
            checkpoint(cancel);gc.collect()
            run=run_variant(video,calibration,off,variant,cancel,limit,warmup,mode,notify)
            report['runs'].append(run);notify(len(report['runs']),len(variants),dict(name=variant,state='completed'))
            atomic_json(output/'checkpoint.json',report)
    except Exception:
        if not cancel.is_set():raise
        report['cancelled']=True
    report['quality']=compare_quality(report['runs'])
    started=time.perf_counter_ns();export_report(report,output)
    report['separate_costs_ms']['RESULT_WRITE']=(time.perf_counter_ns()-started)/1e6
    atomic_json(output/'benchmark.json',report)
    return report


def export_report(report,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    atomic_json(output/'benchmark.json',report)
    with (output/'frames.csv').open('w',encoding='utf-8',newline='') as stream:
        names=['variant','frame_index','pts','timestamp_ms','timestamp_source','registration','analysis','fallback']+list(STAGES+AUX_STAGES)
        writer=csv.DictWriter(stream,fieldnames=names);writer.writeheader()
        for run in report['runs']:
            for row in run['frames']:writer.writerow({key:run['variant'] if key=='variant' else row.get(key) for key in names})
    lines=['# RGB Vision v0.4-perf benchmark','',json.dumps(report['machine'],ensure_ascii=False),'',
        '| Variant | Frames | Mean ms | P50 | P95 | P99 | Max | FPS | RSS MiB | Quality |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for run in report['runs']:
        s=run['end_to_end'];quality=report.get('quality',{}).get(run['variant'],{}).get('verdict','uncompared')
        if not run['frames']:lines.append(f"| {run['variant']} | 0 | unavailable | | | | | | | {quality} |");continue
        lines.append(f"| {run['variant']} | {len(run['frames'])} | {s['mean_ms']:.3f} | {s['p50_ms']:.3f} | {s['p95_ms']:.3f} | {s['p99_ms']:.3f} | {s['max_ms']:.3f} | {s['fps']:.2f} | {(run['peak_observed_rss_bytes'] or 0)/2**20:.1f} | {quality} |")
        lines += ['',f"## {run['variant']} stages",'','| Stage | Mean ms | P50 | P95 | P99 | Max |','|---|---:|---:|---:|---:|---:|']
        for name in STAGES+AUX_STAGES:
            t=run['stages'][name]
            lines.append(f"| {name} | {t['mean_ms']:.3f} | {t['p50_ms']:.3f} | {t['p95_ms']:.3f} | {t['p99_ms']:.3f} | {t['max_ms']:.3f} |")
        lines += ['',f"Decode FPS: {run['decode']['fps']}; processing FPS: {run['processing']['fps']}; wall FPS: {run['wall_fps']}",
            f"Registered: {run['registered_frames']}; invalid: {run['invalid_frames']}; lost: {run['lost_frames']}; slowest: {run['slowest_stage']}",
            f"Budget checks: {json.dumps(run['budgets'])}"]
    lines += ['',f"Separate costs ms: {json.dumps(report['separate_costs_ms'])}; OFF setup ms: {report['off_setup_ms']:.3f}",
        'No frames are silently skipped. Warmup uses a separate decoder pass; measured pass restarts at zero.',
        'FRAME_TOTAL includes decoding and event aggregation. Other stages are exclusive. Uninstrumented bookkeeping remains in FRAME_TOTAL.',
        'PNG, GUI, result writing and OFF setup are separate from measured frame throughput.',
        'A short synthetic clip cannot establish sustained realtime capability or camera timestamp accuracy.']
    (output/'benchmark.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def plot_report(report,path):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    started=time.perf_counter_ns();fig=Figure(figsize=(11,5));FigureCanvasAgg(fig);ax=fig.add_subplot()
    for run in report['runs']:ax.plot([r['frame_index'] for r in run['frames']],[r['FRAME_TOTAL'] for r in run['frames']],label=run['variant'])
    ax.axhline(1000/30,color='red',linestyle='--',label='30 FPS budget')
    ax.set(xlabel='Decoded frame index',ylabel='Decode + processing (ms)',title='Offline measured frame time');ax.legend();fig.tight_layout();fig.savefig(path,dpi=130)
    report['separate_costs_ms']['DIAGNOSTIC_PNG']+=(time.perf_counter_ns()-started)/1e6
