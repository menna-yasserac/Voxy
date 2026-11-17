"""
voice_feedback.py - optional spoken feedback for Voxy.

Public interface (the rest of Voxy only ever uses these functions and never
needs to know which TTS engine is behind them):

    speak(text, lang=None, interrupt=False)
    speak_success(text=None, context=None)
    speak_error(text=None, context=None)
    speak_status(text=None, context=None)
    speak_clarification(text=None, context=None)
    stop_speaking()
    is_speaking()          # True while queued / playing / just finished
    set_enabled(bool)
    set_rate(rate)         # "+10%" or a multiplier such as 1.1
    shutdown()

Design:
  * One lazily-started daemon worker thread + a queue. Speech requests never
    block the caller (the Tk main thread) and never overlap.
  * The TTS engine lives behind the small TTSProvider interface. The default
    provider is Edge-TTS (cloud, free, no API key, tiny local footprint).
    Swap engines with register_provider() or the VOXY_TTS_PROVIDER variable.
  * Every failure (no internet, missing package, no audio player, bad text)
    is logged and swallowed. Voice feedback can never crash Voxy.
  * Generated audio is cached on disk so repeated phrases cost no API call.

Configuration (environment variables or a .env file next to this module;
only VOXY_* keys are read from .env):

    VOXY_VOICE_ENABLED        1 | 0                       (default 1)
    VOXY_TTS_PROVIDER         edge                        (default edge)
    VOXY_TTS_AR_VOICE         ar-EG-SalmaNeural           (Egyptian Arabic)
    VOXY_TTS_EN_VOICE         en-US-AriaNeural
    VOXY_TTS_RATE             +0%  or a multiplier like 1.1
    VOXY_TTS_MIXED_STRATEGY   single | split              (default single)
    VOXY_VOICE_DEFAULT_LANG   en | ar                     (default en)
    VOXY_TTS_CACHE            cache directory
    VOXY_VOICE_LOG            DEBUG | INFO | WARNING      (default INFO)
"""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# logging + .env
# ---------------------------------------------------------------------------

log = logging.getLogger("voxy.voice")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[Voice] %(message)s"))
    log.addHandler(_handler)
    log.propagate = False
log.setLevel(
    getattr(logging, os.environ.get("VOXY_VOICE_LOG", "INFO").upper(),
            logging.INFO)
)


def _load_env_file():
    """Read VOXY_* keys from a .env next to this file (never overrides)."""
    path = Path(__file__).resolve().parent / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("VOXY_") and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


_load_env_file()

# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

_AR = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LAT = re.compile(r"[A-Za-z]")
_UNSPEAKABLE = re.compile(r"[^\w\s.,!?:;'\"()\-%+/\u060C\u061B\u061F]", re.UNICODE)

MAX_CHARS = 300


def detect_language(text):
    """'ar', 'en', 'mixed', or None when the text has no letters."""
    text = text or ""
    has_ar = bool(_AR.search(text))
    has_en = bool(_LAT.search(text))
    if has_ar and has_en:
        return "mixed"
    if has_ar:
        return "ar"
    if has_en:
        return "en"
    return None


def clean_text(text):
    """Strip symbols/markup the engine would read badly and cap the length."""
    text = str(text or "").replace("_", " ")
    text = _UNSPEAKABLE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS]
        text = cut[: cut.rfind(" ")] if " " in cut else cut
    return text


def split_by_script(text):
    """[(kind, words)] runs where kind is 'ar' or 'en'; neutral tokens
    (numbers, punctuation) stick to the run before them."""
    runs = []
    for word in text.split():
        if _AR.search(word):
            kind = "ar"
        elif _LAT.search(word):
            kind = "en"
        else:
            kind = runs[-1][0] if runs else "ar"
        if runs and runs[-1][0] == kind:
            runs[-1][1].append(word)
        else:
            runs.append((kind, [word]))
    return [(kind, " ".join(words)) for kind, words in runs]


def _normalize_rate(rate):
    if rate is None:
        return "+0%"
    if isinstance(rate, (int, float)):
        pct = max(-50, min(100, int(round((float(rate) - 1.0) * 100))))
        return f"{pct:+d}%"
    value = str(rate).strip()
    if re.fullmatch(r"[+-]\d{1,3}%", value):
        return value
    try:
        return _normalize_rate(float(value))
    except ValueError:
        return "+0%"


# ---------------------------------------------------------------------------
# short, natural phrases (spoken only for real events)
# ---------------------------------------------------------------------------

