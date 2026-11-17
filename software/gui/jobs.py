"""Qt background jobs. Workers never touch widgets; cancellation is cooperative."""
import threading
import traceback
import logging
from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from software.vision.research_project import Cancelled


class Signals(QObject):
    result=Signal(object)
    progress=Signal(int,int,object)
    error=Signal(str)
    finished=Signal()
    cancelled=Signal()


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.signals=Signals()
        self.function=function
        self.cancel=threading.Event()

    @Slot()
    def run(self):
        try:
            value=self.function(self.cancel,self.signals.progress.emit)
            self.signals.result.emit(value)
        except Cancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            logging.error('Background operation failed\n%s',traceback.format_exc())
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()
