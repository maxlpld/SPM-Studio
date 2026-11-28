"""One owner of the shared store at a time (Qt).

The standalone app, SPM Studio's panel and any other host on the same computer share the same chats. To make
sure two processes never run the same chat twice or overwrite each other's files, the first one takes a lock
(``hub.lock`` in the data folder, released automatically if that process dies) and listens on a local socket
(user-only). A second process does not open the store: it asks the owner to come to the front.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _name(root: Path) -> str:
    return 'agent-hub-' + hashlib.sha1(str(Path(root).resolve()).encode()).hexdigest()[:12]


class InstanceGuard(QObject):
    activateRequested = Signal()

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(self.root / 'hub.lock'))
        self.lock.setStaleLockTime(0)                  # stale only when the owning process is gone
        self.server = None

    def acquire(self) -> bool:
        if not self.lock.tryLock(150):
            if self.lock.removeStaleLockFile() and self.lock.tryLock(150):
                pass
            else:
                return False
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(_name(self.root))
        self.server.listen(_name(self.root))
        self.server.newConnection.connect(self._incoming)
        return True

    def owner_pid(self) -> int:
        try:
            info = self.lock.getLockInfo()
            ok, pid = info[0], info[1]
            return int(pid) if ok else 0
        except Exception:
            return 0

    def _incoming(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock):
        data = bytes(sock.readAll()).strip()
        if data == b'show':
            self.activateRequested.emit()
            sock.write(b'ok\n')
            sock.flush()
        sock.disconnectFromHost()

    def ask_owner_to_show(self, timeout_ms: int = 1500) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(_name(self.root))
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(b'show\n')
        sock.flush()
        ok = sock.waitForReadyRead(timeout_ms)
        sock.disconnectFromServer()
        return ok

    def release(self):
        if self.server is not None:
            self.server.close()
            self.server = None
        if self.lock.isLocked():
            self.lock.unlock()
