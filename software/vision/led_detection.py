"""Photo-only pipeline. No STM32, serial ports, video or LED/key inference."""
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
import csv
import cv2
import numpy as np
from .calibration import validate
from .image_registration import register
from .color_detection import classify
from .project_storage import read_image,write_image,atomic_json


@dataclass
class Analysis:
    result: dict
    images: dict


def lighting_difference(off,on,mask):
    # Deterministic subsampling; no full-size float RGB copies for 48 MP images.
    stride=max(1,int(np.sqrt(off.shape[0]*off.shape[1]/50000)))
    sampled=mask[::stride,::stride]>0
    a=off[::stride,::stride][sampled].astype(float); b=on[::stride,::stride][sampled].astype(float)
    if len(a)<100: raise ValueError('Insufficient common background for lighting compensation')
    delta=np.empty_like(on); parameters=[]; extreme=False
    for channel in range(3):
        x,y=a[:,channel],b[:,channel]
        gain=1.; offset=float(np.median(y-x))
        for _ in range(3):
            residual=np.abs(y-(gain*x+offset)); keep=residual<=np.quantile(residual,.9)+.5
            if np.std(x[keep])>=5:
                gain,offset=np.linalg.lstsq(np.c_[x[keep],np.ones(keep.sum())],y[keep],rcond=None)[0]
            else: gain,offset=1.,float(np.median(y[keep]-x[keep]))
        if not .7<=gain<=1.3 or abs(offset)>35: extreme=True
        parameters.append(dict(gain=float(gain),offset=float(offset)))
        corrected=off[:,:,channel].astype(np.float32)*gain+offset
        delta[:,:,channel]=np.clip(on[:,:,channel].astype(np.float32)-corrected,0,255).astype(np.uint8)
    return delta,parameters,extreme


