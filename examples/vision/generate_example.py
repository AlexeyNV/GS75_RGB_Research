"""Generate a small, clearly synthetic LED49 photo dataset; no real PCB mapping."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import cv2
import numpy as np
from software.vision.aruco_markers import marker_image
from software.vision.calibration import create,Document
from software.vision.project_storage import write_image,ROOT


def generate(output,overwrite=False):
    output=Path(output)
    if output.exists() and any(output.iterdir()) and not overwrite: raise FileExistsError(output)
    output.mkdir(parents=True,exist_ok=True)
    reference=np.full((700,1200,3),70,np.uint8)
    for marker_id,(x,y) in enumerate([(60,50),(1000,50),(1000,520),(60,520)]):
        reference[y:y+160,x:x+160]=cv2.cvtColor(marker_image(marker_id,20),cv2.COLOR_GRAY2BGR)
    cv2.putText(reference,'SYNTHETIC BOARD - NOT REAL LED COORDINATES',(270,90),cv2.FONT_HERSHEY_SIMPLEX,.6,(170,170,170),1)
    for x,y in [(490,350),(570,350)]: cv2.rectangle(reference,(x-7,y-5),(x+7,y+5),(105,105,105),-1)
    write_image(output/'reference.png',reference)
    data,_=create(output/'reference.png',ROOT,expected=range(4))
    document=Document(data); document.add('LED49',None,490,350,'Synthetic position only; physical key unknown')
    document.add('LED50','SyntheticKey',570,350,'Synthetic second LED, not a physical mapping')
    document.data['metadata'].update(synthetic=True,comment='Generated demonstration; no actual PCB coordinates or optical hardware validation')
    document.data['calibration_version']='synthetic-v0.1'
    document.save(output/'calibration.json')
    off_matrix=np.array([[1.,0,120],[0,1,100],[0,0,1]])
    write_image(output/'off.png',cv2.warpPerspective(reference,off_matrix,(1600,1000),borderValue=(30,30,30)))
    matrix=cv2.getPerspectiveTransform(np.float32([[0,0],[1199,0],[1199,699],[0,699]]),np.float32([[120,60],[1400,160],[1300,860],[70,740]]))
    for name,color in [('red',(0,0,255)),('green',(0,255,0)),('blue',(255,0,0))]:
        image=reference.copy(); cv2.circle(image,(490,350),12,color,-1,cv2.LINE_AA)
        write_image(output/f'{name}.png',cv2.warpPerspective(image,matrix,(1600,1000),borderValue=(30,30,30)))
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('build/vision/example'))
    parser.add_argument('--overwrite',action='store_true')
    args=parser.parse_args(); print(generate(args.output,args.overwrite))
