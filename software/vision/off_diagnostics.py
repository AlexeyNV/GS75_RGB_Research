"""Inspectable OFF quality gates. Geometry edges and color evidence remain separate."""
from pathlib import Path
import csv
import cv2
import numpy as np
from .led_detection import lighting_difference
from .project_storage import write_image,atomic_json


class OffBuildError(ValueError):
    def __init__(self, metadata, path=None):
        self.metadata,self.path=metadata,path
        reasons={}
        for row in metadata['candidates']:
            if row['reason']!='ELIGIBLE':reasons[row['reason']]=reasons.get(row['reason'],0)+1
        failure=metadata.get('failure','')
        primary=failure if failure.startswith(('Unsafe','Known')) else (max(reasons,key=reasons.get) if reasons else failure or 'Недостаточное покрытие')
        super().__init__(f"Не удалось построить фон: принято {metadata.get('retained_frames',0)} кадров из {len(metadata['candidates'])}. "
            f"Основная причина — {primary}. Выберите другой OFF-интервал, просмотрите отклонённые кадры, "
            'проверьте резкость/ArUco. Можно явно выбрать OFF-фотографию. '
            f"[OFF needs >=3 reliable unlit frames; {metadata.get('failure','')}]" + (f' Диагностика: {path}' if path else ''))


def roi_coverage(mask, calibration, radius=40):
    output={};h,w=mask.shape
    for led in calibration['leds']:
        x,y=led['x_ref_px'],led['y_ref_px'];cx,cy=round(x),round(y)
        x0,x1=max(0,cx-radius),min(w,cx+radius+1);y0,y1=max(0,cy-radius),min(h,cy+radius+1)
        yy,xx=np.ogrid[y0:y1,x0:x1];disk=(xx-x)**2+(yy-y)**2<=radius**2
        output[led['led_id']]=min(1.,float(np.count_nonzero(disk&(mask[y0:y1,x0:x1]>0))/(np.pi*radius**2)))
    return output