TEMPLATES = {
    "success": {
        "ar": ["تمام، المهمة خلصت بنجاح.",
               "تمام، الأمر اتنفذ بنجاح.",
               "خلصت، المهمة اتنفذت."],
        "en": ["Done. Your command was executed successfully.",
               "All set, the task is complete.",
               "Your command has been executed successfully."],
        "mixed": ["تمام، your task is completed successfully.",
                  "تمام، the command was executed successfully."],
    },
    "error": {
        "ar": ["حصلت مشكلة أثناء تنفيذ الأمر.",
               "معلش، مقدرتش أنفذ الأمر ده."],
        "en": ["Sorry, I couldn't complete this operation.",
               "Something went wrong while running that command."],
        "mixed": ["معلش، I couldn't complete this operation.",
                  "حصلت مشكلة، the command failed."],
    },
    "status": {
        "ar": ["ثانية واحدة، أنا بجهز طلبك.",
               "لحظة واحدة، لسه بشتغل على طلبك."],
        "en": ["One moment, I'm processing your request.",
               "Hang on, I'm still working on it."],
        "mixed": ["ثانية واحدة، I'm processing your request."],
    },
    "clarify": {
        "ar": ["محتاج توضيح أكتر عشان أنفذ الأمر."],
        "en": ["I need a bit more detail to do that."],
        "mixed": ["محتاج توضيح أكتر، could you clarify?"],
    },
}

# ---------------------------------------------------------------------------
# providers (the only place that knows about a concrete TTS engine)
# ---------------------------------------------------------------------------


class ProviderUnavailable(Exception):
    """Provider can never work in this environment (e.g. package missing)."""


