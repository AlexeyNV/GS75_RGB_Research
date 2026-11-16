"""Independently register OFF/ON photos and export optical candidates."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from software.vision.calibration import load
from software.vision.led_detection import analyze_paths,export


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--off',type=Path,required=True); p.add_argument('--on',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--experiment-id',default='')
    p.add_argument('--threshold',type=int,default=30); p.add_argument('--match-radius',type=float,default=20)
    p.add_argument('--min-area',type=int,default=6); p.add_argument('--overwrite',action='store_true')
    p.add_argument('--mode',choices=['KNOWN_LEDS','DISCOVER'],default='KNOWN_LEDS')
    p.add_argument('--roi-radius',type=float,default=40)
    p.add_argument('--color-threshold',type=float,default=25)
    a=p.parse_args()
    try:
        analysis=analyze_paths(load(a.calibration),a.off,a.on,a.experiment_id or a.output.name,
                               threshold=a.threshold,match_radius=a.match_radius,min_area=a.min_area,mode=a.mode,roi_radius=a.roi_radius,color_threshold=a.color_threshold)
        export(analysis,a.output,a.overwrite)
    except (ValueError,KeyError,OSError) as exc: p.error(str(exc))
    for record in analysis.result['known_leds']:
        print(f"{record['led_id']}: {record['status']} {record['color']} ({', '.join(record['rejection_reasons'])})")
    print(f"{analysis.result['registration_status']}: {len(analysis.result['detections'])} optical regions -> {a.output}")
    return 2 if analysis.result['analysis_status']=='FAILED' else 0


if __name__=='__main__': raise SystemExit(main())
