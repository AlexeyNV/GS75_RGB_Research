"""Validated reference-pixel map and transactional editing history."""
from copy import deepcopy
import json
import math
from pathlib import Path, PurePosixPath
import re
import uuid
import numpy as np
from .aruco_markers import DICTIONARY, detect
from .project_storage import ROOT, atomic_json, image_hash, portable_image, read_image


def validate(data):
    if data.get('schema_version')!=1 or data.get('dictionary')!=DICTIONARY:
        raise ValueError('Unsupported calibration schema or dictionary')
    reference=data['reference']; width,height=reference['width'],reference['height']
    if not isinstance(width,int) or not isinstance(height,int) or min(width,height)<=0:
        raise ValueError('Invalid reference dimensions')
    if PurePosixPath(reference['path']).is_absolute() or '\\' in reference['path'] or ':' in reference['path'] or '..' in PurePosixPath(reference['path']).parts:
        raise ValueError('Reference must be a project-relative path inside the project')
    if not re.fullmatch('[0-9a-f]{64}',reference['sha256']): raise ValueError('Invalid image checksum')
    if data['coordinate_system']!={'kind':'reference_px','origin':'top_left','x_axis':'right','y_axis':'down','orientation':'EXIF_NORMALIZED','physical_mm_calibrated':False}:
        raise ValueError('Unsupported coordinate system')
    if not isinstance(data.get('calibration_version'),str) or not data['calibration_version']:
        raise ValueError('Missing calibration version')
    def point(x,y):
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in [x,y]):
            raise ValueError('Coordinates must be finite numbers')
        if not (0<=x<width and 0<=y<height): raise ValueError('Point outside reference image')
    for key,corners in data['markers'].items():
        if not re.fullmatch(r'\d+',key) or not 0<=int(key)<50: raise ValueError('Invalid marker ID')
        a=np.asarray(corners,dtype=float)
        if a.shape!=(4,2): raise ValueError('Each marker needs four ordered corners')
        for x,y in a: point(float(x),float(y))
        import cv2
        if not cv2.isContourConvex(a.astype(np.float32)) or abs(cv2.contourArea(a.astype(np.float32)))<4:
            raise ValueError('Degenerate marker corners')
    ids=data['expected_marker_ids']
    if len(set(ids))!=len(ids) or any(type(v)!=int or not 0<=v<50 for v in ids): raise ValueError('Invalid expected IDs')
    for size in data['sticker_sizes_mm'].values():
        if not isinstance(size,(int,float)) or not math.isfinite(size) or size<=0: raise ValueError('Invalid nominal sticker size')
    seen=set()
    for led in data['leds']:
        key=led['led_id']
        if not isinstance(key,str) or not re.fullmatch(r'LED[1-9]\d*',key) or key in seen: raise ValueError('LED IDs must be unique LED1, LED2, ...')
        seen.add(key); point(led['x_ref_px'],led['y_ref_px'])
        if led['key_name'] is not None and not isinstance(led['key_name'],str): raise ValueError('Invalid key name')
        if not isinstance(led.get('note',''),str): raise ValueError('Invalid LED note')
    if not isinstance(data['metadata'],dict): raise ValueError('Metadata must be an object')
    camera=data.get('camera_model')
    if camera:
        matrix=np.asarray(camera['matrix'],float); distortion=np.asarray(camera['distortion'],float)
        if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or min(matrix[0,0],matrix[1,1])<=0 or not np.allclose(matrix[2],[0,0,1]):
            raise ValueError('Invalid camera matrix')
        if distortion.size not in [4,5,8,12,14] or not np.isfinite(distortion).all(): raise ValueError('Invalid distortion coefficients')
        if camera['image_size']!=[width,height]: raise ValueError('Camera image_size differs from reference')
    json.dumps(data,allow_nan=False)
    return data


def create(path, root=ROOT, camera=None, expected=range(10), size_mm=10):
    from PIL import Image
    with Image.open(path) as source:
        source_size=source.size; source_orientation=source.getexif().get(274,1)
    relative=portable_image(path,root)
    image=read_image(Path(root)/relative,camera)
    markers=detect(image)
    data=dict(schema_version=1,calibration_version=uuid.uuid4().hex,dictionary=DICTIONARY,
              reference=dict(path=relative,width=image.shape[1],height=image.shape[0],sha256=image_hash(path),
                             source_width=source_size[0],source_height=source_size[1],source_exif_orientation=source_orientation),
              markers=markers,expected_marker_ids=list(expected),sticker_sizes_mm={str(i):size_mm for i in expected},
              coordinate_system=dict(kind='reference_px',origin='top_left',x_axis='right',y_axis='down',orientation='EXIF_NORMALIZED',physical_mm_calibrated=False),
              camera_model=camera,leds=[],metadata={'comment':''})
    return validate(data),image


def load(path, root=ROOT, verify_image=True):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError(f'Duplicate JSON field: {key}')
            result[key]=value
        return result
    data=json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=unique)
    validate(data)
    if verify_image:
        reference=Path(root)/data['reference']['path']
        if image_hash(reference)!=data['reference']['sha256']: raise ValueError('Reference checksum mismatch')
        image=read_image(reference,data.get('camera_model'))
        if list(image.shape[1::-1])!=[data['reference']['width'],data['reference']['height']]: raise ValueError('Reference resolution mismatch')
    return data


class Document:
    def __init__(self,data):
        validate(data); self.data=deepcopy(data); self.past=[]; self.future=[]; self.saved=None

    def signature(self): return json.dumps(self.data,sort_keys=True,ensure_ascii=False,allow_nan=False)
    @property
    def dirty(self): return self.signature()!=self.saved
    def mark_saved(self): self.saved=self.signature()

    def change(self,operation):
        new=deepcopy(self.data); operation(new); new['calibration_version']=uuid.uuid4().hex; validate(new)
        self.past.append(deepcopy(self.data)); self.past=self.past[-500:]; self.data=new; self.future.clear()

    def add(self,led_id,key_name,x,y,note=''):
        self.change(lambda data:data['leds'].append(dict(led_id=led_id,key_name=key_name or None,x_ref_px=float(x),y_ref_px=float(y),note=note)))

    def edit(self,identifier,**changes):
        if identifier not in [l['led_id'] for l in self.data['leds']]: raise ValueError('Unknown LED')
        def operation(data):
            led=next(l for l in data['leds'] if l['led_id']==identifier)
            led.update(changes)
            if led.get('key_name')=='': led['key_name']=None
        self.change(operation)

    def delete(self,led_id):
        self.change(lambda data:data.update(leds=[l for l in data['leds'] if l['led_id']!=led_id]))

    def undo(self):
        if self.past: self.future.append(self.data); self.data=self.past.pop()

    def redo(self):
        if self.future: self.past.append(self.data); self.data=self.future.pop()

    def save(self,path):
        validate(self.data); atomic_json(path,self.data); self.mark_saved()
