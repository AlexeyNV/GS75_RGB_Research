"""Portable image IO and atomic JSON persistence; originals are never modified."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import shutil
import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]


def image_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_image(path, camera=None):
    with Image.open(path) as source:
        rgb = np.array(ImageOps.exif_transpose(source).convert('RGB'))
    image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if camera:
        size = camera['image_size']
        if list(image.shape[1::-1]) != size:
            raise ValueError('Camera intrinsics image_size must match this oriented image')
        image = cv2.undistort(image, np.asarray(camera['matrix'],float), np.asarray(camera['distortion'],float))
    return image


def write_image(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    ok, buffer = cv2.imencode(path.suffix, image)
    if not ok: raise OSError(f'Cannot encode {path}')
    buffer.tofile(str(path))


def portable_image(path, root=ROOT):
    path,root = Path(path).resolve(),Path(root).resolve()
    if path.is_relative_to(root): return path.relative_to(root).as_posix()
    target=root/'data/reference'/f'{image_hash(path)}{path.suffix.lower()}'
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists(): shutil.copy2(path,target)
    elif image_hash(target)!=image_hash(path): raise ValueError('Existing imported reference has a mismatching checksum')
    return target.relative_to(root).as_posix()


def atomic_json(path, data, overwrite=True):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and not overwrite: raise FileExistsError(path)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,encoding='utf-8',delete=False,suffix='.tmp') as stream:
        temporary=Path(stream.name)
        try: json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
        except BaseException:
            stream.close(); temporary.unlink(missing_ok=True); raise
    try: os.replace(temporary,path)
    finally: temporary.unlink(missing_ok=True)
