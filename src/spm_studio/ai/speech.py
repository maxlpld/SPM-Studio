"""Fully offline, push-to-talk speech-to-text for the Assistant chat box.

Design constraints (do not relax without updating the Assistant's privacy
notice):
  * Audio is captured only while the user holds the microphone button or the
    push-to-talk key; it is never recorded "always on".
  * Captured audio never leaves this process: no network call is made with
    audio, partial transcript or final transcript. Capture uses Qt's own
    QtMultimedia (already a hard dependency of the app), and transcription
    uses the bundled, local Vosk recognizer with a model cached under
    ``spm_studio.core.paths.models_dir()``.
  * The only network access in this module is ``download_model()``, which
    fetches a small (~40 MB), generic, public acoustic model (Apache-2.0,
    no personal data whatsoever) the first time speech-to-text is used and
    the model is missing locally. It is never called silently; callers must
    get explicit user confirmation first. Once cached, no further network
    access occurs.
"""
from __future__ import annotations
from pathlib import Path

MODEL_NAME = 'vosk-model-small-en-us-0.15'
MODEL_URL = 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
SAMPLE_RATE = 16000


def model_path() -> Path:
    from spm_studio.core import paths
    return paths.models_dir() / MODEL_NAME


def model_available() -> bool:
    return (model_path() / 'am' / 'final.mdl').is_file()


def vosk_installed() -> bool:
    try:
        import vosk  # noqa: F401
        return True
    except ImportError:
        return False


def available() -> bool:
    """Speech-to-text can run right now, fully offline, with no further setup."""
    return vosk_installed() and model_available()


def download_model(progress=None) -> Path:
    """One-time fetch of the small, generic offline English acoustic model.

    Must only be called after explicit user confirmation (see chat_ui.py).
    Safe to call again later: it is a no-op once the model is cached.
    """
    import zipfile, tempfile, urllib.request
    from spm_studio.core import paths
    dest = model_path()
    if model_available():
        return dest
    paths.models_dir().mkdir(parents=True, exist_ok=True)
    tmp_path = Path(tempfile.mkstemp(suffix='.zip')[1])
    try:
        def _hook(block_num, block_size, total_size):
            if progress and total_size > 0:
                progress(min(100, int(block_num * block_size * 100 / total_size)))
        urllib.request.urlretrieve(MODEL_URL, str(tmp_path), _hook)
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(paths.models_dir())
    finally:
        tmp_path.unlink(missing_ok=True)
    return dest


class Transcriber:
    """Loads the local Vosk model once per process and reuses it."""
    _model = None

    @classmethod
    def _get_model(cls):
        import vosk
        vosk.SetLogLevel(-1)
        if cls._model is None:
            cls._model = vosk.Model(str(model_path()))
        return cls._model

    @classmethod
    def transcribe_pcm16(cls, pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        """``pcm_bytes``: little-endian 16-bit mono PCM. Runs entirely
        in-process; nothing here touches the network."""
        import json, vosk
        if not pcm_bytes:
            return ''
        rec = vosk.KaldiRecognizer(cls._get_model(), sample_rate)
        rec.AcceptWaveform(bytes(pcm_bytes))
        result = json.loads(rec.FinalResult())
        return (result.get('text') or '').strip()


def _to_16k_mono_pcm16(pcm_bytes: bytes, fmt) -> bytes:
    """Down-mix/resample whatever format the default microphone offered to
    16 kHz mono PCM16, using plain NumPy (no extra dependency)."""
    import numpy as np
    from PySide6.QtMultimedia import QAudioFormat
    if not pcm_bytes:
        return b''
    channels = fmt.channelCount() or 1
    rate = fmt.sampleRate() or SAMPLE_RATE
    sf = fmt.sampleFormat()
    if sf == QAudioFormat.SampleFormat.Int16:
        data = np.frombuffer(pcm_bytes, dtype='<i2').astype(np.float32) / 32768.0
    elif sf == QAudioFormat.SampleFormat.Int32:
        data = np.frombuffer(pcm_bytes, dtype='<i4').astype(np.float32) / 2147483648.0
    elif sf == QAudioFormat.SampleFormat.UInt8:
        data = (np.frombuffer(pcm_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sf == QAudioFormat.SampleFormat.Float:
        data = np.frombuffer(pcm_bytes, dtype='<f4').astype(np.float32)
    else:
        data = np.frombuffer(pcm_bytes, dtype='<i2').astype(np.float32) / 32768.0
    if channels > 1:
        usable = len(data) - (len(data) % channels)
        data = data[:usable].reshape(-1, channels).mean(axis=1)
    if len(data) > 1 and rate != SAMPLE_RATE:
        duration = len(data) / rate
        n_out = max(1, int(round(duration * SAMPLE_RATE)))
        x_old = np.linspace(0.0, duration, num=len(data), endpoint=False)
        x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
        data = np.interp(x_new, x_old, data)
    data = np.clip(data, -1.0, 1.0)
    return (data * 32767.0).astype('<i2').tobytes()


class MicRecorder:
    """Push-to-talk microphone capture using Qt's own QtMultimedia input.

    No extra native audio dependency: PySide6 (already required by the app)
    ships its own audio backend. Buffers raw samples in memory only while
    recording; ``stop()`` returns 16 kHz mono PCM16 bytes ready for
    ``Transcriber`` and never writes audio to disk.
    """
    def __init__(self):
        self._source = None
        self._io = None
        self._buffer = bytearray()
        self._format = None

    def is_recording(self) -> bool:
        return self._source is not None

    def start(self) -> str:
        """Returns an error string, or '' on success."""
        if self._source is not None:
            return ''
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            return 'No microphone was found.'
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        self._buffer = bytearray()
        self._format = fmt
        try:
            source = QAudioSource(device, fmt)
            io = source.start()
        except Exception as exc:
            return f'Could not open the microphone: {exc}'
        if io is None:
            return 'Could not open the microphone.'
        io.readyRead.connect(lambda: self._read(io))
        self._source = source
        self._io = io
        return ''

    def _read(self, io):
        data = io.readAll()
        if data:
            self._buffer += bytes(data)

    def stop(self) -> bytes:
        """Stop capturing; return 16 kHz mono PCM16 bytes (never written to disk)."""
        if self._source is None:
            return b''
        try:
            self._source.stop()
        except Exception:
            pass
        pcm = bytes(self._buffer)
        fmt = self._format
        self._source = None
        self._io = None
        self._buffer = bytearray()
        return _to_16k_mono_pcm16(pcm, fmt) if fmt is not None else b''

    def cancel(self):
        """Discard whatever was captured so far without transcribing it."""
        if self._source is not None:
            try:
                self._source.stop()
            except Exception:
                pass
        self._source = None
        self._io = None
        self._buffer = bytearray()
