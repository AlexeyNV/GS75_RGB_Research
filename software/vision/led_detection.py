"""Photo-only pipeline. No STM32, serial ports, video or LED/key inference."""
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
import csv
import cv2
import numpy as np
from .calibration import validate
from .image_registration import register,transform_points
from .optical_signal import evaluate
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


def analyze(calibration,off,on,experiment_id='',threshold=30,match_radius=20,min_area=6,mode='KNOWN_LEDS',roi_radius=40,color_threshold=25):
    validate(calibration)
    if not 1<=threshold<=255 or not 1<=match_radius<=1000 or not 1<=min_area<=100000:
        raise ValueError('Invalid detection threshold, radius or area')
    if mode not in ('KNOWN_LEDS','DISCOVER') or not 5<=roi_radius<=500 or not 1<=color_threshold<=255:
        raise ValueError('Invalid mode, ROI radius or color threshold')
    off_registration=register(off,calibration); on_registration=register(on,calibration)
    images={'Original OFF':off,'Original ON':on}
    on_markers=on.copy()
    for key,corners in on_registration.detected.items():
        points=np.asarray(corners,np.int32); cv2.polylines(on_markers,[points],True,(0,220,255),2)
        cv2.putText(on_markers,f'ID {key}',tuple(points[0]),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,220,255),2)
    images['ON markers']=on_markers
    status='FAILED' if 'FAILED' in [off_registration.status,on_registration.status] else ('DEGRADED' if 'DEGRADED' in [off_registration.status,on_registration.status] else 'REGISTERED')
    result=dict(schema_version=2,calibration_version=calibration['calibration_version'],
                experiment_id=experiment_id,analyzed_utc=datetime.now(timezone.utc).isoformat(),
                coordinate_system=calibration['coordinate_system'],registration_status=status,
                analysis_status='FAILED' if status=='FAILED' else 'ANALYZED',
                registrations=dict(off=off_registration.summary(),on=on_registration.summary()),
                parameters=dict(threshold=threshold,match_radius_px=match_radius,min_area_px=min_area,
                                mode=mode,roi_radius_px=roi_radius,color_threshold=color_threshold),
                detections=[],candidates=[],known_leds=[],warnings=[])
    result['known_leds']=[dict(led_id=led['led_id'],key_name=led['key_name'],
        x_ref_px=led['x_ref_px'],y_ref_px=led['y_ref_px'],status='UNCERTAIN',color='UNDEFINED',
        brightness=0.,chroma=0.,area_px=0,ambiguity_flags=[],rejection_reasons=['ANALYSIS_UNAVAILABLE']) for led in calibration['leds']]
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
        cv2.circle(background,(round(led['x_ref_px']),round(led['y_ref_px'])),round(roi_radius*1.5),0,-1)
    try: delta,lighting,extreme=lighting_difference(off_warped,on_warped,background)
    except ValueError as exc:
        result['analysis_status']='FAILED'; result['warnings'].append(str(exc)); return Analysis(result,images)
    result['lighting_bgr']=lighting
    if extreme:
        result['analysis_status']='FAILED'
        result['warnings'].append('Lighting change exceeds supported small affine compensation; analysis refused')
        return Analysis(result,images)
    known,candidates,detections,diagnostics,strength=evaluate(
        calibration,off_warped,on_warped,delta,common,mode,threshold,color_threshold,roi_radius,min_area)
    result.update(known_leds=known,candidates=candidates,detections=detections,
                  effective_threshold=threshold,
                  legacy_global_threshold=max(float(threshold),float(np.quantile(strength[background>0],.995))+10))
    for records in (known,candidates):
        for record in records:
            record.update(registration_status=status,reprojection_error_px=max(off_registration.error_px,on_registration.error_px),
                          calibration_version=calibration['calibration_version'],experiment_id=experiment_id,analyzed_utc=result['analyzed_utc'])
            if status=='DEGRADED': record['ambiguity_flags'].append('DEGRADED_REGISTRATION')
    result['visible_led_ids']=[r['led_id'] for r in known if r['roi_coverage']>=.9]
    original=on.copy()
    for record in known if mode=='KNOWN_LEDS' else detections:
        p=np.array([[record['x_ref_px'],record['y_ref_px']]],float)
        native=transform_points(p,np.linalg.inv(on_registration.matrix))[0]
        record['x_on_px'],record['y_on_px']=map(float,native)
        native_off=transform_points(p,np.linalg.inv(off_registration.matrix))[0]
        record['x_off_px'],record['y_off_px']=map(float,native_off)
        circle=np.array([[p[0,0]+roi_radius*np.cos(t),p[0,1]+roi_radius*np.sin(t)] for t in np.linspace(0,2*np.pi,60)])
        projected=transform_points(circle,np.linalg.inv(on_registration.matrix)).astype(np.int32)
        cv2.polylines(original,[projected],True,(255,0,255),2)
        cv2.putText(original,f"{record['led_id'] or 'CANDIDATE'} {record['status']} {record['color']}",tuple(native.astype(int)),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,0,255),2)
    result['warnings'].append('Optical evidence requires manual review; colored reflections can resemble emitted light')
    images.update({'Difference':delta,'Valid overlap':common,'Original ON annotated':original,**diagnostics})
    return Analysis(result,images)


def analyze_paths(calibration,off_path,on_path,experiment_id='',**options):
    off=read_image(off_path,calibration.get('camera_model')); on=read_image(on_path,calibration.get('camera_model'))
    analysis=analyze(calibration,off,on,experiment_id,**options)
    analysis.result.update(image_off=Path(off_path).name,image_on=Path(on_path).name)
    for record in analysis.result['known_leds']+analysis.result['candidates']:
        record.update(image_off=Path(off_path).name,image_on=Path(on_path).name)
    return analysis


def export(analysis,output,overwrite=False):
    output=Path(output)
    if output.exists() and any(output.iterdir()) and not overwrite: raise FileExistsError('Output directory not empty; use a new path or --overwrite')
    output.mkdir(parents=True,exist_ok=True)
    atomic_json(output/'results.json',analysis.result)
    columns=['image_on','image_off','experiment_id','analyzed_utc','led_id','key_name','x_ref_px','y_ref_px','color',
             'status','brightness','chroma','area_px','rejection_reasons','registration_status','reprojection_error_px','ambiguity_flags','calibration_version']
    with (output/'results.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns); writer.writeheader()
        records=analysis.result['known_leds'] if analysis.result['parameters']['mode']=='KNOWN_LEDS' else analysis.result['candidates']
        for detection in records:
            row={key:detection.get(key) for key in columns}; row['ambiguity_flags']=';'.join(detection['ambiguity_flags']); row['rejection_reasons']=';'.join(detection.get('rejection_reasons',[])); writer.writerow(row)
    names={'ON markers':'on_markers.png','Registered OFF':'registered_off.png','Registered ON':'registered_on.png',
           'Difference':'difference.png','Valid overlap':'valid_overlap.png','Detected LEDs':'annotated.png',
           'Original ON annotated':'original_on_annotated.png','Color mask':'color_mask.png',
           'Color signal':'color_signal.png','Candidates':'candidates.png','Accepted':'accepted.png',
           'Rejected':'rejected_candidates.png','LED ROIs':'led_rois.png'}
    for key,name in names.items():
        if key in analysis.images: write_image(output/name,analysis.images[key])
        elif overwrite: (output/name).unlink(missing_ok=True)
