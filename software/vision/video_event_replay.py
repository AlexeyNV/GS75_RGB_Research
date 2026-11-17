"""Lazy diagnostics from saved H; no second ArUco/LED analysis for temporal results."""
import cv2
import numpy as np
from .image_registration import Registration,transform_points
from .video_engine import warp_valid
from .off_background import without_markers


def replay_layer(image,frame,calibration,off_image,off_mask,layer='Original',position=None):
    if layer=='Original':return image
    geometry=frame['result']['registrations']['on'];matrix=geometry.get('matrix')
    if matrix is None:raise ValueError('У кадра нет достоверной H; диагностический warp недоступен')
    r=Registration(matrix=np.asarray(matrix),status=geometry['status'])
    if geometry.get('anchor_hull') is not None:r.anchor_hull=np.asarray(geometry['anchor_hull'],np.float32)
    else:
        points=[calibration['markers'][key] for key in geometry['inlier_ids']]
        r.anchor_hull=cv2.convexHull(np.asarray(points,np.float32).reshape(-1,2))
    if layer=='Geometry':
        draw=image.copy()
        for key in geometry['inlier_ids']:
            points=transform_points(calibration['markers'][key],np.linalg.inv(r.matrix)).astype(np.int32)
            cv2.polylines(draw,[points],True,(0,220,255),2)
            cv2.putText(draw,key,tuple(points[0]),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,220,255),2)
        return draw
    h,w=off_mask.shape;warped,mask=warp_valid(image,r,w,h)
    common=cv2.bitwise_and(mask,without_markers(off_mask,calibration))
    if layer=='Registered':return warped
    if layer=='Coverage':return cv2.cvtColor(common,cv2.COLOR_GRAY2BGR)
    if layer=='Difference':
        # Replay the already recorded affine compensation; no new fit.
        parameters=frame['result'].get('lighting_bgr')
        delta=np.zeros_like(warped)
        if parameters:
            for ch,p in enumerate(parameters):delta[:,:,ch]=np.clip(warped[:,:,ch].astype(float)-off_image[:,:,ch]*p['gain']-p['offset'],0,255)
        else:raise ValueError('Компенсация освещения для кадра отсутствует')
        delta[common==0]=0;return delta
    if layer=='ROI':
        if position is None:raise ValueError('Выберите событие или оптический трек')
        x,y=map(round,position)
        return warped[max(0,y-100):min(h,y+101),max(0,x-100):min(w,x+101)]
    raise ValueError('Unknown diagnostic layer')