class TTSProvider:
    """Interface every TTS engine implements. Returns encoded audio bytes."""

    name = "base"
    audio_ext = ".mp3"

    def cache_id(self, lang, rate):
        return f"{self.name}|{lang}|{rate}"

    def synthesize(self, text, lang, rate):  # pragma: no cover - interface
        raise NotImplementedError


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge online voices via the `edge-tts` package (pip install
    edge-tts). Unofficial endpoint: free and keyless, but without an SLA."""

    name = "edge"

    def __init__(self, ar_voice=None, en_voice=None, mixed_strategy=None,
                 timeout=10.0):
        self.ar_voice = ar_voice or os.environ.get(
            "VOXY_TTS_AR_VOICE", "ar-EG-SalmaNeural")
        self.en_voice = en_voice or os.environ.get(
            "VOXY_TTS_EN_VOICE", "en-US-AriaNeural")
        self.mixed_strategy = (
            mixed_strategy
            or os.environ.get("VOXY_TTS_MIXED_STRATEGY", "single")
        ).lower()
        self.timeout = timeout

    def cache_id(self, lang, rate):
        return "|".join((self.name, self.ar_voice, self.en_voice,
                         self.mixed_strategy, lang, rate))

    def plan(self, text, lang):
        """[(text, voice)] segments to synthesize and concatenate."""
        if lang == "en":
            return [(text, self.en_voice)]
        if lang == "mixed" and self.mixed_strategy == "split":
            return [
                (chunk, self.ar_voice if kind == "ar" else self.en_voice)
                for kind, chunk in split_by_script(text)
            ]
        # 'ar', or 'mixed' with the single-voice strategy
        return [(text, self.ar_voice)]

    def synthesize(self, text, lang, rate):
        try:
            import edge_tts  # noqa: F401  (lazy: keeps Voxy start-up light)
        except ImportError as error:
            raise ProviderUnavailable(
                "edge-tts is not installed. Run: pip install edge-tts"
            ) from error
        return b"".join(
            self._fetch(chunk, voice, rate)
            for chunk, voice in self.plan(text, lang)
        )

    def _fetch(self, text, voice, rate):
        import asyncio
        import edge_tts

        async def run():
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            audio = bytearray()
            async for part in communicate.stream():
                if part.get("type") == "audio":
                    audio.extend(part["data"])
            return bytes(audio)

        async def guarded():
            return await asyncio.wait_for(run(), self.timeout)

        data = asyncio.run(guarded())
        if not data:
            raise RuntimeError("TTS service returned no audio")
        return data


_PROVIDERS = {"edge": EdgeTTSProvider}


def register_provider(name, factory):
    """Plug in another engine: register_provider('azure', AzureProvider)."""
    _PROVIDERS[name.lower()] = factory


def _make_provider(name):
    factory = _PROVIDERS.get((name or "edge").lower())
    if factory is None:
        log.warning("Unknown TTS provider %r; voice feedback disabled.", name)
        return None
    return factory()


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

_STOP = object()


class VoiceFeedback:
    """Queue-based speaker. All public methods are thread-safe and
    non-blocking."""

    TAIL_SECONDS = 0.5       # keep is_speaking() True briefly after playback
    DEDUP_SECONDS = 4.0      # ignore the identical text spoken just now
    STALE_SECONDS = 20.0     # drop requests that waited too long in the queue
    MAX_PENDING = 6
    BACKOFF_AFTER = 3        # consecutive provider failures ...
    BACKOFF_SECONDS = 60.0   # ... then stay quiet this long (offline case)
    CACHE_LIMIT = 300

    def __init__(self, provider=None, enabled=None, rate=None,
                 cache_dir=None, default_lang=None):
        self._provider = provider if provider is not None else _make_provider(
            os.environ.get("VOXY_TTS_PROVIDER", "edge"))
        if enabled is None:
            enabled = os.environ.get(
                "VOXY_VOICE_ENABLED", "1").strip().lower() not in (
                "0", "false", "no", "off")
        self._enabled = bool(enabled) and self._provider is not None
        self._rate = _normalize_rate(
            rate if rate is not None else os.environ.get("VOXY_TTS_RATE"))
        self._default_lang = (
            default_lang or os.environ.get("VOXY_VOICE_DEFAULT_LANG", "en")
        )
        self._cache_dir = self._init_cache(cache_dir)

        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._thread = None
        self._gen = 0
        self._pending = 0
        self._proc = None
        self._last_end = -1e9
        self._recent = {}
        self._last_pick = {}
        self._fail_count = 0
        self._backoff_until = 0.0
        self._warned_no_player = False

    # ------------------------------------------------------------ public

    def speak(self, text, lang=None, interrupt=False):
        """Queue `text`. Returns True if it was accepted."""
        try:
            return self._enqueue(text, lang, interrupt)
        except Exception as error:  # never propagate into the GUI
            log.warning("speak() ignored error: %r", error)
            return False

    def speak_success(self, text=None, context=None):
        return self._speak_kind("success", text, context)

    def speak_error(self, text=None, context=None):
        return self._speak_kind("error", text, context)

    def speak_status(self, text=None, context=None):
        return self._speak_kind("status", text, context)

    def speak_clarification(self, text=None, context=None):
        """Speak the engine's own clarification question when it is short,
        otherwise a generic template."""
        if text and len(clean_text(text)) <= 160:
            return self.speak(text)
        return self._speak_kind("clarify", None, context)

    def stop_speaking(self):
        """Cancel current speech and everything queued."""
        with self._lock:
            self._gen += 1
            proc = self._proc
            while True:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                if item is not _STOP:
                    self._pending -= 1
            self._last_end = time.monotonic()
        self._terminate(proc)

    def is_speaking(self):
        with self._lock:
            return (self._pending > 0
                    or time.monotonic() - self._last_end < self.TAIL_SECONDS)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled) and self._provider is not None
        if not self._enabled:
            self.stop_speaking()

    def set_rate(self, rate):
        self._rate = _normalize_rate(rate)

    def shutdown(self):
        try:
            self.stop_speaking()
            thread = self._thread
            if thread is not None and thread.is_alive():
                self._q.put(_STOP)
                thread.join(timeout=1.5)
        except Exception as error:
            log.debug("shutdown error: %r", error)

    # ----------------------------------------------------------- internal

    def _speak_kind(self, kind, text, context):
        try:
            if text:
                return self.speak(text)
            lang = detect_language(context) or self._default_lang
            return self.speak(self._pick(kind, lang), lang=lang)
        except Exception as error:
            log.warning("speak_%s() ignored error: %r", kind, error)
            return False

    def _pick(self, kind, lang):
        options = TEMPLATES[kind].get(lang) or TEMPLATES[kind]["en"]
        last = self._last_pick.get((kind, lang))
        choices = [o for o in options if o != last] or options
        choice = random.choice(choices)
        self._last_pick[(kind, lang)] = choice
        return choice

    def _enqueue(self, text, lang, interrupt):
        if not self._enabled:
            return False
        cleaned = clean_text(text)
        if not cleaned:
            return False
        if lang not in ("ar", "en", "mixed"):
            lang = detect_language(cleaned) or self._default_lang
        if interrupt:
            self.stop_speaking()

        now = time.monotonic()
        with self._lock:
            last = self._recent.get(cleaned)
            if last is not None and now - last < self.DEDUP_SECONDS:
                return False
            self._recent[cleaned] = now
            if len(self._recent) > 50:
                for key in sorted(self._recent, key=self._recent.get)[:25]:
                    del self._recent[key]
            if self._pending >= self.MAX_PENDING:
                log.debug("queue full, dropping: %s", cleaned)
                return False
            self._pending += 1
            gen = self._gen

        self._ensure_worker()
        self._q.put((cleaned, lang, gen, now))
        return True

    def _ensure_worker(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker, name="voxy-voice", daemon=True)
            self._thread.start()

    def _worker(self):
        while True:
            item = self._q.get()
            if item is _STOP:
                break
            try:
                self._handle(*item)
            except Exception as error:
                log.warning("voice worker error: %r", error)
            finally:
                with self._lock:
                    self._pending -= 1
                    self._last_end = time.monotonic()

    def _handle(self, text, lang, gen, queued_at):
        if gen != self._gen or not self._enabled:
            return
        if time.monotonic() - queued_at > self.STALE_SECONDS:
            log.debug("dropping stale request: %s", text)
            return
        path = self._audio_for(text, lang)
        if path is None or gen != self._gen:
            return
        self._play(path, gen)

    # ----- audio generation + cache

    def _init_cache(self, cache_dir):
        candidates = [cache_dir, os.environ.get("VOXY_TTS_CACHE"),
                      Path.home() / ".cache" / "voxy_tts",
                      Path(tempfile.gettempdir()) / "voxy_tts"]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                path = Path(candidate)
                path.mkdir(parents=True, exist_ok=True)
                return path
            except OSError:
                continue
        return None

    def _audio_for(self, text, lang):
        if self._provider is None or self._cache_dir is None:
            return None
        key = hashlib.sha256(
            f"{self._provider.cache_id(lang, self._rate)}|{text}".encode()
        ).hexdigest()[:32]
        path = self._cache_dir / f"{key}{self._provider.audio_ext}"
        if path.exists() and path.stat().st_size > 0:
            os.utime(path, None)
            return path

        if time.monotonic() < self._backoff_until:
            log.debug("provider in back-off, skipping speech")
            return None
        try:
            data = self._provider.synthesize(text, lang, self._rate)
            if not data:
                raise RuntimeError("provider returned no audio")
        except ProviderUnavailable as error:
            log.warning("%s Voice feedback disabled.", error)
            self._enabled = False
            return None
        except Exception as error:
            self._fail_count += 1
            log.warning("TTS request failed (%s: %s)",
                        type(error).__name__, error)
            if self._fail_count >= self.BACKOFF_AFTER:
                self._fail_count = 0
                self._backoff_until = time.monotonic() + self.BACKOFF_SECONDS
                log.warning("TTS unreachable; pausing voice feedback for %d s.",
                            int(self.BACKOFF_SECONDS))
            return None

        self._fail_count = 0
        try:
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            self._prune_cache()
        except OSError as error:
            log.warning("could not write TTS cache: %r", error)
            return None
        return path

    def _prune_cache(self):
        try:
            files = sorted(self._cache_dir.glob("*" + self._provider.audio_ext),
                           key=lambda p: p.stat().st_mtime)
            for old in files[: max(0, len(files) - self.CACHE_LIMIT)]:
                old.unlink(missing_ok=True)
        except OSError:
            pass

    # ----- playback

    def _player_cmd(self, path):
        path = str(path)
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
        if shutil.which("mpv"):
            return ["mpv", "--no-video", "--really-quiet", path]
        if shutil.which("mpg123"):
            return ["mpg123", "-q", path]
        return None

    def _play(self, path, gen):
        cmd = self._player_cmd(path)
        if cmd is None:
            if not self._warned_no_player:
                self._warned_no_player = True
                log.warning("No audio player found. Install one: "
                            "sudo apt install ffmpeg   (or mpv / mpg123)")
            return
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL)
        except OSError as error:
            log.warning("could not start audio player: %r", error)
            return
        with self._lock:
            self._proc = proc
        try:
            while proc.poll() is None:
                if gen != self._gen:
                    self._terminate(proc)
                    break
                time.sleep(0.05)
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None

    @staticmethod
    def _terminate(proc):
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# module-level facade (what the GUI imports)
# ---------------------------------------------------------------------------

_instance = None
_instance_lock = threading.Lock()


def _get():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = VoiceFeedback()
        return _instance


def speak(text, lang=None, interrupt=False):
    return _get().speak(text, lang, interrupt)


def speak_success(text=None, context=None):
    return _get().speak_success(text, context)


def speak_error(text=None, context=None):
    return _get().speak_error(text, context)


def speak_status(text=None, context=None):
    return _get().speak_status(text, context)


def speak_clarification(text=None, context=None):
    return _get().speak_clarification(text, context)


def stop_speaking():
    return _get().stop_speaking()


def is_speaking():
    return _get().is_speaking()


def set_enabled(enabled):
    return _get().set_enabled(enabled)


def set_rate(rate):
    return _get().set_rate(rate)


def shutdown():
    global _instance
    with _instance_lock:
        instance, _instance = _instance, None
    if instance is not None:
        instance.shutdown()
