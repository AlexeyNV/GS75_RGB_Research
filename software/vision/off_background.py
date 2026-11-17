"""Bounded, per-frame registered automatic OFF construction. No hardware actions."""
from dataclasses import dataclass
from pathlib import Path
import math
import numpy as np
import cv2
from .image_registration import register,Registration
from .project_storage import read_image,write_image,atomic_json
from .pts_video import SequentialVideoReader
from .led_detection import lighting_difference
from .optical_signal import signal_maps
from .research_project import checkpoint


def without_markers(mask,calibration):
    mask=mask.copy()
    for corners in calibration['markers'].values():
        a=np.asarray(corners,float);a=a.mean(axis=0)+(a-a.mean(axis=0))*1.55
        cv2.fillConvexPoly(mask,a.astype(np.int32),0)
    return mask


@dataclass
class OffModel:
    image: object
    mask: object
    registration: Registration
    calibration_version: str
    metadata: dict
    original: object=None

    def save(self,path):
        path=Path(path);path.mkdir(parents=True,exist_ok=False)
        write_image(path/'off.png',self.image);write_image(path/'valid_mask.png',self.mask)
        atomic_json(path/'off_model.json',dict(self.metadata,calibration_version=self.calibration_version))


def from_photo(image,calibration):
    r=register(image,calibration)
    if r.status=='FAILED':raise ValueError('OFF registration failed: '+r.reason)
    from .off_diagnostics import roi_coverage
    coverage=roi_coverage(without_markers(r.valid_mask,calibration),calibration)
    if any(value<.9 for value in coverage.values()):raise ValueError('Known LED outside explicit OFF-photo coverage')
    metadata=dict(source='explicit_photo',status='READY',retained_frames=1,candidates=[],
        valid_fraction=float(np.mean(r.valid_mask>0)),coverage=dict(known_leds=coverage))
    return OffModel(r.warped,r.valid_mask,r,calibration['calibration_version'],metadata,image)


def identity_registration(image,mask,metadata):
    return Registration(status='REGISTERED',reason='Validated multi-frame OFF model',
        error_px=metadata.get('max_rmse_px',0.),max_error_px=metadata.get('max_error_px',0.),
        inlier_ids=metadata.get('marker_ids',[]),common_ids=metadata.get('marker_ids',[]),
        matrix=np.eye(3),warped=image,valid_mask=mask)


