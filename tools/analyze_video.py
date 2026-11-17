"""All-frame offline RGB events; no serial/hardware access."""
import argparse
from pathlib import Path
import signal
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from software.vision.calibration import load
from software.vision.project_storage import ROOT
from software.vision.temporal_events import profile_settings
from software.vision.video_analysis import analyze_video,reaggregate_video


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path);p.add_argument('--calibration',type=Path,default=Path('config/gs75_board_calibration.json'))
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['KNOWN_LEDS','DISCOVER'],default='KNOWN_LEDS')
    p.add_argument('--profile',choices=['reliable','short'],default='reliable')
    for key in ('min-on','min-off','max-gap'):p.add_argument('--'+key,type=float)
    p.add_argument('--min-samples',type=int);p.add_argument('--off-start',type=float,default=0.)
    p.add_argument('--off-duration',type=float,default=2.);p.add_argument('--session',type=Path)
    p.add_argument('--reuse',type=Path,help='Recompute temporal results in a new directory without OpenCV')
    a=p.parse_args();cancel=threading.Event();signal.signal(signal.SIGINT,lambda *args:cancel.set())
    overrides={key:value for key,value in [('min_on_s',a.min_on),('min_off_s',a.min_off),('max_gap_s',a.max_gap),('min_samples',a.min_samples)] if value is not None}
    settings=profile_settings(a.profile=='short',**overrides)
    if a.reuse:
        report=reaggregate_video(a.reuse,a.output,settings,cancel,video=a.video)
        if a.session and report['status']=='COMPLETED':
            from software.vision.event_alignment import align_session
            from software.vision.project_storage import atomic_json
            atomic_json(a.output/'alignment.json',align_session(report['events'],a.session))
    else:
        if a.video is None:p.error('--video is required without --reuse')
        report=analyze_video(a.video,load(a.calibration,a.root),a.output,a.mode,settings,a.off_start,a.off_duration,cancel,session_path=a.session)
    print(report['status'],'frames',report['processed_frames'],'confirmed events',sum(e['status']=='CONFIRMED' for e in report['events']))
    return 0 if report['status']=='COMPLETED' else (130 if report['status']=='CANCELLED' else 2)


if __name__=='__main__':raise SystemExit(main())
