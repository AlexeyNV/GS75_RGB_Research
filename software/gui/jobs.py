"""Qt background jobs. Workers never touch widgets; cancellation is cooperative."""
import threading
import traceback
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
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()
