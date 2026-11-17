"""Export inspectable real-video frames and legacy/new OFF metrics; never controls hardware."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from software.vision.calibration import load
from software.vision.project_storage import ROOT
from software.vision.pts_video import SequentialVideoReader
from software.vision.image_registration import register
from software.vision.off_background import without_markers
from software.vision.off_diagnostics import (quality_maps,glow_regions,roi_coverage,
    save_candidate,save_diagnostics)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--calibration',type=Path,default=Path('config/gs75_board_calibration.json'))
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--frames',default='0,6,13,20,28,35,43,50,59')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();selected={int(s) for s in args.frames.split(',')}
    if not selected or min(selected)<0:parser.error('Choose nonnegative frame indices')
    args.output.mkdir(parents=True,exist_ok=False)
    cal=load(args.calibration,args.root);reader=SequentialVideoReader();anchor=anchor_mask=None;rows=[]
    try:
        meta=reader.open(args.video)
        for index in range(max(selected)+1):
            try:image,info=reader.frame(index)
            except StopIteration:break
            if index not in selected:continue
            r=register(image,cal);maps={}
            row=dict(**info,registration=r.summary(),detected_markers=r.detected,selected=False,
                reason='GEOMETRY: '+r.reason,rmse_px=r.error_px,
                blur_laplacian_var=float(cv2.Laplacian(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.CV_32F).var()))
            if r.status=='REGISTERED':
                small=cv2.resize(r.warped,None,fx=.25,fy=.25,interpolation=cv2.INTER_AREA)
                mask=cv2.resize(without_markers(r.valid_mask,cal),small.shape[1::-1],interpolation=cv2.INTER_NEAREST)
                if anchor is None:anchor=small.copy();anchor_mask=mask.copy();anchor_H=r.matrix.copy()
                metrics,maps=quality_maps(anchor,small,cv2.bitwise_and(mask,anchor_mask));row.update(metrics)
                row['relative_H']= (r.matrix@np.linalg.inv(anchor_H)).tolist()
                row['roi_coverage']=roi_coverage(without_markers(r.valid_mask,cal),cal)
                row['roi_min']=min(row['roi_coverage'].values(),default=1.)
                count,color=glow_regions(small,mask);row['glow_regions']=int(count);maps['suspicious_color']=color
                row['legacy_decision']='LIGHTING_OR_MOVING_OBJECT' if metrics['extreme_lighting'] or metrics['changed_fraction']>.02 else 'ELIGIBLE'
                row['reason']='ELIGIBLE'
                if metrics['extreme_lighting'] or max(metrics['stable_changed_fraction'],metrics['smooth_changed_fraction'])>.02:row['reason']='LIGHTING_OR_MOVING_OBJECT'
                if row['roi_min']<.9:row['reason']='KNOWN_LED_NOT_COVERED'
                if count:row['reason']='POSSIBLE_LOCAL_GLOW'
            rows.append(row);save_candidate(args.output,row,image,r,maps)
        save_diagnostics(args.output,dict(status='DIAGNOSTIC_ONLY_NOT_AN_OFF_MODEL',retained_frames=0,
            candidates=rows,video=meta,warning='No median is built; actual OFF needs >=3 reliable observations and coverage checks'))
    finally:reader.close()
    print('Diagnostics:',args.output)
    return 0


if __name__=='__main__':raise SystemExit(main())
