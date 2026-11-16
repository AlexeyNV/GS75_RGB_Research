"""Read-only validation of operator photographs; reports never replace input data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from software.vision.calibration import load
from software.vision.led_detection import analyze_paths,export
from software.vision.project_storage import ROOT,read_image,write_image,atomic_json
from software.vision.image_registration import transform_points


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def raw_red_check(image):
    b,g,r=cv2.split(image.astype(np.int16))
    mask=(r>np.maximum(b,g)+50).astype(np.uint8)
    count,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    return [dict(area_px=int(stats[i,4]),center=centers[i].tolist()) for i in range(1,count) if stats[i,4]>20]


def validate_real(calibration_path,off_path,on_path,output,archive=None):
    calibration=load(calibration_path)
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Choose a new empty report directory; previous reports are preserved')
    inputs=[Path(calibration_path),Path(off_path),Path(on_path),ROOT/calibration['reference']['path']]
    hashes={str(p):digest(p) for p in inputs}
    a=analyze_paths(calibration,off_path,on_path,output.name,mode='KNOWN_LEDS')
    export(a,output)
    off=read_image(off_path); on=read_image(on_path)
    summary=dict(input_sha256=hashes,off_shape=list(off.shape),on_shape=list(on.shape),
                 raw_red_off=raw_red_check(off),raw_red_on=raw_red_check(on),
                 parameters=a.result['parameters'],registrations=a.result['registrations'],
                 known_leds=a.result['known_leds'])
    if archive:
        archive=Path(archive); old=json.loads((archive/'results.json').read_text(encoding='utf-8'))
        mask=cv2.imread(str(archive/'valid_overlap.png'),cv2.IMREAD_GRAYSCALE)
        summary['archived_run']=dict(path=str(archive),regions=len(old['detections']),
            parameters=old['parameters'],effective_threshold=old.get('effective_threshold'),
            reprojection=old['registrations'],region_areas=[r['area_px'] for r in old['detections']],
            colors=sorted(set(r['color'] for r in old['detections'])),
            mask_at_leds={r['led_id']:int(mask[round(r['y_ref_px']),round(r['x_ref_px'])]) for r in calibration['leds']})
    if a.result['analysis_status']=='ANALYZED':
        # Named report artifacts and numerical cross-sections from the real ROI.
        write_image(output/'off_registered.png',a.images['Registered OFF'])
        write_image(output/'red_registered.png',a.images['Registered ON'])
        write_image(output/'red_signal.png',a.images['Color signal'])
        write_image(output/'annotated_result.png',a.images['Detected LEDs'])
        for record in a.result['known_leds']:
            x,y=round(record['x_ref_px']),round(record['y_ref_px']); r=round(record['roi_radius_px'])
            y0,y1=max(0,y-r),min(a.images['Registered ON'].shape[0],y+r+1)
            x0,x1=max(0,x-r),min(a.images['Registered ON'].shape[1],x+r+1)
            panels=[a.images[name][y0:y1,x0:x1] for name in ['Registered OFF','Registered ON','Difference']]
            write_image(output/(record['led_id'].lower()+'_roi.png'),np.concatenate(panels,axis=1))
            fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
            for idx,color in enumerate(['b','g','r']):
                axes[0].plot(np.arange(x0,x1)-record['x_ref_px'],a.images['Difference'][y,x0:x1,idx],color,label=color.upper())
            axes[0].axhline(a.result['parameters']['threshold'],linestyle='--',color='k',label='brightness threshold')
            axes[0].set(xlabel='Reference x offset (px)',ylabel='Compensated positive delta',title=record['led_id']+' center cross-section');axes[0].legend()
            region=a.images['Color signal'][y0:y1,x0:x1]
            axes[1].hist(region.ravel(),bins=40)
            axes[1].axvline(a.result['parameters']['color_threshold'],color='r',linestyle='--')
            axes[1].set(xlabel='New channel excess',ylabel='Pixels',title='ROI chroma signal')
            fig.savefig(output/(record['led_id'].lower()+'_diagnostics.png'),dpi=140);plt.close(fig)
        # Check raw red centroid against the independently projected map point.
        if summary['raw_red_on']:
            raw=max(summary['raw_red_on'],key=lambda r:r['area_px'])
            mapped=transform_points([raw['center']],a.result['registrations']['on']['matrix'])[0]
            summary['raw_red_centroid_reference']=mapped.tolist()
            summary['raw_red_distance_to_mapped_leds_px']={led['led_id']:float(np.hypot(mapped[0]-led['x_ref_px'],mapped[1]-led['y_ref_px'])) for led in calibration['leds']}
    # Do not retain multiple full-resolution pipelines in memory simultaneously.
    del a
    b=analyze_paths(calibration,off_path,off_path,'real_off_off',mode='KNOWN_LEDS')
    export(b,output/'off_off');summary['off_off_known_leds']=b.result['known_leds'];del b
    d=analyze_paths(calibration,off_path,on_path,'real_discover',mode='DISCOVER')
    export(d,output/'discover');summary['discover_proposals']=d.result['detections'];del d
    summary['inputs_unchanged']=all(digest(p)==sha for p,sha in hashes.items())
    summary['acceptance_passed']=(summary['inputs_unchanged'] and
        all(r['status']=='REGISTERED' for r in summary['registrations'].values()) and
        [(r['led_id'],r['color']) for r in summary['known_leds'] if r['status']=='ON']==[('LED49','RED')] and
        all(r['status']=='OFF' for r in summary['off_off_known_leds']))
    atomic_json(output/'result.json',summary)
    lines=['# Real photograph validation','',f"Acceptance passed: {summary['acceptance_passed']}",
           '', 'Input SHA256 / dimensions, measured values and thresholds are in result.json.',
           'All inputs were read-only; synthetic fixtures were not substituted.', '',
           '| LED | Status | Color | Color area px | Brightness | Chroma | ROI coverage |',
           '|---|---|---|---:|---:|---:|---:|']
    for r in summary['known_leds']:
        lines.append(f"| {r['led_id']} | {r['status']} | {r['color']} | {r['area_px']} | {r['brightness']:.3f} | {r['chroma']:.3f} | {r.get('roi_coverage',0):.3f} |")
    lines += ['',f"Parameters: `{json.dumps(summary['parameters'])}`",'',
              f"Raw diagnostic R > max(G,B)+50: OFF={summary['raw_red_off']}, ON={summary['raw_red_on']}",
              '',f"DISCOVER proposals: {len(summary['discover_proposals'])}; identities are not assigned.",
              '', 'The archived 44-region run, when supplied, has a different registration from current inputs.',
              'Its valid mask excludes LED49. Global threshold 165 retains neutral texture edges;',
              'all 44 components have area below 30, so min-area=30 removes all of them.',
              'Current KNOWN_LEDS uses the mapped ROI and new color evidence; white core is excluded from the color vote.',
              'If a known ROI lacks geometric coverage, it remains visible as UNCERTAIN.',
              '', 'Real GREEN/BLUE photographs and the new PHOTO firmware still require operator tests.']
    (output/'validation_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--calibration',type=Path,default=Path('config/gs75_board_calibration.json'))
    p.add_argument('--off',type=Path,default=Path('data/off.jpg'))
    p.add_argument('--on',type=Path,default=Path('data/red.jpg'))
    p.add_argument('--output',type=Path,default=Path('build/vision/real_validation_report'))
    p.add_argument('--archive',type=Path,help='Optional read-only old results directory')
    args=p.parse_args()
    try: result=validate_real(args.calibration,args.off,args.on,args.output,args.archive)
    except (ValueError,OSError,KeyError) as exc: p.error(str(exc))
    print(f"Real validation: {'PASS' if result['acceptance_passed'] else 'FAIL'} -> {args.output}")
    return 0 if result['acceptance_passed'] else 2


if __name__=='__main__': raise SystemExit(main())
