"""One persistent Qt worker owns the only CDC transport; OFF uses an Event, not queued slots."""
from queue import Queue, Empty
import threading
import time
from PySide6.QtCore import QThread, Signal
from tools.rgb_probe import SerialTransport
from software.hardware.experiment import Experiment


class ExperimentWorker(QThread):
    update = Signal(dict)

    def __init__(self, root, parent=None, factory=SerialTransport, clock_ns=time.monotonic_ns):
        super().__init__(parent)
        self.root, self.factory = root, factory
        self.clock_ns = clock_ns
        self.queue = Queue()
        self.abort = threading.Event()
        self.stopping = threading.Event()
        self.engine = None
        self.last_off_confirmed = True
        self.ever_connected = False

    def submit(self, action, value=None):
        if self.stopping.is_set():
            # A cancelled window close may leave the GUI open. Reconnect is explicit.
            if action == 'connect' and not self.isRunning():
                self.stopping.clear()
            else:
                return
        if action in ('connect', 'check', 'prepare'):
            self.abort.clear()
        self.queue.put((action, value))
        if not self.isRunning():
            self.start()

    def interrupt(self, reason='Operator OFF'):
        if self.engine:
            self.engine.reason = reason
        self.abort.set()

    def shutdown(self):
        self.interrupt('GUI closed')
        self.stopping.set()
        self.queue.put(('shutdown', None))

    def disconnect_transport(self):
        if self.engine:
            self.last_off_confirmed = self.engine.safe_off()
            try:
                self.engine.transport.close()
            finally:
                self.engine = None
                self.update.emit(dict(connected=False))

    def run(self):
        try:
            while not self.stopping.is_set():
                try:
                    action, value = self.queue.get(timeout=.05)
                except Empty:
                    continue
                if self.stopping.is_set():
                    break
                # A pending OFF cancels queued starts as well as active work.
                cancelled = self.abort.is_set()
                try:
                    if action == 'connect':
                        if self.engine:
                            raise RuntimeError('Port already owned by this worker')
                        transport = self.factory(value)
                        self.ever_connected = True
                        self.last_off_confirmed = False
                        self.engine = Experiment(transport, value, self.root, clock_ns=self.clock_ns, notify=self.update.emit, abort=self.abort)
                        self.update.emit(dict(connected=True))
                        diagnostics = self.engine.preflight()
                        self.update.emit(dict(ready=True, diagnostics=diagnostics))
                    elif action == 'disconnect':
                        self.disconnect_transport()
                    elif self.engine is None:
                        raise RuntimeError('Connect COM port first')
                    elif action in ('check', 'prepare'):
                        diagnostics = self.engine.preflight()
                        self.update.emit(dict(ready=True, prepared=action == 'prepare', diagnostics=diagnostics))
                    elif action == 'run':
                        if cancelled:
                            self.engine.safe_off()
                            raise RuntimeError('Queued experiment cancelled by OFF')
                        self.engine.run_sequence(**value)
                    elif action == 'off':
                        self.last_off_confirmed = self.engine.safe_off()
                        self.update.emit(dict(state='ABORTED', ready=False))
                except Exception as exc:
                    if self.engine:
                        self.last_off_confirmed = self.engine.safe_off()
                    self.update.emit(dict(error=f'{type(exc).__name__}: {exc}. If COM is busy, close PuTTY / serial_console.', ready=False))
                finally:
                    if self.engine:
                        self.last_off_confirmed = self.engine.off_confirmed
                    self.update.emit(dict(busy=False))
        finally:
            try:
                self.disconnect_transport()
            except Exception as exc:
                self.last_off_confirmed = False
                self.update.emit(dict(error=str(exc)))
