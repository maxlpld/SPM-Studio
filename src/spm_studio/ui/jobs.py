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
