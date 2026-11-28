"""Voice input controller (Qt): record → transcribe off the GUI thread → text for the composer.

Never sends anything: the result is emitted as ``transcribed(text)`` for the message box. Errors (no
microphone, denied permission, missing model, empty recording, failed transcription) arrive as
``failed(message)`` with a readable message.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from . import speech


class _Transcribe(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, pcm: bytes, conf: dict, parent=None):
        super().__init__(parent)
        self.pcm = pcm
        self.conf = dict(conf)

    def run(self):
        try:
            if self.conf.get('voice_backend') == 'cloud':
                if not self.conf.get('voice_cloud_consent') or self.conf.get('routing_profile') == 'local':
                    raise RuntimeError('Cloud transcription is not allowed (no consent, or Local only mode).')
                from .. import settings_store as ss
                conn = next((c for c in ss.load_ai()['connections']
                             if c['id'] == self.conf.get('voice_cloud_connection')), None)
                if conn is None:
                    raise RuntimeError('Choose the cloud transcription connection in Settings › Voice.')
                text = speech.transcribe_cloud(self.pcm, conn.get('base') or ss.PROVIDERS[conn['provider']]['base'],
                                               ss.api_key(conn), self.conf.get('voice_language', ''))
            else:
                text = speech.Transcriber.transcribe_pcm16(self.pcm, language=self.conf.get('voice_language', 'en'))
            self.done.emit(text)
        except Exception as exc:
            self.failed.emit(str(exc)[:300])


class VoiceController(QObject):
    stateChanged = Signal(str)          # idle · recording · transcribing
    elapsed = Signal(int)               # seconds while recording
    transcribed = Signal(str)
    failed = Signal(str)
    needsModel = Signal(str)            # language whose offline model must be downloaded first

    def __init__(self, conf_getter, parent=None):
        super().__init__(parent)
        self.conf = conf_getter
        self.recorder = None
        self.state = 'idle'
        self.started = 0.0
        self.job = None
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(lambda: self.elapsed.emit(int(time.monotonic() - self.started)))

    def _set(self, state):
        self.state = state
        self.stateChanged.emit(state)

    def backend_label(self) -> str:
        c = self.conf()
        if c.get('voice_backend') == 'cloud' and c.get('voice_cloud_consent') and c.get('routing_profile') != 'local':
            return 'cloud transcription (your connection)'
        return f"offline Vosk ({c.get('voice_language', 'en')})"

    def ready(self) -> str:
        """'' when recording can start, else the reason."""
        c = self.conf()
        if c.get('voice_backend') == 'cloud' and c.get('voice_cloud_consent') and c.get('routing_profile') != 'local':
            return ''
        if not speech.vosk_installed():
            return 'Offline speech-to-text needs the "vosk" package (pip install vosk).'
        if not speech.model_available(c.get('voice_language', 'en')):
            return 'model'
        return ''

    def toggle(self):
        if self.state == 'recording':
            self.stop()
        elif self.state == 'idle':
            self.start()

    def start(self):
        if self.state != 'idle':
            return
        reason = self.ready()
        if reason == 'model':
            self.needsModel.emit(self.conf().get('voice_language', 'en'))
            return
        if reason:
            self.failed.emit(reason)
            return
        self.recorder = speech.MicRecorder(self.conf().get('voice_device', ''))
        error = self.recorder.start()
        if error:
            self.recorder = None
            hint = ' Check the microphone permission of this application in the system settings.' \
                if 'open' in error.lower() else ''
            self.failed.emit(error + hint)
            return
        self.started = time.monotonic()
        self.timer.start()
        self._set('recording')

    def stop(self):
        if self.state != 'recording' or self.recorder is None:
            return
        self.timer.stop()
        pcm = self.recorder.stop()
        self.recorder = None
        if len(pcm) < 3200:                      # < 0.1 s of audio
            self._set('idle')
            self.failed.emit('Nothing was recorded (check the microphone and its level).')
            return
        self._set('transcribing')
        self.job = _Transcribe(pcm, self.conf(), self)
        self.job.done.connect(self._done)
        self.job.failed.connect(self._failed)
        self.job.start()

    def cancel(self):
        self.timer.stop()
        if self.recorder is not None:
            self.recorder.cancel()
            self.recorder = None
        if self.job is not None and self.job.isRunning():
            try:
                self.job.done.disconnect(self._done)
            except (RuntimeError, TypeError):
                pass
        self._set('idle')

    def _done(self, text):
        self._set('idle')
        if text.strip():
            self.transcribed.emit(text.strip())
        else:
            self.failed.emit('No speech was recognized.')

    def _failed(self, reason):
        self._set('idle')
        self.failed.emit('Transcription failed: ' + reason)

    def shutdown(self):
        self.cancel()
        if self.job is not None:
            self.job.wait(3000)
