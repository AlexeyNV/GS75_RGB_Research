"""Audit saved RGB events against an electrical journal without CV/hardware."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from software.vision.experiment_diagnostics import operation_diagnostics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis',type=Path,required=True);parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--baseline',type=Path)
    args=parser.parse_args();summary=operation_diagnostics(args.analysis,args.session,args.output,args.baseline)
    print('frames',summary['processed_frames'],'events',summary['optical_event_counts'],'matched operations',summary['matched_operations'])


if __name__=='__main__':main()