def build_off(video,calibration,cancel,start_s=0.,duration_s=2.,max_frames=5,notify=lambda *args:None,diagnostics_dir=None):
    """Bounded adaptive search; retain the best <=5 observations, inspect the full interval."""
    from .off_diagnostics import (OffBuildError,roi_coverage,pcb_region,quality_maps,glow_regions,
                                  save_candidate,save_diagnostics,masked_median_tile)
    import time
    started=time.perf_counter_ns()
    if not math.isfinite(start_s+duration_s) or start_s<0 or duration_s<=0 or not 3<=max_frames<=9:
        raise ValueError('Invalid OFF interval or frame bound')
    if calibration.get('camera_model'):raise ValueError('Video-specific camera intrinsics are not yet validated; camera_model must be null')
    reader=SequentialVideoReader();frames=[];masks=[];accepted=[];rejected=[];candidates=[];retained=[]
    anchor=anchor_mask=pcb=None;unsafe=[];decoded=0
    diagnostics=dict(status='BUILDING',source='automatic_video_median',start_s=start_s,duration_s=duration_s,
        candidates=candidates,retained_frames=0,accepted=accepted,rejected=rejected)
    def fail(reason):
        diagnostics.update(status='FAILED',failure=reason,retained_frames=len(retained),decoded_frames=decoded,
                           setup_ms=(time.perf_counter_ns()-started)/1e6)
        save_diagnostics(diagnostics_dir,diagnostics)
        raise OffBuildError(diagnostics,diagnostics_dir)
    try:
        meta=reader.open(video);end_s=start_s+duration_s
        # At most 24 registrations; retries throughout the interval, not only four fixed samples.
        next_time=start_s;period=duration_s/23;index=0
        while True:
            checkpoint(cancel)
            try:image,info=reader.frame(index)
            except StopIteration:break
            decoded+=1;index=info['frame_index']+1
            seconds=info['timestamp_ms'] if info['timestamp_ms'] is not None else info['estimated_ms']
            if seconds is None:fail('No usable timestamp for OFF interval')
            seconds/=1000
            if seconds>=end_s-1e-6:break
            if seconds+1e-6<next_time or len(candidates)>=24:continue
            next_time=seconds+period
            r=register(image,calibration)
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
            row=dict(**info,registration=r.summary(),reason='ELIGIBLE',selected=False,
                rmse_px=r.error_px,blur_laplacian_var=float(cv2.Laplacian(gray,cv2.CV_32F).var()))
            maps={};candidates.append(row)
            if r.status!='REGISTERED':row['reason']='GEOMETRY: '+r.reason
            elif row['blur_laplacian_var']<8:row['reason']='MOTION_BLUR'
            else:
                mask=without_markers(r.valid_mask,calibration)
                small=cv2.resize(r.warped,None,fx=.25,fy=.25,interpolation=cv2.INTER_AREA)
                smask=cv2.resize(mask,small.shape[1::-1],interpolation=cv2.INTER_NEAREST)
                glow,color=glow_regions(small,smask);row['glow_regions']=int(glow);maps['suspicious_color']=color
                roi=roi_coverage(mask,calibration);row.update(roi_coverage=roi,roi_min=min(roi.values(),default=1.))
                if anchor is None:
                    anchor=small.copy();anchor_mask=smask.copy();pcb,pcb_method=pcb_region(r.warped,calibration)
                common=cv2.bitwise_and(smask,anchor_mask)
                try:
                    metrics,comparison=quality_maps(anchor,small,common);row.update(metrics);maps.update(comparison)
                    row['changed_fraction_pcb']=float(np.mean((comparison['residual']>40)[(common>0)&(cv2.resize(pcb,small.shape[1::-1],interpolation=cv2.INTER_NEAREST)>0)]))
                    if metrics['extreme_lighting'] or metrics['stable_changed_fraction']>.02 or metrics['smooth_changed_fraction']>.02:
                        row['reason']='LIGHTING_OR_MOVING_OBJECT'
                except ValueError:row['reason']='INSUFFICIENT_COMMON_BACKGROUND'
                if glow:row['reason']='POSSIBLE_LOCAL_GLOW'
                if row['reason'] in ('POSSIBLE_LOCAL_GLOW','LIGHTING_OR_MOVING_OBJECT'):unsafe.append(row['reason'])
                if row['reason']=='ELIGIBLE' and row['roi_min']<.9:row['reason']='KNOWN_LED_NOT_COVERED'
                if row['reason']=='ELIGIBLE':
                    row['score']=float(row['roi_min']*4+np.mean(mask>0)-r.error_px*.2+math.log1p(row['blur_laplacian_var'])*.03)
                    retained.append((row,r.warped,r.valid_mask))
                    retained.sort(key=lambda item:item[0]['score'],reverse=True)
                    del retained[max_frames:]
            if row['reason']!='ELIGIBLE':rejected.append(dict(frame=row['frame_index'],reason=row['reason']))
            if diagnostics_dir:save_candidate(diagnostics_dir,row,image,r,maps)
            notify(min(95,round(90*(seconds-start_s)/duration_s)),100,dict(name='OFF',state='searching',candidate=row))
        if unsafe:fail('Unsafe OFF interval: '+', '.join(sorted(set(unsafe))))
        if len(retained)<3:fail('Insufficient reliable observations')
        retained.sort(key=lambda item:item[0]['frame_index'])
        for row,frame,mask in retained:
            row['selected']=True;frames.append(frame);masks.append(mask)
            accepted.append(dict(frame_index=row['frame_index'],timestamp_ms=row['timestamp_ms'],registration=row['registration'],score=row['score']))
        minimum=max(3,math.ceil(len(frames)*.8));height,width=masks[0].shape
        counts=np.zeros((height,width),np.uint8)
        for mask in masks:counts+=(mask>0).astype(np.uint8)
        valid=np.where(counts>=minimum,255,0).astype(np.uint8)
        if np.count_nonzero(valid)<height*width*.02:fail('OFF has insufficient trustworthy overlap')
        coverage=roi_coverage(without_markers(valid,calibration),calibration)
        if any(value<.9 for value in coverage.values()):fail('Known LED ROI outside trusted OFF coverage')
        median=np.zeros_like(frames[0])
        # Only a small row tile is stacked; the video and dozens of full frames are never retained.
        for y in range(0,height,64):
            checkpoint(cancel)
            tile=np.stack([f[y:y+64] for f in frames])
            preview=np.median(tile,axis=0).astype(np.uint8)
            median[y:y+64]=masked_median_tile(tile,np.stack([mask[y:y+64]>0 for mask in masks]))
            # Untrusted pixels are retained only for display / baseline ArUco decoding.
            # In particular, do not blacken marker quiet zones at the anchor-hull edge.
            outside=valid[y:y+64]==0;median[y:y+64][outside]=preview[outside]
            notify(90+round(9*(y+len(tile[0]))/height),100,dict(name='OFF',state='median'))
        metadata=dict(status='READY',algorithm_version='0.4.2',median_method='masked_uint16_rank',candidates=candidates,video=meta,coverage=dict(known_leds=coverage,
            analysis_valid_fraction=float(np.mean(without_markers(valid,calibration)>0)),
            pcb_fraction=float(np.mean(valid[pcb>0]>0)),pcb_method=pcb_method,
            discover_unavailable_fraction=float(np.mean(without_markers(valid,calibration)[pcb>0]==0))),
            setup_ms=(time.perf_counter_ns()-started)/1e6,source='automatic_video_median',start_s=start_s,duration_s=duration_s,
            decoded_frames=decoded,retained_frames=len(frames),minimum_observations=minimum,
            retained_image_bytes=sum(f.nbytes+m.nbytes for f,m in zip(frames,masks)),
            accepted=accepted,rejected=rejected,valid_fraction=float(np.mean(valid>0)),
            max_rmse_px=max(a['registration']['reprojection_rmse_px'] for a in accepted),
            max_error_px=max(a['registration']['max_inlier_error_px'] for a in accepted),
            marker_ids=sorted(set(k for a in accepted for k in a['registration']['inlier_ids'])),
            warning='Operator must guarantee interval OFF; absence of optical evidence is not electrical proof')
        checkpoint(cancel)
        save_diagnostics(diagnostics_dir,metadata,median,without_markers(valid,calibration),calibration)
        notify(100,100,dict(name='OFF',state='READY',diagnostics=metadata))
        return OffModel(median,valid,identity_registration(median,valid,metadata),calibration['calibration_version'],metadata,median)
    except Exception as exc:
        if cancel.is_set():
            diagnostics.update(status='CANCELLED',decoded_frames=decoded,retained_frames=len(retained))
            save_diagnostics(diagnostics_dir,diagnostics)
        elif not isinstance(exc,OffBuildError):
            diagnostics.update(status='FAILED',failure=type(exc).__name__+': '+str(exc),decoded_frames=decoded,
                               retained_frames=len(retained))
            save_diagnostics(diagnostics_dir,diagnostics)
        raise
    finally:reader.close()


def update_off(current,candidate,guaranteed_off=False,active_light=False):
    if not guaranteed_off or active_light:raise ValueError('OFF update refused: interval must be guaranteed OFF and no confirmed light active')
    if current.calibration_version!=candidate.calibration_version:raise ValueError('Different calibration versions')
    mask=cv2.bitwise_and(current.mask,candidate.mask)
    image=cv2.addWeighted(current.image,.5,candidate.image,.5,0)
    metadata=dict(candidate.metadata,source='validated_off_update',previous_source=current.metadata['source'])
    return OffModel(image,mask,identity_registration(image,mask,metadata),current.calibration_version,metadata,image)
