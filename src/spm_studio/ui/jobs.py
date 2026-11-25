"""Threadpool tasks for IO and processing; subprocess jobs for independent modules."""
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

class TaskSignals(QObject):
    done=Signal(int,object)
    failed=Signal(int,str)

class Task(QRunnable):
    def __init__(self, token, fn, *args, **kwargs):
        super().__init__()
        # Prevent Qt from deleting the C++ QRunnable while queued Python
        # signal handlers still depend on its TaskSignals object.
        self.setAutoDelete(False)
        self.signals=TaskSignals()
        self.token=token
        self.fn=fn
        self.args=args
        self.kwargs=kwargs

    @Slot()
    def run(self):
        import traceback
        try:
            result=self.fn(*self.args,**self.kwargs)
            self.signals.done.emit(self.token,result)
        except Exception:
            self.signals.failed.emit(self.token,traceback.format_exc())


class FolderPoller(QObject):
    """v0.0.20: reads a folder signature in a background thread; the GUI thread only gets changes.

    ``changed(sig)`` is emitted after every poll whose signature differs from ``reference`` (the receiver sets
    ``reference`` once it has taken the new state into account), so a file still being written is seen twice.
    """
    changed=Signal(object)

    def __init__(self,signature,interval_s=2.5,parent=None):
        super().__init__(parent)
        import threading
        self._signature=signature
        self._interval=float(interval_s)
        self._stop=threading.Event()
        self._thread=threading.Thread(target=self._run,name='spm-folder-poller',daemon=True)
        self.reference=None

    def start(self):
        try:
            self.reference=self._signature()
        except Exception:
            self.reference=None
        self._thread.start()

    def _run(self):
        while not self._stop.wait(self._interval):
            try:
                sig=self._signature()
            except Exception:
                continue
            if sig is not None and sig!=self.reference:
                try:
                    self.changed.emit(sig)
                except RuntimeError:          # receiver gone (window closed)
                    return

    def stop(self):
        self._stop.set()
