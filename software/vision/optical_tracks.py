"""Optical positions are track IDs, never inferred PCB LED identities."""
import math
from statistics import median
from .temporal_events import observation,missing_observation


class OpticalTracker:
    def __init__(self,settings):self.settings=settings;self.tracks={}

    def feed(self,result,info):
        geometry=result['registrations']['on'];records=result['records'];pairs=[];assigned={};used=set()
        for index,r in enumerate(records):
            x=r.get('signal_x_ref_px',r['x_ref_px']);y=r.get('signal_y_ref_px',r['y_ref_px'])
            for key,track in self.tracks.items():
                distance=math.hypot(track['x_ref_px']-x,track['y_ref_px']-y)
                uncertainty=3*max(0.,geometry.get('reprojection_rmse_px') or 0.)
                if distance<=self.settings.spatial_radius_px+uncertainty:pairs.append((distance,index,key))
        for distance,index,key in sorted(pairs):
            if index not in used and key not in assigned:assigned[key]=index;used.add(index)
        for index,r in enumerate(records):
            if index in used:continue
            key=f'TRACK{len(self.tracks)+1:04d}'
            self.tracks[key]=dict(track_id=key,led_id=None,key_name=None,x_ref_px=r.get('signal_x_ref_px',r['x_ref_px']),
                y_ref_px=r.get('signal_y_ref_px',r['y_ref_px']),observations=[],decision_source='ALGORITHM',
                interpretation='Optical source hypothesis; silk-screen identity requires operator confirmation')
            assigned[key]=index
        output=[]
        for key,track in self.tracks.items():
            if key in assigned:
                r=records[assigned[key]]
                o=observation(r,info,geometry,key)
                o['led_id']=None;track['observations'].append(o)
                track['x_ref_px']=median(p['x_ref_px'] for p in track['observations'])
                track['y_ref_px']=median(p['y_ref_px'] for p in track['observations'])
                competitors=[pair for pair in pairs if pair[1]==assigned[key]]
                if len(competitors)>1:o['reasons'].append('SPATIAL_ASSOCIATION_AMBIGUOUS')
            else:o=missing_observation(info,geometry,key)
            output.append(o)
        return output

    def summary(self,events):
        output=[]
        for key,track in self.tracks.items():
            points=track['observations'];linked=[e for e in events if e['entity']==key]
            statuses={e['status'] for e in linked}
            status='CONFIRMED' if 'CONFIRMED' in statuses else ('CANDIDATE' if 'CANDIDATE' in statuses else 'REJECTED')
            dispersion=median(math.hypot(p['x_ref_px']-track['x_ref_px'],p['y_ref_px']-track['y_ref_px']) for p in points)
            if dispersion>self.settings.spatial_radius_px*.5 and status=='CONFIRMED':status='UNCERTAIN'
            output.append({k:v for k,v in track.items() if k!='observations'}|dict(status=status,observations=len(points),
                start_pts=points[0]['pts_s'],end_pts=points[-1]['pts_s'],spatial_median_deviation_px=dispersion,
                start_frame=points[0]['frame_index'],end_frame=points[-1]['frame_index'],
                median_chroma=median(p['chroma'] for p in points),median_brightness=median(p['brightness'] for p in points),
                colors=sorted({p['color'] for p in points}),event_ids=[e['event_id'] for e in linked]))
        return output
