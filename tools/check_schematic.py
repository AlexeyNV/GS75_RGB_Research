"""Extract connectivity from this EasyEDA Standard sheet; no visual guesses.

Wire endpoints, symbol pins, labels and explicit junctions connect to segments.
Crossings without these points do not create junctions.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract():
    path = ROOT / 'hardware/easyeda/SCH_PCB_light_keyboard_2026-11-09.json'
    shapes = json.loads(path.read_text(encoding='utf-8'))['schematics'][0]['dataStr']['shape']
    parent, segments, labels, parts = {}, [], {}, {}

    def point(x, y):
        p = (float(x), float(y))
        parent.setdefault(p, p)
        return p

    def find(p):
        if parent[p] != p:
            parent[p] = find(parent[p])
        return parent[p]

    def union(a, b):
        parent[find(a)] = find(b)

    for shape in shapes:
        fields = shape.split('~')
        if fields[0] == 'W':
            coords = list(map(float, fields[1].split()))
            pts = [point(*coords[i:i+2]) for i in range(0, len(coords), 2)]
            segments.extend(zip(pts, pts[1:]))
        elif fields[0] == 'J':
            point(fields[1], fields[2])
        elif fields[0] == 'F':
            sections = shape.split('^^')
            name = sections[2].split('~')[0]
            p = point(*sections[1].split('~'))
            if name in labels:
                union(p, labels[name])
            labels[name] = p
        elif fields[0] == 'LIB':
            sections = shape.split('#@$')
            ref = next(x.split('~')[12] for x in sections if x.startswith('T~P~'))
            value = next(x.split('~')[12] for x in sections if x.startswith('T~N~'))
            pins = []
            for section in sections:
                if section.startswith('P~'):
                    pin = section.split('^^')
                    f = pin[0].split('~')
                    pins.append((f[3], pin[3].split('~')[4], point(f[4], f[5])))
            parts[ref] = (value, pins)
    for a, b in segments:
        union(a, b)
        for p in parent:
            cross = (p[0]-a[0])*(b[1]-a[1]) - (p[1]-a[1])*(b[0]-a[0])
            if abs(cross) < 1e-6 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]):
                union(a, p)
    nets = {}
    for name, p in labels.items():
        nets.setdefault(find(p), []).append(name)
    result = {}
    for ref, (value, pins) in parts.items():
        result[ref] = {'value': value, 'pins': {number: {'name': name, 'net': sorted(nets.get(find(p), [])), 'node': str(find(p))} for number, name, p in pins}}
    return result


if __name__ == '__main__':
    result = extract()
    out = ROOT / 'docs/schematic_nets.json'
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    for ref in ['U21', *('U'+str(i) for i in range(1, 14)), *('R'+str(i) for i in range(1, 19)), 'FPC1']:
        p = result[ref]
        print(ref, p['value'], ' '.join(f"{n}:{v['name']}={','.join(v['net']) or v['node']}" for n, v in p['pins'].items()))