def pcb_region(image, calibration):
    """Estimated dark PCB silhouette, independent of its current registration mask."""
    h,w=image.shape[:2];small=cv2.resize(image,(max(1,w//4),max(1,h//4)),interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    dark=(gray<85).astype(np.uint8)*255
    dark=cv2.morphologyEx(dark,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
    contours,_=cv2.findContours(dark,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    mask=np.zeros_like(gray);method='dark_silhouette_estimate'
    if contours:
        largest=max(contours,key=cv2.contourArea);cv2.drawContours(mask,[largest],-1,255,-1)
    points=np.array([np.mean(v,axis=0)/4 for v in calibration['markers'].values()])
    if (not .12<float(np.mean(mask>0))<.95 or any(mask[min(mask.shape[0]-1,max(0,round(y))),min(mask.shape[1]-1,max(0,round(x)))]==0 for x,y in points)):
        mask[:]=0;cv2.fillConvexPoly(mask,cv2.convexHull(np.array(list(calibration['markers'].values()),np.float32).reshape(-1,2)/4).astype(np.int32),255)
        method='marker_envelope_proxy_not_physical_outline'
    return cv2.resize(mask,(w,h),interpolation=cv2.INTER_NEAREST),method


def quality_maps(anchor, small, common):
    delta,lighting,extreme=lighting_difference(anchor,small,common)
    predicted=np.stack([anchor[:,:,ch].astype(np.float32)*p['gain']+p['offset'] for ch,p in enumerate(lighting)],axis=2)
    residual=np.abs(small.astype(np.float32)-predicted).max(axis=2)
    edges=cv2.bitwise_or(cv2.Canny(cv2.cvtColor(anchor,cv2.COLOR_BGR2GRAY),40,100),
                         cv2.Canny(cv2.cvtColor(small,cv2.COLOR_BGR2GRAY),40,100))
    edges=cv2.dilate(edges,np.ones((5,5),np.uint8))>0
    valid=common>0;stable=valid&~edges
    boundary=valid&(cv2.erode(common,np.ones((9,9),np.uint8))==0)
    smooth=np.abs(cv2.GaussianBlur(small.astype(np.float32),(5,5),1)-cv2.GaussianBlur(predicted,(5,5),1)).max(axis=2)
    changed=(residual>40)&valid
    fraction=lambda values,region:float(np.mean(values[region])) if region.any() else 1.
    # Same >40 / 2% gates, on stable interiors AND low-frequency structures.
    metrics=dict(lighting_bgr=lighting,extreme_lighting=bool(extreme),
        changed_fraction=fraction(changed,valid),stable_changed_fraction=fraction(residual>40,stable),
        smooth_changed_fraction=fraction(smooth>40,valid),
        changed_pixels_near_edges=float(np.count_nonzero(changed&edges)/max(1,np.count_nonzero(changed))),
        edge_changed_fraction=fraction(changed,valid&edges),boundary_changed_fraction=fraction(changed,boundary),
        stable_fraction=float(stable.sum()/max(1,valid.sum())))
    return metrics,dict(before=np.abs(small.astype(np.float32)-anchor).max(axis=2),
        residual=residual,smooth_residual=smooth,changed=changed.astype(np.uint8)*255,
        common=common,edges=edges.astype(np.uint8)*255,stable=stable.astype(np.uint8)*255,delta=delta)


def glow_regions(small, mask):
    values=small.astype(np.int16);maximum=values.max(axis=2);minimum=values.min(axis=2)
    colored=((maximum-minimum>70)&(maximum>160)&(mask>0)).astype(np.uint8)
    n,_,stats,_=cv2.connectedComponentsWithStats(colored)
    return sum(stats[i,4]>=3 for i in range(1,n)),colored*255


def masked_median_tile(observed, masks):
    """Exact uint8 median over valid observations, without per-pixel all-NaN warnings."""
    count=np.sum(masks,axis=0,dtype=np.uint16)
    ranked=np.sort(np.where(masks[:,:,:,None],observed.astype(np.uint16),256),axis=0)
    low=np.maximum(count.astype(np.int16)-1,0)//2;high=count//2
    index=lambda value:np.broadcast_to(value[None,:,:,None],(1,*value.shape,3))
    lower=np.take_along_axis(ranked,index(low),axis=0)[0]
    upper=np.take_along_axis(ranked,index(high),axis=0)[0]
    result=((lower+upper)//2).astype(np.uint8)
    result[count==0]=0
    return result


def save_candidate(path, row, image, registration, maps):
    path=Path(path);group='accepted_frames' if row['reason']=='ELIGIBLE' else 'rejected_frames'
    stem=f"frame_{row['frame_index']:04d}"
    write_image(path/group/(stem+'.jpg'),image)
    directory=path/'registration_diagnostics'/stem
    draw=image.copy()
    for key,corners in registration.detected.items():
        p=np.asarray(corners,np.int32);cv2.polylines(draw,[p],True,(0,220,255),2)
        cv2.putText(draw,key,tuple(p[0]),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,220,255),2)
    write_image(directory/'markers.jpg',draw)
    if registration.warped is not None:
        write_image(directory/'warped.jpg',registration.warped);write_image(directory/'valid_mask.png',registration.valid_mask)
    for name,array in maps.items():
        if name in ('before','residual','smooth_residual'):
            array=cv2.applyColorMap(np.clip(array*3,0,255).astype(np.uint8),cv2.COLORMAP_TURBO)
        write_image(path/'residual_heatmaps'/stem/(name+'.png'),array)
    atomic_json(directory/'diagnostics.json',row)


def save_diagnostics(path, metadata, image=None, mask=None, calibration=None):
    if path is None:return
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    atomic_json(path/'off_diagnostics.json',metadata)
    names=['frame_index','timestamp_ms','reason','selected','score','blur_laplacian_var','changed_fraction',
           'stable_changed_fraction','smooth_changed_fraction','changed_pixels_near_edges','edge_changed_fraction',
           'boundary_changed_fraction','glow_regions','roi_min','rmse_px']
    with (path/'off_candidates.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=names,extrasaction='ignore');writer.writeheader();writer.writerows(metadata['candidates'])
    if image is not None:
        display=cv2.resize(image,(1000,round(image.shape[0]*1000/image.shape[1])))
        coverage=cv2.resize(mask,display.shape[1::-1],interpolation=cv2.INTER_NEAREST)>0
        display[~coverage]=(display[~coverage]*.3+np.array([0,0,110])).astype(np.uint8)
        write_image(path/'off_coverage.png',display)
        write_image(path/'discover_unavailable.png',255-mask)
        for led in calibration['leds']:
            x,y=round(led['x_ref_px']),round(led['y_ref_px'])
            write_image(path/(led['led_id'].lower()+'_coverage.png'),mask[max(0,y-80):y+81,max(0,x-80):x+81])
