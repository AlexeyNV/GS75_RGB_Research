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
        atomic_json(path/'off_model.json',dict(calibration_version=self.calibration_version,**self.metadata))


def from_photo(image,calibration):
    r=register(image,calibration)
    if r.status=='FAILED':raise ValueError('OFF registration failed: '+r.reason)
    return OffModel(r.warped,r.valid_mask,r,calibration['calibration_version'],dict(source='explicit_photo'),image)


def identity_registration(image,mask,metadata):
    return Registration(status='REGISTERED',reason='Validated multi-frame OFF model',
        error_px=metadata.get('max_rmse_px',0.),max_error_px=metadata.get('max_error_px',0.),
        inlier_ids=metadata.get('marker_ids',[]),common_ids=metadata.get('marker_ids',[]),
        matrix=np.eye(3),warped=image,valid_mask=mask)


def build_off(video,calibration,cancel,start_s=0.,duration_s=2.,max_frames=5,notify=lambda *args:None):
    """Decode every interval frame, retain <=5 registered observations, median in row tiles."""
    if not math.isfinite(start_s+duration_s) or start_s<0 or duration_s<=0 or not 3<=max_frames<=9:
        raise ValueError('Invalid OFF interval or frame bound')
    if calibration.get('camera_model'):raise ValueError('Video-specific camera intrinsics are not yet validated; camera_model must be null')
    reader=SequentialVideoReader();frames=[];masks=[];accepted=[];rejected=[]
    # Quality is relative to other registered video observations; no reference photo is copied as OFF.
    try:
        meta=reader.open(video)
        end_s=start_s+duration_s
        next_time=start_s;period=duration_s/max(1,max_frames-1);index=0;decoded=0
        while len(frames)<max_frames:
            checkpoint(cancel)
            if reader.count and index>=reader.count:break
            try:image,info=reader.frame(index)
            except StopIteration:break
            decoded+=1;index=info['frame_index']+1
            seconds=(info['timestamp_ms'] if info['timestamp_ms'] is not None else info['estimated_ms'])
            if seconds is None:raise ValueError('No usable timestamp for OFF interval')
            seconds/=1000
            if seconds>=end_s-1e-6:break
            if seconds+1e-6<next_time:continue
            next_time+=period
            r=register(image,calibration)
            if r.status!='REGISTERED':
                rejected.append(dict(frame=info['frame_index'],reason='GEOMETRY: '+r.reason));continue
            mask=without_markers(r.valid_mask,calibration)
            # Reject local strongly chromatic compact peaks. This is conservative evidence,
            # not a proof that a dark/broken LED is electrically off.
            small=cv2.resize(r.warped,None,fx=.25,fy=.25,interpolation=cv2.INTER_AREA)
            smask=cv2.resize(mask,(small.shape[1],small.shape[0]),interpolation=cv2.INTER_NEAREST)
            values=small.astype(np.int16);maximum=values.max(axis=2);minimum=values.min(axis=2)
            colored=((maximum-minimum>70)&(maximum>160)&(smask>0)).astype(np.uint8)
            n,_,stats,_=cv2.connectedComponentsWithStats(colored)
            if any(stats[i,4]>=3 for i in range(1,n)):
                rejected.append(dict(frame=info['frame_index'],reason='POSSIBLE_LOCAL_GLOW'));continue
            if frames:
                common=cv2.bitwise_and(mask,masks[0]);sample=cv2.resize(common,(small.shape[1],small.shape[0]),interpolation=cv2.INTER_NEAREST)
                anchor=cv2.resize(frames[0],(small.shape[1],small.shape[0]),interpolation=cv2.INTER_AREA)
                try:delta,lighting,extreme=lighting_difference(anchor,small,sample)
                except ValueError:
                    rejected.append(dict(frame=info['frame_index'],reason='INSUFFICIENT_COMMON_BACKGROUND'));continue
                predicted=np.empty_like(anchor,dtype=np.float32)
                for ch,p in enumerate(lighting):predicted[:,:,ch]=anchor[:,:,ch].astype(np.float32)*p['gain']+p['offset']
                residual=np.abs(small.astype(np.float32)-predicted).max(axis=2)[sample>0]
                changed=float(np.mean(residual>40)) if len(residual) else 1.
                if extreme or changed>.02:
                    rejected.append(dict(frame=info['frame_index'],reason='LIGHTING_OR_MOVING_OBJECT',changed_fraction=changed));continue
            # Retain observed marker pixels in the median for honest A_BASELINE
            # re-registration; analysis masks remove their code and quiet zones later.
            frames.append(r.warped);masks.append(r.valid_mask);accepted.append(dict(**info,registration=r.summary()))
            notify(len(frames),max_frames,dict(name='OFF',state='accepted'))
        if len(frames)<3:
            raise ValueError('Automatic OFF needs >=3 reliable unlit frames. Choose another interval. '+str(rejected))
        minimum=max(3,math.ceil(len(frames)*.8));height,width=masks[0].shape
        counts=np.zeros((height,width),np.uint8)
        for mask in masks:counts+=(mask>0).astype(np.uint8)
        valid=np.where(counts>=minimum,255,0).astype(np.uint8)
        if np.count_nonzero(valid)<height*width*.02:raise ValueError('OFF has insufficient trustworthy overlap')
        median=np.zeros_like(frames[0])
        # Only a small row tile is stacked; the video and dozens of full frames are never retained.
        import warnings
        for y in range(0,height,64):
            checkpoint(cancel)
            tile=np.stack([f[y:y+64].astype(np.float32) for f in frames])
            preview=np.median(tile,axis=0).astype(np.uint8)
            for i,mask in enumerate(masks):tile[i][mask[y:y+64]==0]=np.nan
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning)
                median[y:y+64]=np.nan_to_num(np.nanmedian(tile,axis=0)).astype(np.uint8)
            # Untrusted pixels are retained only for display / baseline ArUco decoding.
            # In particular, do not blacken marker quiet zones at the anchor-hull edge.
            outside=valid[y:y+64]==0;median[y:y+64][outside]=preview[outside]
        metadata=dict(source='automatic_video_median',start_s=start_s,duration_s=duration_s,
            decoded_frames=decoded,retained_frames=len(frames),minimum_observations=minimum,
            retained_image_bytes=sum(f.nbytes+m.nbytes for f,m in zip(frames,masks)),
            accepted=accepted,rejected=rejected,valid_fraction=float(np.mean(valid>0)),
            max_rmse_px=max(a['registration']['reprojection_rmse_px'] for a in accepted),
            max_error_px=max(a['registration']['max_inlier_error_px'] for a in accepted),
            marker_ids=sorted(set(k for a in accepted for k in a['registration']['inlier_ids'])),
            warning='Operator must guarantee interval OFF; absence of optical evidence is not electrical proof')
        return OffModel(median,valid,identity_registration(median,valid,metadata),calibration['calibration_version'],metadata,median)
    finally:reader.close()


def update_off(current,candidate,guaranteed_off=False,active_light=False):
    if not guaranteed_off or active_light:raise ValueError('OFF update refused: interval must be guaranteed OFF and no confirmed light active')
    if current.calibration_version!=candidate.calibration_version:raise ValueError('Different calibration versions')
    mask=cv2.bitwise_and(current.mask,candidate.mask)
    image=cv2.addWeighted(current.image,.5,candidate.image,.5,0)
    metadata=dict(candidate.metadata,source='validated_off_update',previous_source=current.metadata['source'])
    return OffModel(image,mask,identity_registration(image,mask,metadata),current.calibration_version,metadata,image)
