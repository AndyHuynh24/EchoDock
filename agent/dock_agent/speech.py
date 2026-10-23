"""Local speech-to-text with faster-whisper.

Uses small.en, or base.en on slower or low-memory machines. The model loads when
listening starts and is unloaded after IDLE_UNLOAD_SECONDS.
"""

import os
import sys
import threading
import time

import numpy as np
import sounddevice

RATE = 16000
LIGHT_MODEL = "base.en"
SMALL_RAM_GB = 8  # RAM at or below this starts with base.en
IDLE_UNLOAD_SECONDS = 600


def _memory_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return 16.0


MODEL = os.environ.get("DOCK_SPEECH_MODEL") or ("small.en" if _memory_gb() > SMALL_RAM_GB else LIGHT_MODEL)
SLOW_SECONDS = 2.5  # switch to base.en if slower than this
MAX_PROMPT = 200  # longer hints make Whisper hallucinate lists
MIN_SECONDS = 0.3
QUIET = 0.004  # silence threshold
SPEAKING = 0.02  # speech threshold
PAUSE_SECONDS = 1.2  # silence after speech that ends a click-to-talk
MAX_SECONDS = 20
GIVE_UP_SECONDS = 6

_model = None
_model_name = MODEL
_model_lock = threading.Lock()
_last_used = 0.0


def _whisper():
    global _model, _last_used
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            started = time.time()
            _model = WhisperModel(_model_name, device="cpu", compute_type="int8")
            print(f"Speech model {_model_name} loaded in {time.time() - started:.1f}s")
        _last_used = time.time()
        return _model


def _unload_when_idle() -> None:
    """Unload the model after IDLE_UNLOAD_SECONDS without speech."""
    global _model
    while True:
        time.sleep(60)
        with _model_lock:
            if _model is not None and time.time() - _last_used > IDLE_UNLOAD_SECONDS:
                _model = None
                import gc
                gc.collect()
                print(f"Speech model unloaded after {IDLE_UNLOAD_SECONDS // 60} minutes unused")


def prepare() -> None:
    """Download the model at startup without loading it, and start the idle check."""
    def download():
        try:
            from faster_whisper import download_model
            download_model(_model_name)
        except Exception as e:
            print(f"Couldn't download the speech model yet: {e!r}")

    threading.Thread(target=download, daemon=True).start()
    threading.Thread(target=_unload_when_idle, daemon=True).start()


def _use_light_model() -> None:
    """Fall back to the lighter model."""
    global _model, _model_name
    if _model_name != LIGHT_MODEL:
        print(f"Speech took too long with {_model_name}; switching to {LIGHT_MODEL}.")
        _model_name, _model = LIGHT_MODEL, None
        preload()


def preload() -> None:
    """Load the model in the background if needed."""
    if _model is None:
        threading.Thread(target=_whisper, daemon=True).start()


def permissions() -> dict:
    """Microphone permission: "allowed", "denied" or "ask"."""
    if sys.platform == "win32":
        # Windows privacy setting for desktop apps.
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
        for path in (key, key + r"\NonPackaged"):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as opened:
                    if winreg.QueryValueEx(opened, "Value")[0] == "Deny":
                        return {"microphone": "denied"}
            except OSError:
                continue
        return {"microphone": "allowed"}
    if sys.platform != "darwin":
        return {"microphone": "allowed"}
    from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    return {"microphone": {3: "allowed", 0: "ask"}.get(status, "denied")}


def ask_permission() -> None:
    """Ask for microphone access (or open Windows' settings)."""
    if sys.platform == "win32":
        import os
        os.startfile("ms-settings:privacy-microphone")
        return
    if sys.platform == "darwin":
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda granted: None)


class Listener:
    def __init__(self):
        self.stream = None
        self.chunks: list[np.ndarray] = []
        self.hints: list[str] = []

    def start(self, hints: list[str] | None = None, on_pause=None) -> None:
        """Start recording. hints: words to expect. on_pause(): called once after speech then silence."""
        preload()
        self.hints = hints or []
        self.chunks = []
        heard = self.heard = {"talking": False, "quiet": 0, "total": 0, "told": False}

        def got_audio(data, frames, when, status):
            self.chunks.append(data.copy())
            if on_pause is None or heard["told"]:
                return
            loud = float(np.sqrt(np.mean(data ** 2)))
            heard["total"] += frames
            if loud > SPEAKING:
                heard["talking"], heard["quiet"] = True, 0
            else:
                heard["quiet"] += frames
            if ((heard["talking"] and heard["quiet"] > RATE * PAUSE_SECONDS) or heard["total"] > RATE * MAX_SECONDS
                    or (not heard["talking"] and heard["total"] > RATE * GIVE_UP_SECONDS)):
                heard["told"] = True
                on_pause()

        self.stream = sounddevice.InputStream(samplerate=RATE, channels=1, dtype="float32", callback=got_audio)
        self.stream.start()

    def talked(self) -> bool:
        """Whether speech was heard since start()."""
        return getattr(self, "heard", {}).get("talking", False)

    def cancel(self) -> None:
        """Stop and discard the recording."""
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.chunks = []

    def stop(self) -> str:
        """Stop and return the transcript ("" if nothing)."""
        if self.stream is None:
            return ""
        self.stream.stop()
        self.stream.close()
        self.stream = None
        audio = np.concatenate(self.chunks)[:, 0] if self.chunks else np.zeros(0, dtype=np.float32)
        if len(audio) < RATE * MIN_SECONDS or float(np.sqrt(np.mean(audio ** 2))) < QUIET:
            return ""
        prompt = ("Talking to Dock, a desk assistant. " + ", ".join(self.hints))[:MAX_PROMPT]
        started = time.time()
        segments, _ = _whisper().transcribe(audio, language="en", beam_size=1, vad_filter=True, initial_prompt=prompt)
        text = " ".join(segment.text for segment in segments).strip()
        if time.time() - started > SLOW_SECONDS:
            _use_light_model()
        return text
