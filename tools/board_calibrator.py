"""Launch the Qt board calibrator; no serial device or camera is accessed."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--calibration',type=Path)
    p.add_argument('--image',type=Path)
    a=p.parse_args()
    from PySide6.QtWidgets import QApplication
    from software.gui.board_calibrator import Calibrator
    app=QApplication(sys.argv[:1]); window=Calibrator()
    if a.calibration: window.load_map(a.calibration)
    elif a.image: window.set_reference(a.image)
    window.show(); return app.exec()


if __name__=='__main__': raise SystemExit(main())
