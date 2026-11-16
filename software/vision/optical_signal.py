"""Local chromatic evidence, separate from geometric registration and LED identity."""
import cv2
import numpy as np


def chroma(image):
    image = image.astype(np.float32)
    return image - (image.sum(axis=2, keepdims=True) - image) / 2


def signal_maps(off, on, delta, common, threshold, color_threshold):
    # White lettering / neutral exposure edges have little channel excess.
    # Compare ON excess with OFF as well: a static red object is not new light.
    excess = chroma(on)
    change = excess - chroma(off)
    signal = np.maximum(0, np.minimum(excess, change)).max(axis=2)
    strength = delta.max(axis=2)
    color = ((signal >= color_threshold) & (strength >= threshold) & (common > 0)).astype(np.uint8)*255
    # Close small gaps in the halo; opening suppresses isolated chroma noise.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    color = cv2.morphologyEx(color, cv2.MORPH_CLOSE, kernel)
    color = cv2.morphologyEx(color, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    color[common == 0] = 0
    bright = ((strength >= threshold) & (common > 0)).astype(np.uint8)*255
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return strength, signal, color, bright


def measure(delta, on, signal, selection, dominance_ratio=.45, mixed_ratio=.70):
    area = int(np.count_nonzero(selection))
    if not area:
        return dict(color='UNDEFINED', area_px=0, brightness=0., chroma=0., mean_rgb_delta=[0.,0.,0.],
                    ambiguity_flags=['NO_COLOR_EVIDENCE'],color_confidence=0.,color_reason='NO_COLOR_EVIDENCE',
                    secondary_primary_ratio=None,color_evidence_rgb=[0.,0.,0.])
    # Vote on compensated new light, not the pre-existing ON color cast.
    changes = delta[selection].astype(float)
    spectral = changes - changes.min(axis=1, keepdims=True)
    means = spectral.mean(axis=0)
    order = np.argsort(means)[::-1]
    primary, secondary = int(order[0]), int(order[1])
    peak = float(means[primary])
    ratio = float(means[secondary]/peak) if peak > 0 else 1.
    names = ['BLUE','GREEN','RED']
    flags = []
    if peak < 10:
        color='UNDEFINED'; reason='LOW_CHROMA_SIGNAL'; flags.append(reason)
    elif ratio <= dominance_ratio:
        color=names[primary]; reason='DOMINANT_NEW_COLOR_CHANNEL'
    elif ratio >= mixed_ratio:
        color='MIXED'; reason='COMPARABLE_NEW_COLOR_CHANNELS'; flags.append('MULTICHANNEL_LIGHT')
    else:
        color='UNDEFINED'; reason='AMBIGUOUS_SECONDARY_CHANNEL'; flags.append(reason)
    confidence = float(1-ratio) if color in names else (ratio if color=='MIXED' else 0.)
    return dict(color=color, area_px=area, brightness=float(changes.max(axis=1).mean()),
                chroma=float(signal[selection].mean()), mean_rgb_delta=changes.mean(axis=0)[::-1].tolist(),
                ambiguity_flags=flags,color_confidence=confidence,color_reason=reason,
                secondary_primary_ratio=ratio,color_evidence_rgb=means[::-1].tolist())



def evaluate(calibration, off, on, delta, common, mode, threshold, color_threshold, roi_radius, min_area, dominance_ratio=.45, mixed_ratio=.70):
    strength, signal, color_mask, bright = signal_maps(off,on,delta,common,threshold,color_threshold)
    known=[]; candidates=[]; accepted=[]
    roi_overlay=on.copy(); accepted_overlay=on.copy(); rejected_overlay=on.copy(); candidate_overlay=on.copy()
    h,w=common.shape
    # Candidates are proposals, NEVER automatic LED identities in DISCOVER.
    count,labels,stats,_=cv2.connectedComponentsWithStats(cv2.bitwise_or(color_mask,bright))
    for i in range(1,count):
        x,y,ww,hh,area=map(int,stats[i]); local=labels[y:y+hh,x:x+ww]==i
        selected=local & (color_mask[y:y+hh,x:x+ww]>0)
        ys,xs=np.nonzero(selected if selected.any() else local)
        px=float(x+xs.mean()); py=float(y+ys.mean())
        m=measure(delta[y:y+hh,x:x+ww],on[y:y+hh,x:x+ww],signal[y:y+hh,x:x+ww],selected,dominance_ratio,mixed_ratio)
        reasons=[]
        if m['area_px']<min_area: reasons.append('INSUFFICIENT_COLOR_AREA')
        if m['color']=='UNDEFINED': reasons.append(m.get('color_reason','NO_CHROMATIC_CHANGE'))
        if area>w*h*.02: reasons.append('LARGE_REGION_POSSIBLE_REFLECTION')
        record=dict(led_id=None,key_name=None,x_ref_px=px,y_ref_px=py,**m,
                    status='REJECTED' if reasons else 'CANDIDATE',rejection_reasons=reasons,
                    component_area_px=area,bbox_ref_px=[x,y,ww,hh],candidate_led_ids=[])
        candidates.append(record)
        cv2.rectangle(candidate_overlay,(x,y),(x+ww,y+hh),(0,200,255),1)
        if reasons:
            cv2.rectangle(rejected_overlay,(x,y),(x+ww,y+hh),(0,0,255),1)
        elif mode=='DISCOVER':
            record['ambiguity_flags'].append('UNKNOWN_LED_ADD_TO_CALIBRATION')
            accepted.append(record)
    for led in calibration['leds']:
        px,py=led['x_ref_px'],led['y_ref_px']; cx,cy=round(px),round(py); r=round(roi_radius)
        x0,y0=max(0,cx-r),max(0,cy-r); x1,y1=min(w,cx+r+1),min(h,cy+r+1)
        yy,xx=np.ogrid[y0:y1,x0:x1]; disk=(xx-px)**2+(yy-py)**2<=roi_radius**2
        full_area=max(1,np.pi*roi_radius**2)
        valid=disk & (common[y0:y1,x0:x1]>0)
        coverage=min(1.,float(valid.sum()/full_area))
        selected=valid & (color_mask[y0:y1,x0:x1]>0)
        m=measure(delta[y0:y1,x0:x1],on[y0:y1,x0:x1],signal[y0:y1,x0:x1],selected,dominance_ratio,mixed_ratio)
        reasons=[]; state='OFF'
        if coverage<.9:
            state='UNCERTAIN'; reasons.append('ROI_NOT_GEOMETRICALLY_COVERED')
        elif m['area_px']>=min_area:
            ys,xs=np.nonzero(selected)
            distance=float(np.hypot(xs.mean()+x0-px,ys.mean()+y0-py))
            if distance>roi_radius*.75:
                state='UNCERTAIN'; reasons.append('COLOR_SIGNAL_FAR_FROM_LED_CENTER')
            else: state='ON'
        elif np.count_nonzero(valid & (bright[y0:y1,x0:x1]>0))>=min_area:
            state='UNCERTAIN'; reasons.append('BRIGHT_CHANGE_WITHOUT_COLOR_EVIDENCE')
            m['ambiguity_flags'].append('SATURATED_WHITE' if np.any(np.all(on[y0:y1,x0:x1][valid]>=250,axis=1)) else 'ACHROMATIC_CHANGE')
        else: reasons.append('NO_NEW_LOCAL_LIGHT')
        # Overlapping mapped ROIs cannot establish which LED emitted the light.
        if state=='ON' and m['color']=='UNDEFINED':
            state='UNCERTAIN'; reasons.append(m.get('color_reason','NO_COLOR_EVIDENCE'))
        if state=='ON' and any(other['led_id']!=led['led_id'] and np.hypot(other['x_ref_px']-px,other['y_ref_px']-py)<2*roi_radius for other in calibration['leds']):
            state='UNCERTAIN'; reasons.append('OVERLAPPING_LED_ROIS')
        roi=on[y0:y1,x0:x1]
        white=float(np.mean(np.all(roi[valid]>=250,axis=1))) if valid.any() else 0.
        record=dict(led_id=led['led_id'],key_name=led['key_name'],x_ref_px=px,y_ref_px=py,**m,
                    status=state,rejection_reasons=reasons,roi_radius_px=roi_radius,roi_coverage=coverage,
                    saturated_white_fraction=white,candidate_led_ids=[led['led_id']])
        if selected.any():
            ys,xs=np.nonzero(selected)
            record.update(signal_x_ref_px=float(xs.mean()+x0),signal_y_ref_px=float(ys.mean()+y0))
        if white and state=='ON': record['ambiguity_flags'].append('COLOR_FROM_HALO_AROUND_CLIPPED_CORE')
        if state!='ON': record['color']='UNDEFINED'
        known.append(record)
        if mode=='KNOWN_LEDS' and state in ('ON','UNCERTAIN'): accepted.append(record)
        cv2.circle(roi_overlay,(cx,cy),r,(255,0,255),2)
        cv2.putText(roi_overlay,f"{led['led_id']} {state} {record['color']}",(cx+8,cy-8),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,0,255),2)
    for rec in accepted:
        point=(round(rec['x_ref_px']),round(rec['y_ref_px']))
        cv2.circle(accepted_overlay,point,round(roi_radius),(0,220,0) if rec['status'] in ('ON','CANDIDATE') else (0,180,255),2)
        cv2.putText(accepted_overlay,f"{rec['led_id'] or 'CANDIDATE'} {rec['status']} {rec['color']}",(point[0]+8,point[1]-8),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,220,0),2)
    return known,candidates,accepted,{
        'Color mask':color_mask,'Color signal':np.clip(signal,0,255).astype(np.uint8),
        'Candidates':candidate_overlay,'Accepted':accepted_overlay,'Rejected':rejected_overlay,
        'LED ROIs':roi_overlay,'Detected LEDs':accepted_overlay},strength
