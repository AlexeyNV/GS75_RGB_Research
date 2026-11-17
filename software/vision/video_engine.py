"""Four comparable video paths, cached OFF and high-resolution local refinement."""
from copy import deepcopy
import cv2
import numpy as np
from .aruco_markers import detect
from .frame_profile import timed
from .image_registration import register,transform_points
from .led_detection import analyze,lighting_difference
from .off_background import without_markers
from .optical_signal import evaluate,signal_maps


@timed('ARUCO_DETECT')
def hybrid_markers(image,calibration,max_side=1280):
    factor=min(1.,max_side/max(image.shape[:2]))
    if factor==1:return detect(image),False
    small=cv2.resize(image,None,fx=factor,fy=factor,interpolation=cv2.INTER_AREA)
    points=detect(small)
    points={k:(np.asarray(v)/factor).tolist() for k,v in points.items()}
    if len(set(points)&set(calibration['markers']))<3:return detect(image),True
    # Refine in original pixel coordinates before the homography fit.
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    for key,corners in points.items():
        a=np.asarray(corners,np.float32).reshape(-1,1,2)
        cv2.cornerSubPix(gray,a,(5,5),(-1,-1),(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,30,.01))
        points[key]=a.reshape(4,2).tolist()
    return points,False


@timed('IMAGE_RECTIFICATION')
def warp_valid(image,r,width,height,transform=None):
    matrix=r.matrix if transform is None else transform@r.matrix
    warped=cv2.warpPerspective(image,matrix,(width,height),flags=cv2.INTER_LINEAR)
    mask=cv2.warpPerspective(np.full(image.shape[:2],255,np.uint8),matrix,(width,height),flags=cv2.INTER_NEAREST)
    mask=cv2.erode(mask,np.ones((5,5),np.uint8))
    hull=np.asarray(r.anchor_hull,np.float32).reshape(-1,2)
    if transform is not None:hull=transform_points(hull,transform)
    anchor=np.zeros((height,width),np.uint8);cv2.fillConvexPoly(anchor,hull.astype(np.int32),255)
    return warped,cv2.bitwise_and(mask,anchor)


