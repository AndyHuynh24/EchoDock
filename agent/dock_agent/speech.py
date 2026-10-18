"""Speech to text, while the talk key is held (see hotkey.py).

The microphone records only between start() and stop(). Then Whisper (via
faster-whisper) turns the recording into text right on this computer: free
and private. It uses the "small.en" model (about 480 MB, downloaded once;
under 1 s per request on an M1 Mac). If a computer is too slow for it (more
than SLOW_SECONDS for a request), Dock switches to the lighter "base.en"
(about 140 MB, about 0.3 s), which hears a little less well. Computers with
SMALL_RAM_GB of memory or less use base.en from the start.

Memory: the model takes about 290 MB (small.en) while loaded, so it's only
kept while it's being used. It loads the moment the talk key goes down (about
0.8 s, done while the user is still talking) and is freed after
IDLE_UNLOAD_SECONDS without speech. When Dock starts, it only makes sure the
model is downloaded.

Tested on 56 clips in 7 English accents (US, UK, Indian, Australian, Irish,
South African): small.en got 47 right through the whole chain (speech, then
the AI picking the action), base.en 45. Amazon Transcribe heard far less, and
Voxtral on Bedrock sometimes made up names, so neither is used. Short hints
(the user's class folders) help; long ones make Whisper write lists of names.

(Apple's own speech recognition was tried first, but it only works when the
user has turned on Siri or Dictation in System Settings.)

Recording (sounddevice) and Whisper work the same on Windows; only the
microphone permission check below is Mac-specific (docs/WINDOWS-PORT.md).
"""

import os
import sys
import threading
import time

import numpy as np
import sounddevice

RATE = 16000          # Whisper wants 16 kHz mono
LIGHT_MODEL = "base.en"
SMALL_RAM_GB = 8      # this much memory or less: start with the light model
IDLE_UNLOAD_SECONDS = 600


def _memory_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return 16.0  # (unknown, e.g. on Windows: assume enough)


MODEL = os.environ.get("DOCK_SPEECH_MODEL") or ("small.en" if _memory_gb() > SMALL_RAM_GB else LIGHT_MODEL)
SLOW_SECONDS = 2.5    # slower than this on a request: switch to the light model
MAX_PROMPT = 200      # longer hints make Whisper invent lists of names
MIN_SECONDS = 0.3     # shorter than this is a slip of the finger
QUIET = 0.004         # average loudness below this is silence
SPEAKING = 0.02       # louder than this is someone talking
PAUSE_SECONDS = 1.2   # (clicked to talk) this much quiet after talking means "done"
MAX_SECONDS = 20
GIVE_UP_SECONDS = 6   # (clicked to talk) nobody said anything for this long

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
    """Free the model's memory after IDLE_UNLOAD_SECONDS without speech."""
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
    """At startup: make sure the model is downloaded (the first time it's ~480 MB),
    without keeping it in memory, and start the idle check."""
    def download():
        try:
            from faster_whisper import download_model
            download_model(_model_name)
        except Exception as e:
            print(f"Couldn't download the speech model yet: {e!r}")

    threading.Thread(target=download, daemon=True).start()
    threading.Thread(target=_unload_when_idle, daemon=True).start()


def _use_light_model() -> None:
    """This computer is too slow for the default model: switch to the light one."""
    global _model, _model_name
    if _model_name != LIGHT_MODEL:
        print(f"Speech took too long with {_model_name}; switching to {LIGHT_MODEL}.")
        _model_name, _model = LIGHT_MODEL, None
        preload()


def preload() -> None:
    """Load the model in the background (if it isn't already), e.g. the moment
    the talk key goes down, so it's ready by the time the user stops talking."""
    if _model is None:
        threading.Thread(target=_whisper, daemon=True).start()


def permissions() -> dict:
    """"allowed", "denied" or "ask" for the microphone."""
    if sys.platform == "win32":
        # Windows' privacy switch for desktop apps (Settings › Privacy & security › Microphone).
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
    """Show macOS's "allow the microphone" question (once), or Windows' microphone settings."""
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
        """Start recording. hints are words to expect (e.g. the front app's menu
        items), which helps Whisper spell them right. on_pause() is called once
        when the user has talked and then gone quiet (or after MAX_SECONDS):
        used when they clicked to talk instead of holding the key."""
        preload()  # (loads while the user talks, if it was freed)
        self.hints = hints or []
        self.chunks = []
        heard = {"talking": False, "quiet": 0, "total": 0, "told": False}

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

    def cancel(self) -> None:
        """Stop recording and throw it away."""
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.chunks = []

    def stop(self) -> str:
        """Stop recording and return what was said ("" if nothing)."""
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
