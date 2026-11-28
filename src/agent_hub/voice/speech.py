"""Speech-to-text for the Agent Hub composer — offline by default.

Design constraints (do not relax without updating the privacy notice in Settings › Voice):
  * Audio is captured only while the user records (click the microphone, or hold the push-to-talk key); never
    "always on". It stays in memory and is never written to disk.
  * Offline backend (default): Qt's own QtMultimedia capture + the local Vosk recognizer with a small model per
    language (English, French, German) cached under ``paths.models_dir()``. No audio or text leaves the
    computer. ``download_model()`` fetches a generic public model (Apache-2.0) once, only after the user
    confirms.
  * Cloud backend (optional, off): ``transcribe_cloud()`` sends the recording to an OpenAI-compatible
    transcription endpoint of a connection the user chose — only when they enabled it and gave consent, and
    never in the "Local only" routing profile.
  * The transcript goes into the message box for editing; nothing is sent automatically.
"""
from __future__ import annotations
from pathlib import Path

MODEL_NAME = 'vosk-model-small-en-us-0.15'
MODEL_URL = 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
# Agent Hub 0.2: small offline models per language (Apache-2.0, ~40–50 MB each, from the Vosk project)
MODELS = {'en': 'vosk-model-small-en-us-0.15', 'fr': 'vosk-model-small-fr-0.22', 'de': 'vosk-model-small-de-0.15'}
SAMPLE_RATE = 16000


def model_name(language: str = 'en') -> str:
    return MODELS.get(language, MODEL_NAME)


def model_url(language: str = 'en') -> str:
    return f'https://alphacephei.com/vosk/models/{model_name(language)}.zip'


def model_path(language: str = 'en') -> Path:
    from ..paths import models_dir
    return models_dir() / model_name(language)


def model_available(language: str = 'en') -> bool:
    root = model_path(language)
    return (root / 'am' / 'final.mdl').is_file() or (root / 'final.mdl').is_file()


def vosk_installed() -> bool:
    try:
        import vosk  # noqa: F401
        return True
    except ImportError:
        return False


def available(language: str = 'en') -> bool:
    """Speech-to-text can run right now, fully offline, with no further setup."""
    return vosk_installed() and model_available(language)


def download_model(progress=None, language: str = 'en') -> Path:
    """One-time fetch of the small, generic offline English acoustic model.

    Must only be called after explicit user confirmation (see chat_ui.py).
    Safe to call again later: it is a no-op once the model is cached.
    """
    import zipfile, tempfile, urllib.request
    from ..paths import models_dir
    dest = model_path(language)
    if model_available(language):
        return dest
    models_dir().mkdir(parents=True, exist_ok=True)
    tmp_path = Path(tempfile.mkstemp(suffix='.zip')[1])
    try:
        def _hook(block_num, block_size, total_size):
            if progress and total_size > 0:
                progress(min(100, int(block_num * block_size * 100 / total_size)))
        urllib.request.urlretrieve(model_url(language), str(tmp_path), _hook)
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(models_dir())
    finally:
        tmp_path.unlink(missing_ok=True)
    return dest


class Transcriber:
    """Loads each local Vosk model once per process and reuses it."""
    _model = None
    _models = {}

    @classmethod
    def _get_model(cls, language: str = 'en'):
        import vosk
        vosk.SetLogLevel(-1)
        if language not in cls._models:
            cls._models[language] = vosk.Model(str(model_path(language)))
        cls._model = cls._models[language]
        return cls._model

    @classmethod
    def transcribe_pcm16(cls, pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE, language: str = 'en') -> str:
        """``pcm_bytes``: little-endian 16-bit mono PCM. Runs entirely
        in-process; nothing here touches the network."""
        import json, vosk
        if not pcm_bytes:
            return ''
        rec = vosk.KaldiRecognizer(cls._get_model(language), sample_rate)
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
    def __init__(self, device_id: str = ''):
        self.device_id = device_id
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
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        except ImportError:
            return 'Qt Multimedia is not available in this installation.'
        device = QMediaDevices.defaultAudioInput()
        if getattr(self, 'device_id', ''):
            for d in QMediaDevices.audioInputs():
                if bytes(d.id()).decode('utf8', 'replace') == self.device_id or d.description() == self.device_id:
                    device = d
                    break
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


def input_devices() -> list[tuple[str, str]]:
    """[(id, description)] of the microphones Qt sees (empty list without QtMultimedia)."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
        return [(bytes(d.id()).decode('utf8', 'replace'), d.description()) for d in QMediaDevices.audioInputs()]
    except Exception:
        return []


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe_cloud(pcm: bytes, base: str, api_key: str, language: str = '', model: str = 'whisper-1',
                     timeout: float = 120) -> str:
    """OpenAI-compatible ``/audio/transcriptions``. Only called when the user enabled cloud transcription
    and consented; the WAV exists only in memory."""
    import json
    import uuid
    from urllib.request import Request, urlopen
    from ..agents.providers import endpoint
    url = endpoint('openai', base) + '/audio/transcriptions'
    boundary = uuid.uuid4().hex
    fields = {'model': model, **({'language': language} if language else {})}
    body = b''
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
             'Content-Type: audio/wav\r\n\r\n').encode() + pcm_to_wav(pcm) + f'\r\n--{boundary}--\r\n'.encode()
    req = Request(url, data=body, method='POST', headers={'Authorization': 'Bearer ' + api_key,
                                                          'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urlopen(req, timeout=timeout) as r:
        return str(json.load(r).get('text', '')).strip()
