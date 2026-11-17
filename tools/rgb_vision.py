"""Desktop entry point. Hardware starts only through explicit experiment controls."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    try:
        logdir=ROOT/'logs'
        logdir.mkdir(exist_ok=True)
        logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',
            handlers=[RotatingFileHandler(logdir/'rgb_vision.log',maxBytes=2000000,backupCount=3,encoding='utf-8')])
        from PySide6.QtWidgets import QApplication,QMessageBox
        from software.gui.vision_window import VisionWindow
        app=QApplication(sys.argv[:1]);app.setApplicationName('GS75 RGB Vision')
        window=VisionWindow()
        def exception(kind,value,tb):
            logging.error('GUI exception',exc_info=(kind,value,tb))
            window.error(str(value))
        sys.excepthook=exception
        window.show()
        return app.exec()
    except Exception as exc:
        logging.exception('Startup failed')
        import ctypes
        ctypes.windll.user32.MessageBoxW(0,str(exc)+'\nУстановите requirements-vision.txt. См. README.md и logs/rgb_vision.log','GS75 RGB Vision',16)
        return 2


if __name__=='__main__':raise SystemExit(main())
