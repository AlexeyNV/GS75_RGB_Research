import numpy as np


def classify(delta_bgr,on_bgr):
    """Classify positive light change; white clipping stays undefined."""
    flags=[]
    means=np.asarray(delta_bgr,float).mean(axis=0)
    if np.mean(np.all(np.asarray(on_bgr)>=250,axis=1))>.15:
        return 'UNDEFINED',['SATURATED_WHITE'],means[::-1].tolist()
    if means.max()<20:
        return 'UNDEFINED',['LOW_CHROMA_SIGNAL'],means[::-1].tolist()
    names=np.array(['BLUE','GREEN','RED'])
    active=names[means>=.35*means.max()].tolist()
    color=active[0] if len(active)==1 else 'MIXED'
    if len(active)>1: flags.append('MULTICHANNEL_LIGHT')
    return color,flags,means[::-1].tolist()
