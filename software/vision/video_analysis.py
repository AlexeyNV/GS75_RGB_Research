"""Offline, all-frame RGB events. One OFF, one decode/process pass, bounded images."""
from dataclasses import asdict
from copy import deepcopy
import csv
import json
from pathlib import Path
import threading
import time
from .temporal_events import VERSION,TemporalSettings
from .video_temporal import FrameTemporalAnalysis
from .video_engine import VideoEngine
from .off_background import build_off
from .pts_video import SequentialVideoReader
from .frame_profile import FrameProfile,STAGES,stats,machine_info
from .video_benchmark import MemorySampler
from .project_storage import atomic_json,image_hash
from .research_project import checkpoint,Cancelled
from .video_event_export import export_analysis,plot_timeline
from .event_alignment import align_session


OBSERVATION_FIELDS=['frame_index','pts','time_base','pts_s','entity','led_id','key_name','state','raw_state','color',
    'x_ref_px','y_ref_px','brightness','chroma','area_px','confidence','registration','rmse_px','coverage','off_coverage','reasons']


def analyze_video(video,calibration,output,mode='KNOWN_LEDS',settings=None,start_s=0.,duration_s=2.,
                  cancel=None,notify=lambda *args:None,off=None,session_path=None):
    if mode not in ('KNOWN_LEDS','DISCOVER'):raise ValueError('Unknown video analysis mode')
    if mode=='KNOWN_LEDS' and not calibration['leds']:raise ValueError('KNOWN_LEDS needs a marked LED map')
    cancel=cancel or threading.Event();settings=settings or TemporalSettings();output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    report=dict(schema_version=1,algorithm_version=VERSION,status='RUNNING',source=str(Path(video).resolve()),
        source_sha256=image_hash(video),calibration_version=calibration['calibration_version'],settings=asdict(settings),mode=mode,
        processed_frames=0,events=[],unknown_tracks=[],uncertainty_intervals=[],state_counts={},
        temporal_ms=0.,temporal_mean_ms=0.,video=None,off=None,machine=machine_info(),
        limitations=['Frame PTS endpoints are not physical light switching times',
            'Continuity across unknown gaps is a hypothesis; duration may be censored',
            'Unknown tracks have no automatic PCB LED ID', 'Optical evidence is not electrical proof'])
    atomic_json(output/'calibration_snapshot.json',calibration);export_analysis(report,output)
    reader=SequentialVideoReader();temporal=None;timings=[];processing_started=None;memory=None
    started=time.perf_counter_ns()
    try:
        checkpoint(cancel);setup=time.perf_counter_ns()
        if off is None:off=build_off(video,calibration,cancel,start_s,duration_s,notify=notify,diagnostics_dir=output/'off_diagnostics')
        if off.calibration_version!=calibration['calibration_version']:raise ValueError('OFF calibration mismatch')
        off.save(output/'off_model');report['off']=off.metadata
        from .off_diagnostics import save_diagnostics
        from .off_background import without_markers
        save_diagnostics(output,off.metadata,off.image,without_markers(off.mask,calibration),calibration)
        report['off_setup_ms']=(time.perf_counter_ns()-setup)/1e6
        data=deepcopy(calibration)
        if mode=='DISCOVER':data['leds']=[]
        report['known_led_coordinates_used']=mode=='KNOWN_LEDS'
        engine=VideoEngine(data,off,'C_HYBRID',mode);temporal=FrameTemporalAnalysis(data,off,mode,settings)
        meta=reader.open(video);report['video']=meta
        processing_started=time.perf_counter_ns();cpu_started=time.process_time_ns()
        with MemorySampler() as memory, (output/'frame_results.jsonl').open('x',encoding='utf-8') as raw, \
             (output/'frame_observations.csv').open('x',encoding='utf-8',newline='') as observations:
            writer=csv.DictWriter(observations,fieldnames=OBSERVATION_FIELDS,extrasaction='ignore');writer.writeheader()
            index=0
            while True:
                checkpoint(cancel);profile=FrameProfile()
                try:
                    with profile.activate(),profile.stage('FRAME_TOTAL'):
                        with profile.stage('VIDEO_DECODE'):image,info=reader.frame(index)
                        result=engine.process(image)
                        normalized=temporal.feed(result,info)
                except StopIteration:break
                # Disk IO is outside the measured OpenCV/temporal section.
                raw.write(json.dumps(dict(**info,result=result),ensure_ascii=False)+'\n');raw.flush()
                for row in normalized:writer.writerow(dict(row,reasons=json.dumps(row['reasons'],ensure_ascii=False)))
                observations.flush();timings.append(dict(frame_index=index,**profile.milliseconds()))
                index+=1;report['processed_frames']=index
                if index%5==0:
                    elapsed=(time.perf_counter_ns()-processing_started)/1e9
                    notify(index,meta['frame_count'] or index+1,dict(name='VIDEO_ANALYSIS',state='processing',frame=index-1,
                        pts_s=info['timestamp_ms']/1000,states=dict(temporal.state_counts),frame_states=dict(temporal.frame_state_counts),
                        confirmed_events=sum(e['status']=='CONFIRMED' for e in temporal.detector.completed),
                        eta_s=elapsed/index*max(0,meta['frame_count']-index) if meta['frame_count'] else None))
        report['processing_wall_s']=(time.perf_counter_ns()-processing_started)/1e9
        report['cpu_seconds']=(time.process_time_ns()-cpu_started)/1e9
        if not report['processed_frames']:raise ValueError('No decoded observations')
        if meta['frame_count'] and report['processed_frames']!=meta['frame_count']:raise ValueError('Premature EOF: decoded frame count differs from video metadata')
        report['status']='COMPLETED'
    except Cancelled:report.update(status='CANCELLED',error='Operator cancelled; partial frames and events retained')
    except Exception as exc:
        import logging
        logging.exception('Offline video analysis failed')
        report.update(status='FAILED',error=type(exc).__name__+': '+str(exc),failed_at_frame=report['processed_frames'])
    finally:
        reader.close()
        if temporal:report.update(temporal.finish())
        if processing_started and 'processing_wall_s' not in report:report['processing_wall_s']=(time.perf_counter_ns()-processing_started)/1e9
        if memory:report['peak_observed_rss_bytes']=memory.peak
        report['total_wall_s']=(time.perf_counter_ns()-started)/1e9
        report['wall_fps']=report['processed_frames']/max(report.get('processing_wall_s',0.),1e-9)
        report['frame_stage_stats']={name:stats([r[name] for r in timings]) for name in STAGES}
        with (output/'performance_frames.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['frame_index',*STAGES],extrasaction='ignore');writer.writeheader();writer.writerows(timings)
        if not (output/'frame_results.jsonl').exists():(output/'frame_results.jsonl').touch()
        if not (output/'frame_observations.csv').exists():
            with (output/'frame_observations.csv').open('w',encoding='utf-8',newline='') as stream:csv.writer(stream).writerow(OBSERVATION_FIELDS)
        export_analysis(report,output)
        plot_timeline(report,output/'timeline.png')
    if session_path and report['status']=='COMPLETED':
        try:atomic_json(output/'alignment.json',align_session(report['events'],session_path))
        except Exception as exc:atomic_json(output/'alignment.json',dict(status='FAILED',error=str(exc)))
    return report


def reaggregate_video(source,output,settings=None,cancel=None,notify=lambda *args:None,video=None):
    """New immutable run from compact original observations. No decode/ArUco/OFF work."""
    import shutil
    from types import SimpleNamespace
    from .project_storage import read_image
    source,output=Path(source),Path(output);cancel=cancel or threading.Event()
    report=json.loads((source/'events.json').read_text(encoding='utf-8'))
    if report['status']!='COMPLETED':raise ValueError('Temporal reuse requires a completed source run')
    if video is not None:
        if image_hash(video)!=report['source_sha256']:raise ValueError('Video SHA-256 differs from cached observations')
        report['source']=str(Path(video).resolve())
    output.mkdir(parents=True,exist_ok=False)
    settings=settings or TemporalSettings(**report['settings'])
    calibration=json.loads((source/'calibration_snapshot.json').read_text(encoding='utf-8'))
    if report['mode']=='DISCOVER':calibration['leds']=[]
    for name in ['frame_results.jsonl','calibration_snapshot.json','performance_frames.csv','off_coverage.png','led49_coverage.png']:
        if (source/name).is_file():shutil.copyfile(source/name,output/name)
    shutil.copytree(source/'off_model',output/'off_model')
    off=SimpleNamespace(mask=read_image(output/'off_model/valid_mask.png')[:,:,0])
    temporal=FrameTemporalAnalysis(calibration,off,report['mode'],settings)
    report.update(status='RUNNING',settings=asdict(settings),algorithm_version=VERSION,temporal_reuse_source=str(source.resolve()),
        processed_frames=0,opencv_rerun=False,
        performance_provenance='OpenCV throughput/timing from source run; temporal reanalysis is measured separately')
    started=time.perf_counter_ns()
    try:
        with (source/'frame_results.jsonl').open(encoding='utf-8') as stream,(output/'frame_observations.csv').open('x',encoding='utf-8',newline='') as csv_stream:
            writer=csv.DictWriter(csv_stream,fieldnames=OBSERVATION_FIELDS,extrasaction='ignore');writer.writeheader()
            for line in stream:
                checkpoint(cancel);frame=json.loads(line)
                for row in temporal.feed(frame['result'],frame):writer.writerow(dict(row,reasons=json.dumps(row['reasons'],ensure_ascii=False)))
                report['processed_frames']+=1
                if report['processed_frames']%20==0:notify(report['processed_frames'],report['video']['frame_count'],dict(name='TEMPORAL_REUSE',state='no_OpenCV'))
        report['status']='COMPLETED'
    except Cancelled:report.update(status='CANCELLED',error='Temporal reanalysis cancelled')
    except Exception as exc:report.update(status='FAILED',error=str(exc))
    report.update(temporal.finish());report['temporal_reanalysis_wall_s']=(time.perf_counter_ns()-started)/1e9
    export_analysis(report,output);plot_timeline(report,output/'timeline.png')
    return report
