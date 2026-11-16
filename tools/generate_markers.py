"""Print-ready A4 ArUco sheet; sticker size includes white quiet zone."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from software.vision.aruco_markers import generate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--size-mm', type=int, choices=[10,12,15], default=10)
    p.add_argument('--count', type=int, default=10)
    p.add_argument('--ids', help='Comma-separated unique IDs; overrides count')
    p.add_argument('--output', type=Path, default=Path('build/markers'))
    p.add_argument('--overwrite', action='store_true')
    a = p.parse_args()
    try:
        ids = list(map(int,a.ids.split(','))) if a.ids else list(range(a.count))
        result = generate(a.output, ids, a.size_mm, a.overwrite)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    print(f"Verified {len(result['markers'])} markers: {a.output}/aruco_A4.pdf and aruco_A4.svg")


if __name__ == '__main__': main()
