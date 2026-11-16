"""Reproducible synthetic OFF/RGB/motion fixture; never presented as phone data."""
from pathlib import Path
import json
import cv2
import numpy as np
from .aruco_markers import marker_image
from .calibration import create,Document
from .project_storage import write_image,atomic_json


def generate_sequence(directory,size=(1920,1080),fps=30,frames=120):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    board=np.full((700,1200,3),70,np.uint8)
    for identifier,(x,y) in enumerate([(60,50),(1000,50),(1000,520),(60,520)]):
        marker=marker_image(identifier,20);board[y:y+160,x:x+160]=cv2.cvtColor(marker,cv2.COLOR_GRAY2BGR)
    write_image(directory/'reference.png',board);data,_=create(directory/'reference.png',directory)
    doc=Document(data);doc.add('LED49',None,490,350);doc.save(directory/'calibration.json')
    width,height=size;path=directory/'sequence.mp4'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),fps,size)
    if not writer.isOpened():raise ValueError('MP4 encoder unavailable')
    expected=[]
    try:
        for index in range(frames):
            # First two seconds guaranteed OFF, followed by three 10-frame colors with OFF gaps.
            color='OFF';bgr=None
            if 60<=index<70:color='RED';bgr=(0,0,255)
            elif 80<=index<90:color='GREEN';bgr=(0,255,0)
            elif 100<=index<110:color='BLUE';bgr=(255,0,0)
            frame=board.copy()
            if bgr:cv2.circle(frame,(490,350),12,bgr,-1,cv2.LINE_AA)
            scale=min(width/1400,height/820)*(1+.015*np.sin(index*.09))
            transform=cv2.getRotationMatrix2D((600,350),1.2*np.sin(index*.07),scale)
            transform[:,2]+=[width/2-600+8*np.sin(index*.12),height/2-350+6*np.cos(index*.1)]
            H=np.vstack([transform,[2e-6*np.sin(index*.1),2e-6*np.cos(index*.13),1.]])
            image=cv2.warpPerspective(frame,H,size,borderValue=(40,40,40))
            # Deliberate complete marker loss outside OFF-building interval.
            if index in (85,86):image[:]=70;color='INVALID'
            writer.write(image);expected.append(dict(frame=index,expected=color,matrix=H.tolist()))
    finally:writer.release()
    atomic_json(directory/'fixture.json',dict(synthetic=True,size=list(size),fps=fps,frames=expected,
        reference_size=[1200,700],note='Large ideal markers; these are not phone footage performance/quality'))
    return path,doc.data,expected