class VideoEngine:
    VARIANTS=('A_BASELINE','A_CACHED','B_CACHED_FULL','C_HYBRID')
    def __init__(self,calibration,off,variant='C_HYBRID',mode='KNOWN_LEDS',detect_side=1280):
        if variant not in self.VARIANTS:raise ValueError('Unknown benchmark architecture')
        if calibration.get('camera_model'):
            raise ValueError('Video benchmark currently requires camera_model=null; video-specific intrinsics are not validated')
        if mode=='KNOWN_LEDS' and not calibration['leds']:raise ValueError('KNOWN_LEDS benchmark requires a marked LED map')
        if calibration['calibration_version']!=off.calibration_version:raise ValueError('OFF calibration changed')
        self.calibration=deepcopy(calibration);self.off=off;self.variant=variant;self.mode=mode;self.detect_side=detect_side
        w,h=off.image.shape[1],off.image.shape[0];self.scale=min(1.,640/max(w,h))
        self.size=(round(w*self.scale),round(h*self.scale))
        self.S=np.diag([self.scale,self.scale,1.])
        self.coarse_off=cv2.resize(off.image,self.size,interpolation=cv2.INTER_AREA)
        self.full_mask=without_markers(off.mask,calibration)
        self.coarse_mask=cv2.resize(self.full_mask,self.size,interpolation=cv2.INTER_NEAREST)
        self.coarse_background=self.coarse_mask.copy()
        for led in calibration['leds']:
            cv2.circle(self.coarse_background,(round(led['x_ref_px']*self.scale),round(led['y_ref_px']*self.scale)),max(3,round(60*self.scale)),0,-1)

    def process(self,image):
        if self.variant!='C_HYBRID':
            a=analyze(self.calibration,self.off.original if self.off.original is not None else self.off.image,image,
                mode=self.mode,prepared_off=None if self.variant=='A_BASELINE' else self.off.registration,
                diagnostics=self.variant in ('A_BASELINE','A_CACHED'),trusted_off_mask=self.off.mask)
            if a.result['registration_status']=='DEGRADED':
                a.result.update(analysis_status='FAILED',known_leds=[],detections=[])
                a.result['warnings'].append('Two-marker geometry needs manual review')
            return dict(registration_status=a.result['registration_status'],registrations=a.result['registrations'],
                records=a.result['known_leds'] if self.mode=='KNOWN_LEDS' else a.result['detections'],
                analysis_status=a.result['analysis_status'],fallback=False,
                warnings=a.result['warnings'])
        return self.hybrid(image)

    def hybrid(self,image,force_full=False):
        detected,fallback=(detect(image),True) if force_full else hybrid_markers(image,self.calibration,self.detect_side)
        r=register(image,self.calibration,detected=detected,rectify=False)
        if r.status=='FAILED' and not fallback:
            # A failed reduced search must never become an invented confident result.
            detected=detect(image);fallback=True;r=register(image,self.calibration,detected=detected,rectify=False)
        result=dict(registration_status=r.status,registrations={'on':r.summary()},records=[],
                    analysis_status='FAILED' if r.status=='FAILED' else 'ANALYZED',fallback=fallback,warnings=[])
        if r.status=='FAILED':return result
        if r.status=='DEGRADED':
            result.update(analysis_status='FAILED',warnings=['Two-marker geometry needs review; no confirmed video observation'])
            return result
        coarse,mask=warp_valid(image,r,*self.size,self.S)
        common=cv2.bitwise_and(mask,self.coarse_mask)
        background=cv2.bitwise_and(common,self.coarse_background)
        try:delta,parameters,extreme=lighting_difference(self.coarse_off,coarse,background,max_samples=10000)
        except ValueError as exc:result.update(analysis_status='FAILED',warnings=[str(exc)]);return result
        if extreme:result.update(analysis_status='FAILED',warnings=['Extreme lighting']);return result
        result['lighting_bgr']=parameters
        if self.mode=='KNOWN_LEDS':
            for led in self.calibration['leds']:
                record=self.refine(image,r,led,parameters)
                # Preserve uncertainty for spatially ambiguous maps.
                if record['status']=='ON' and any(other['led_id']!=led['led_id'] and np.hypot(other['x_ref_px']-led['x_ref_px'],other['y_ref_px']-led['y_ref_px'])<80 for other in self.calibration['leds']):
                    record.update(status='UNCERTAIN',color='UNDEFINED');record['rejection_reasons'].append('OVERLAPPING_LED_ROIS')
                result['records'].append(record)
            if not fallback and any('ROI_NOT_GEOMETRICALLY_COVERED' in r['rejection_reasons'] for r in result['records']):
                return self.hybrid(image,force_full=True)
        else:
            # Coarse discovery proposes positions only; color and status are refined at full resolution.
            proposals=self.discover_proposals(coarse,delta,common)
            for px,py in proposals:
                pseudo=dict(led_id='CANDIDATE',key_name=None,x_ref_px=px,y_ref_px=py)
                record=self.refine(image,r,pseudo,parameters);record['led_id']=None
                if record['status']=='ON':record['status']='CANDIDATE';result['records'].append(record)
            result['warnings'].append('DISCOVER coarse proposal can miss tiny emitters; quality must be compared with B')
        return result

    @timed('LED_DETECTION')
    def discover_proposals(self,on,delta,mask):
        _,signal,color,_=signal_maps(self.coarse_off,on,delta,mask,20,20)
        count,_,stats,centers=cv2.connectedComponentsWithStats(color)
        return [(float(centers[i,0]/self.scale),float(centers[i,1]/self.scale)) for i in range(1,count) if stats[i,4]>=2]

    def refine(self,image,r,led,parameters):
        radius=40;pad=46;w,h=self.off.image.shape[1],self.off.image.shape[0]
        x0=max(0,round(led['x_ref_px'])-pad);y0=max(0,round(led['y_ref_px'])-pad)
        x1=min(w,round(led['x_ref_px'])+pad+1);y1=min(h,round(led['y_ref_px'])+pad+1)
        T=np.array([[1.,0,-x0],[0,1.,-y0],[0,0,1.]])
        on,mask=warp_valid(image,r,x1-x0,y1-y0,T)
        common=cv2.bitwise_and(mask,self.full_mask[y0:y1,x0:x1])
        off=self.off.image[y0:y1,x0:x1]
        delta=self.local_compensation(off,on,parameters)
        local=deepcopy(led);local['x_ref_px']-=x0;local['y_ref_px']-=y0
        data=dict(leds=[local],markers={})
        known,_,_,_,_=evaluate(data,off,on,delta,common,'KNOWN_LEDS',30,25,radius,6,
            diagnostics=False,find_candidates=False)
        record=known[0];record['x_ref_px']+=x0;record['y_ref_px']+=y0
        if 'signal_x_ref_px' in record:record['signal_x_ref_px']+=x0;record['signal_y_ref_px']+=y0
        record['registration_status']=r.status
        if r.status=='DEGRADED':record['ambiguity_flags'].append('DEGRADED_REGISTRATION')
        return record

    @staticmethod
    @timed('BACKGROUND_COMPENSATION')
    def local_compensation(off,on,parameters):
        out=np.empty_like(on)
        for ch,p in enumerate(parameters):
            out[:,:,ch]=np.clip(on[:,:,ch].astype(np.float32)-(off[:,:,ch].astype(np.float32)*p['gain']+p['offset']),0,255).astype(np.uint8)
        return out


class EventAggregator:
    """Confirmation needs consecutive valid observations; geometry loss closes events."""
    def __init__(self,minimum_frames=2):self.minimum=minimum_frames;self.active={};self.closed=[]
    @timed('EVENT_AGGREGATION')
    def feed(self,result,timestamp_ms,frame_index):
        keys={}
        if result['registration_status']=='REGISTERED' and result['analysis_status']=='ANALYZED':
            for record in result['records']:
                if record.get('led_id') and record['status']=='ON' and record['color']!='UNDEFINED':
                    keys[(record['led_id'],record['color'])]=record
        for key in list(self.active):
            if key not in keys:self.closed.append(self.active.pop(key))
        for key in keys:
            event=self.active.setdefault(key,dict(led_id=key[0],color=key[1],start_ms=timestamp_ms,end_ms=timestamp_ms,
                start_frame=frame_index,end_frame=frame_index,frames=0,confirmed=False))
            event.update(end_ms=timestamp_ms,end_frame=frame_index,frames=event['frames']+1)
            event['confirmed']=event['frames']>=self.minimum
    def events(self):return self.closed+list(self.active.values())