def analyze(calibration,off,on,experiment_id='',threshold=30,match_radius=20,min_area=6):
    validate(calibration)
    if not 1<=threshold<=255 or not 1<=match_radius<=1000 or not 1<=min_area<=100000:
        raise ValueError('Invalid detection threshold, radius or area')
    off_registration=register(off,calibration); on_registration=register(on,calibration)
    images={'Original OFF':off,'Original ON':on}
    on_markers=on.copy()
    for key,corners in on_registration.detected.items():
        points=np.asarray(corners,np.int32); cv2.polylines(on_markers,[points],True,(0,220,255),2)
        cv2.putText(on_markers,f'ID {key}',tuple(points[0]),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,220,255),2)
    images['ON markers']=on_markers
    status='FAILED' if 'FAILED' in [off_registration.status,on_registration.status] else ('DEGRADED' if 'DEGRADED' in [off_registration.status,on_registration.status] else 'REGISTERED')
    result=dict(schema_version=1,calibration_version=calibration['calibration_version'],
                experiment_id=experiment_id,analyzed_utc=datetime.now(timezone.utc).isoformat(),
                coordinate_system=calibration['coordinate_system'],registration_status=status,
                analysis_status='FAILED' if status=='FAILED' else 'ANALYZED',
                registrations=dict(off=off_registration.summary(),on=on_registration.summary()),
                parameters=dict(threshold=threshold,match_radius_px=match_radius,min_area_px=min_area),
                detections=[],warnings=[])
    if status=='FAILED':
        result['warnings'].append('Registration failed; no LED identities or light results produced')
        return Analysis(result,images)
    off_warped,on_warped=off_registration.warped,on_registration.warped
    images.update({'Registered OFF':off_warped,'Registered ON':on_warped})
    common=cv2.bitwise_and(off_registration.valid_mask,on_registration.valid_mask)
    # Remove marker code AND quiet zone; highlights on stickers are not LED observations.
    for corners in calibration['markers'].values():
        points=np.asarray(corners,float); expanded=points.mean(axis=0)+(points-points.mean(axis=0))*1.55
        cv2.fillConvexPoly(common,expanded.astype(np.int32),0)
    background=common.copy()
    for led in calibration['leds']:
        cv2.circle(background,(round(led['x_ref_px']),round(led['y_ref_px'])),round(match_radius*1.5),0,-1)
    try: delta,lighting,extreme=lighting_difference(off_warped,on_warped,background)
    except ValueError as exc:
        result['analysis_status']='FAILED'; result['warnings'].append(str(exc)); return Analysis(result,images)
    result['lighting_bgr']=lighting
    if extreme:
        result['analysis_status']='FAILED'
        result['warnings'].append('Lighting change exceeds supported small affine compensation; analysis refused')
        return Analysis(result,images)
    strength=delta.max(axis=2)
    samples=strength[background>0]
    adaptive=max(float(threshold),float(np.quantile(samples,.995))+10)
    binary=np.where((strength>adaptive)&(common>0),255,0).astype(np.uint8)
    binary=cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    result['effective_threshold']=adaptive
    count,labels,stats,centroids=cv2.connectedComponentsWithStats(binary,connectivity=8)
    overlay=on_warped.copy()
    for key,corners in calibration['markers'].items():
        cv2.polylines(overlay,[np.asarray(corners,np.int32)],True,(0,200,255),1)
    for index in range(1,count):
        x,y,w,h,area=map(int,stats[index])
        if area<min_area: continue
        local=labels[y:y+h,x:x+w]==index
        weights=strength[y:y+h,x:x+w][local].astype(float)
        ys,xs=np.nonzero(local); total=weights.sum()
        px=float(x+np.dot(xs,weights)/total); py=float(y+np.dot(ys,weights)/total)
        distances=sorted([(float(np.hypot(px-led['x_ref_px'],py-led['y_ref_px'])),led) for led in calibration['leds']],key=lambda v:v[0])
        matched=distances[0][1] if distances and distances[0][0]<=match_radius else None
        flags=['DEGRADED_REGISTRATION'] if status=='DEGRADED' else []
        candidates=[led['led_id'] for distance,led in distances if distance<=match_radius]
        if len(distances)>1 and distances[1][0]<=match_radius and distances[1][0]-distances[0][0]<max(3,match_radius*.2):
            matched=None; flags.append('AMBIGUOUS_LED_MATCH')
        if not matched: flags.append('UNKNOWN_LED_ADD_TO_CALIBRATION')
        if area>on_warped.shape[0]*on_warped.shape[1]*.02: flags.append('LARGE_REGION_POSSIBLE_REFLECTION')
        color,color_flags,rgb=classify(delta[y:y+h,x:x+w][local],on_warped[y:y+h,x:x+w][local]); flags+=color_flags
        record=dict(led_id=matched['led_id'] if matched else None,key_name=matched['key_name'] if matched else None,
                    x_ref_px=px,y_ref_px=py,color=color,mean_rgb_delta=rgb,brightness=float(weights.mean()),
                    area_px=area,registration_status=status,
                    reprojection_error_px=max(off_registration.error_px,on_registration.error_px),
                    ambiguity_flags=flags,candidate_led_ids=candidates,
                    calibration_version=calibration['calibration_version'],experiment_id=experiment_id,
                    analyzed_utc=result['analyzed_utc'])
        result['detections'].append(record)
        cv2.circle(overlay,(round(px),round(py)),round(match_radius),(255,0,255),2)
        cv2.putText(overlay,f"{record['led_id'] or 'UNKNOWN'} {color}",(round(px)+8,round(py)-8),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,0,255),2)
    assigned=[r['led_id'] for r in result['detections'] if r['led_id']]
    for record in result['detections']:
        if record['led_id'] and assigned.count(record['led_id'])>1:
            record['ambiguity_flags'].append('MULTIPLE_REGIONS_SAME_LED')
    result['visible_led_ids']=[led['led_id'] for led in calibration['leds'] if common[min(common.shape[0]-1,round(led['y_ref_px'])),min(common.shape[1]-1,round(led['x_ref_px']))]>0]
    result['warnings'].append('Optical candidates require manual review; reflections can resemble light')
    images.update({'Difference':delta,'Valid overlap':common,'Detected LEDs':overlay})
    return Analysis(result,images)


def analyze_paths(calibration,off_path,on_path,experiment_id='',**options):
    off=read_image(off_path,calibration.get('camera_model')); on=read_image(on_path,calibration.get('camera_model'))
    analysis=analyze(calibration,off,on,experiment_id,**options)
    analysis.result.update(image_off=Path(off_path).name,image_on=Path(on_path).name)
    for record in analysis.result['detections']:
        record.update(image_off=Path(off_path).name,image_on=Path(on_path).name)
    return analysis


def export(analysis,output,overwrite=False):
    output=Path(output)
    if output.exists() and any(output.iterdir()) and not overwrite: raise FileExistsError('Output directory not empty; use a new path or --overwrite')
    output.mkdir(parents=True,exist_ok=True)
    atomic_json(output/'results.json',analysis.result)
    columns=['image_on','image_off','experiment_id','analyzed_utc','led_id','key_name','x_ref_px','y_ref_px','color',
             'brightness','area_px','registration_status','reprojection_error_px','ambiguity_flags','calibration_version']
    with (output/'results.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns); writer.writeheader()
        for detection in analysis.result['detections']:
            row={key:detection.get(key) for key in columns}; row['ambiguity_flags']=';'.join(detection['ambiguity_flags']); writer.writerow(row)
    names={'ON markers':'on_markers.png','Registered OFF':'registered_off.png','Registered ON':'registered_on.png',
           'Difference':'difference.png','Valid overlap':'valid_overlap.png','Detected LEDs':'annotated.png'}
    for key,name in names.items():
        if key in analysis.images: write_image(output/name,analysis.images[key])
        elif overwrite: (output/name).unlink(missing_ok=True)
