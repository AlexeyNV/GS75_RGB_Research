"""Robust current-image -> reference-image homography with explicit rejection."""
from dataclasses import dataclass,field
import cv2
import numpy as np
from .aruco_markers import detect
from .frame_profile import timed,ACTIVE


def transform_points(points,matrix):
    return cv2.perspectiveTransform(np.asarray(points,float).reshape(-1,1,2),np.asarray(matrix,float)).reshape(-1,2)


@dataclass
class Registration:
    status: str='FAILED'
    reason: str='Not estimated'
    error_px: float|None=None
    max_error_px: float|None=None
    common_ids: list=field(default_factory=list)
    inlier_ids: list=field(default_factory=list)
    detected: dict=field(default_factory=dict)
    coverage: float=0
    matrix: object=None
    warped: object=None
    valid_mask: object=None

    def summary(self):
        return dict(status=self.status,reason=self.reason,reprojection_rmse_px=self.error_px,
                    max_inlier_error_px=self.max_error_px,common_ids=self.common_ids,inlier_ids=self.inlier_ids,
                    anchor_coverage=self.coverage,matrix=self.matrix.tolist() if self.matrix is not None else None,
                    anchor_hull=self.anchor_hull.tolist() if getattr(self,'anchor_hull',None) is not None else None)


@timed('HOMOGRAPHY')
def register(image,calibration,detected=None,max_error_px=3.0,rectify=True):
    result=Registration()
    try: result.detected=detect(image) if detected is None else detected
    except ValueError as exc: result.reason=str(exc); return result
    keys=sorted(set(calibration['markers']) & set(result.detected),key=int)
    result.common_ids=keys
    if len(keys)<2:
        result.reason='At least two spatially separated matching markers required (three recommended)'; return result
    source=np.asarray([result.detected[k] for k in keys],float).reshape(-1,2)
    target=np.asarray([calibration['markers'][k] for k in keys],float).reshape(-1,2)
    if not np.isfinite(source).all() or source.shape!=target.shape:
        result.reason='Invalid corner coordinates'; return result
    matrix,inliers=cv2.findHomography(source,target,cv2.RANSAC,max_error_px,maxIters=4000,confidence=.995)
    if matrix is None or inliers is None or not np.isfinite(matrix).all():
        result.reason='Homography estimation failed'; return result
    accepted=inliers.ravel().astype(bool)
    # Reject marker identities which do not contribute at least three inlier corners.
    result.inlier_ids=[key for i,key in enumerate(keys) if accepted[4*i:4*i+4].sum()>=3]
    if len(result.inlier_ids)<2 or accepted.sum()<8 or accepted.mean()<.6:
        result.reason='Insufficient robust inlier support'; return result
    projected=transform_points(source,matrix)
    errors=np.linalg.norm(projected-target,axis=1)[accepted]
    result.error_px=float(np.sqrt(np.mean(errors**2))); result.max_error_px=float(errors.max())
    if result.error_px>max_error_px or result.max_error_px>max_error_px*1.5:
        result.reason='Reprojection error too large'; return result
    w,h=calibration['reference']['width'],calibration['reference']['height']
    hull=cv2.convexHull(target[accepted].astype(np.float32))
    result.coverage=float(cv2.contourArea(hull)/(w*h))
    if result.coverage<.015 or np.ptp(target[accepted,0])<w*.15 or np.ptp(target[accepted,1])<h*.15:
        result.reason='Reference anchors are clustered or nearly collinear'; return result
    ih,iw=image.shape[:2]
    corners=np.array([[0,0],[iw-1,0],[iw-1,ih-1],[0,ih-1]],float)
    homogeneous=np.c_[corners,np.ones(4)] @ matrix.T
    denominators=homogeneous[:,2]
    if np.any(np.abs(denominators)<1e-8) or np.any(denominators*denominators[0]<=0):
        result.reason='Projective horizon intersects image'; return result
    polygon=transform_points(corners,matrix).astype(np.float32)
    area=cv2.contourArea(polygon,oriented=True)
    if not np.isfinite(polygon).all() or not cv2.isContourConvex(polygon) or not .02*w*h<area<30*w*h:
        result.reason='Mirrored, folded or extreme geometry'; return result
    result.matrix=matrix
    if not rectify:
        # Convex intersection verifies visibility without allocating a full-resolution mask.
        intersection,_=cv2.intersectConvexConvex(polygon,hull.reshape(-1,2))
        if intersection<w*h*.02:
            result.matrix=None;result.reason='Insufficient visible reference area';return result
        result.anchor_hull=hull
    else:
        profile=ACTIVE.get()
        from contextlib import nullcontext
        with profile.stage('IMAGE_RECTIFICATION') if profile else nullcontext():
            mask=cv2.warpPerspective(np.full(image.shape[:2],255,np.uint8),matrix,(w,h),flags=cv2.INTER_NEAREST)
            mask=cv2.erode(mask,np.ones((5,5),np.uint8))
            anchor_mask=np.zeros((h,w),np.uint8); cv2.fillConvexPoly(anchor_mask,hull.astype(np.int32),255)
            mask=cv2.bitwise_and(mask,anchor_mask)
            if np.count_nonzero(mask)<w*h*.02:
                result.reason='Insufficient visible reference area'; return result
            result.valid_mask=mask
            result.warped=cv2.warpPerspective(image,matrix,(w,h),flags=cv2.INTER_LINEAR)
    result.status='REGISTERED' if len(result.inlier_ids)>=3 else 'DEGRADED'
    result.reason='Robust marker registration' if result.status=='REGISTERED' else 'Only two markers support registration; manual review required'
    return result
