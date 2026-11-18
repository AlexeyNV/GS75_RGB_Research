"""Count unavailable evidence by cause. Geometry failure never means darkness."""
from collections import defaultdict


CATEGORIES=('ARUCO_LOSS','BAD_HOMOGRAPHY','ROI_COVERAGE','LOW_COLOR_SIGNAL',
            'AMBIGUOUS_COLOR','TEMPORAL_CONTINUITY','OTHER')


def categories(row, geometry=None):
    if row['state'] not in ('UNCERTAIN','INVALID_GEOMETRY','NO_COVERAGE'):return []
    geometry=geometry or {};reasons=' '.join(row.get('reasons',[])).upper()
    if row['state']=='NO_COVERAGE' or 'ROI_NOT_' in reasons or 'ROI_NOT_GEOMETRICALLY' in reasons or 'CURRENT_ROI_NOT_COVERED' in reasons:
        return ['ROI_COVERAGE']
    if row['state']=='INVALID_GEOMETRY':
        common=geometry.get('common_ids')
        return ['ARUCO_LOSS' if common is not None and len(common)<3 or any(s in reasons for s in ('NO ARUCO','NO COMMON','NOT ENOUGH MARKER')) else 'BAD_HOMOGRAPHY']
    result=[]
    if any(s in reasons for s in ('NO_COLOR_EVIDENCE','ACHROMATIC','LOW_COLOR','LOW_CHROMA')):result.append('LOW_COLOR_SIGNAL')
    if any(s in reasons for s in ('AMBIGUOUS_COLOR','MIXED','COLOR_AMBIGUITY','TRANSIENT_COLOR_CONFLICT')):result.append('AMBIGUOUS_COLOR')
    if any(s in reasons for s in ('MISSING_FRAME','PTS_OBSERVATION_GAP','OBSERVABILITY_LOSS')):result.append('TEMPORAL_CONTINUITY')
    return result or ['OTHER']


def uncertainty_statistics(observations, events=(), intervals=()):
    """Unique frame counts and contiguous runs per entity/category.

    Labels can overlap, notably ROI loss and a bridged temporal gap. Counts
    therefore must not be added to obtain a total number of unknown frames.
    """
    groups={key:defaultdict(set) for key in CATEGORIES}
    pts={};unknown=set()
    for row in observations:
        entity=row['entity'];frame=row['frame_index'];pts[(entity,frame)]=row['pts_s']
        if row['state'] in ('UNCERTAIN','INVALID_GEOMETRY','NO_COVERAGE'):unknown.add(frame)
        for category in row.get('uncertainty_categories',categories(row)):groups[category][entity].add(frame)
    temporal_ranges=[(e['entity'],g['start_s'],g['end_s']) for e in events for g in e.get('unknown_gaps',[])]
    temporal_ranges += [(u['entity'],u['start_s'],u['end_s']) for u in intervals
                        if any(s in ' '.join(u.get('reasons',[])) for s in ('MISSING_FRAME','PTS_OBSERVATION_GAP'))]
    for entity,start,end in temporal_ranges:
        for (name,frame),t in pts.items():
            if name==entity and start<=t<end:groups['TEMPORAL_CONTINUITY'][entity].add(frame)
    result={}
    for key,entities in groups.items():
        intervals_count=0
        for frames in entities.values():
            ordered=sorted(frames);intervals_count+=sum(index==0 or frame!=ordered[index-1]+1 for index,frame in enumerate(ordered))
        result[key]=dict(frames=len(set().union(*entities.values())) if entities else 0,
            entity_frame_observations=sum(len(frames) for frames in entities.values()),intervals=intervals_count)
    return dict(unique_unknown_frames=len(unknown),by_reason=result,
        counting='Frames unique across entities; intervals contiguous frame-index runs per entity/reason; categories may overlap')
