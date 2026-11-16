"""DICT_4X4_50 markers; print sizes include the quiet zone."""
from pathlib import Path
import json
import cv2
import numpy as np
from .project_storage import write_image

DICTIONARY = 'DICT_4X4_50'


def dictionary():
    return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def detect(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    corners, ids, _ = cv2.aruco.ArucoDetector(dictionary(), parameters).detectMarkers(gray)
    result = {}
    if ids is not None:
        for marker_id, points in zip(ids.flatten(), corners):
            key = str(int(marker_id))
            if key in result:
                raise ValueError(f'Duplicate ArUco ID {key} in image')
            result[key] = points.reshape(4, 2).astype(float).tolist()
    return result


def marker_image(marker_id, cell_px=40):
    if not 0 <= marker_id < 50:
        raise ValueError('DICT_4X4_50 IDs must be 0..49')
    code = cv2.aruco.generateImageMarker(dictionary(), marker_id, 6 * cell_px)
    return cv2.copyMakeBorder(code, cell_px, cell_px, cell_px, cell_px,
                              cv2.BORDER_CONSTANT, value=255)


def generate(output, ids=range(10), size_mm=10, overwrite=False):
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    ids = list(ids)
    if len(ids) not in range(8, 13) or len(set(ids)) != len(ids) or any(not 0 <= i < 50 for i in ids):
        raise ValueError('Choose 8..12 unique IDs in 0..49')
    if size_mm not in (10, 12, 15):
        raise ValueError('Sticker size must be 10, 12 or 15 mm including white zone')
    output = Path(output)
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FileExistsError('Output is not empty; choose another directory or --overwrite')
    (output / 'individual').mkdir(parents=True, exist_ok=True)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">',
           '<rect width="210" height="297" fill="white"/>',
           '<text x="15" y="12" font-family="sans-serif" font-size="3.5">DICT_4X4_50 - Print A4 at 100%, no fit-to-page</text>']
    pdf = canvas.Canvas(str(output / 'aruco_A4.pdf'), pagesize=(210*mm, 297*mm), invariant=1)
    pdf.setTitle('GS75 RGB ArUco A4 100 percent')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(15*mm, 285*mm, 'DICT_4X4_50 - Print A4 at 100%, no fit-to-page')
    entries = []
    for index, marker_id in enumerate(ids):
        image = marker_image(marker_id)
        found = detect(image)
        if list(found) != [str(marker_id)]:
            raise RuntimeError(f'Generated marker {marker_id} did not pass detection')
        path = output / 'individual' / f'marker_{marker_id:02d}.png'
        write_image(path,image)
        x, y = 15 + (index % 6)*(size_mm+12), 25 + (index//6)*(size_mm+14)
        cell = size_mm / 8
        bits = cv2.aruco.generateImageMarker(dictionary(), marker_id, 6)
        for row, col in np.argwhere(bits == 0):
            px, py = x+(int(col)+1)*cell, y+(int(row)+1)*cell
            svg.append(f'<rect x="{px:g}" y="{py:g}" width="{cell:g}" height="{cell:g}" fill="black"/>')
            pdf.rect(px*mm, (297-py-cell)*mm, cell*mm, cell*mm, stroke=0, fill=1)
        svg.append(f'<rect x="{x}" y="{y}" width="{size_mm}" height="{size_mm}" fill="none" stroke="#999" stroke-width="0.1" stroke-dasharray="0.6 0.6"/>')
        svg.append(f'<text x="{x}" y="{y+size_mm+4}" font-size="3" font-family="sans-serif">ID {marker_id:02d}</text>')
        pdf.setStrokeColorRGB(.6, .6, .6); pdf.setLineWidth(.1*mm); pdf.setDash(.6*mm, .6*mm)
        pdf.rect(x*mm, (297-y-size_mm)*mm, size_mm*mm, size_mm*mm, stroke=1, fill=0)
        pdf.setDash(); pdf.setStrokeColorRGB(0, 0, 0)
        pdf.setFont('Helvetica', 8); pdf.drawString(x*mm, (297-y-size_mm-4)*mm, f'ID {marker_id:02d}')
        entries.append(dict(id=marker_id, sticker_mm=size_mm, quiet_zone_mm=cell, code_mm=6*cell,
                            page_box_mm=[x,y,size_mm,size_mm], png=f'individual/{path.name}', detection_verified=True))
    svg.append('<path d="M15 110H65 M15 108V112 M65 108V112" fill="none" stroke="black" stroke-width="0.25"/>')
    svg.append('<text x="15" y="117" font-size="3.5" font-family="sans-serif">50 mm reference ruler</text></svg>')
    pdf.setLineWidth(.25*mm); pdf.line(15*mm,187*mm,65*mm,187*mm)
    for x in (15,65): pdf.line(x*mm,185*mm,x*mm,189*mm)
    pdf.setFont('Helvetica',10); pdf.drawString(15*mm,180*mm,'50 mm reference ruler')
    pdf.showPage(); pdf.save()
    (output/'aruco_A4.svg').write_text('\n'.join(svg)+'\n', encoding='utf-8')
    manifest = dict(schema_version=1, dictionary=DICTIONARY, page_mm=[210,297],
                    print_scale=1, ruler_mm=50, markers=entries)
    (output/'markers_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return manifest
