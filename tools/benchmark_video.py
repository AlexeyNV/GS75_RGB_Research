"""Auxiliary reproducible runner; ordinary benchmark use is available through the GUI."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from software.vision.calibration import load
from software.vision.project_storage import ROOT,read_image,atomic_json
from software.vision.off_background import from_photo
from software.vision.video_benchmark import benchmark,plot_report,export_report
from software.vision.perf_fixture import generate_sequence


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path);p.add_argument('--calibration',type=Path,default=Path('config/gs75_board_calibration.json'))
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frames',type=int,default=120);p.add_argument('--warmup',type=int,default=3)
    p.add_argument('--mode',choices=['KNOWN_LEDS','DISCOVER'],default='KNOWN_LEDS')
    p.add_argument('--synthetic-height',type=int,choices=[1080,1440,2160])
    p.add_argument('--off-photo',type=Path);p.add_argument('--off-start',type=float,default=0.);p.add_argument('--off-duration',type=float,default=2.)
    a=p.parse_args()
    if a.frames<0 or a.warmup<0:p.error('Invalid frame count')
    if a.synthetic_height:
        a.output.mkdir(parents=True,exist_ok=False)
        video,data,expected=generate_sequence(a.output/'dataset',(round(a.synthetic_height*16/9),a.synthetic_height))
        output=a.output/'report'
    else:
        if not a.video:p.error('--video or --synthetic-height is required')
        video=a.video;data=load(a.calibration,a.root);output=a.output
    off=from_photo(read_image(a.off_photo),data) if a.off_photo else None
    report=benchmark(video,data,output,limit=a.frames,warmup=a.warmup,off=off,
        start_s=a.off_start,duration_s=a.off_duration,mode=a.mode)
    if a.synthetic_height:
        truth={r['frame']:r['expected'] for r in expected}
        for run in report['runs']:
            bad=[]
            for row in run['frames']:
                expected_color=truth[row['frame_index']]
                active=[r['color'] for r in row['records'] if r['status'] in ('ON','CANDIDATE')]
                ok=(row['registration']=='FAILED') if expected_color=='INVALID' else (active==[] if expected_color=='OFF' else active==[expected_color])
                if not ok:bad.append(dict(frame=row['frame_index'],expected=expected_color,active=active,registration=row['registration']))
            run['synthetic_ground_truth_errors']=bad
    plot_report(report,output/'frame_times.png');export_report(report,output)
    for run in report['runs']:print(run['variant'],run['end_to_end'],report['quality'][run['variant']]['verdict'])
    return 2 if any(r.get('synthetic_ground_truth_errors') for r in report['runs']) else 0


if __name__=='__main__':raise SystemExit(main())
