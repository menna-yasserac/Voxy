"""
Offline tests for voice_feedback.py and its GUI hooks.

NOTHING here touches the network, a sound card or a display:
  * the TTS provider is a fake that returns bytes,
  * the "player" is a real subprocess (`sleep`) so start/stop/terminate paths
    are exercised for real, but no sound is produced,
  * the GUI hooks are tested against a stub `tkinter`.
Run:  python3 -m unittest test_voice_feedback -v
"""

import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

import voice_feedback as vf


class FakeProvider(vf.TTSProvider):
    name = "fake"

    def __init__(self, fail=False, delay=0.0):
        self.calls = []
        self.fail = fail
        self.delay = delay

    def synthesize(self, text, lang, rate):
        self.calls.append((text, lang, rate))
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise ConnectionError("offline")
        return b"FAKEAUDIO" + text.encode()


def make(provider=None, play_seconds="0.15", **kw):
    tmp = tempfile.mkdtemp()
    v = vf.VoiceFeedback(provider=provider or FakeProvider(), enabled=True,
                         cache_dir=tmp, **kw)
    v.TAIL_SECONDS = 0.05
    v.DEDUP_SECONDS = 0.0
    events = []

    def cmd(path):
        events.append(("start", time.monotonic()))
        return ["sleep", play_seconds]

    v._player_cmd = cmd
    v.events = events
    return v


def wait_idle(v, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not v.is_speaking():
            return True
        time.sleep(0.02)
    return False


class TextHelpers(unittest.TestCase):
    def test_detect_language(self):
        self.assertEqual(vf.detect_language("افتح الملف"), "ar")
        self.assertEqual(vf.detect_language("Open Firefox"), "en")
        self.assertEqual(vf.detect_language("افتح Firefox"), "mixed")
        self.assertIsNone(vf.detect_language("123 !?"))
        self.assertIsNone(vf.detect_language(""))

    def test_clean_text(self):
        self.assertEqual(vf.clean_text("✓ 1. Done ✗"), "1. Done")
        self.assertEqual(vf.clean_text("   "), "")
        self.assertEqual(vf.clean_text(None), "")
        self.assertLessEqual(len(vf.clean_text("word " * 200)), vf.MAX_CHARS)

    def test_split_by_script(self):
        runs = vf.split_by_script("تمام، the task is done 100%")
        self.assertEqual([k for k, _ in runs], ["ar", "en"])
        self.assertIn("100%", runs[1][1])

    def test_rate(self):
        self.assertEqual(vf._normalize_rate(None), "+0%")
        self.assertEqual(vf._normalize_rate(1.2), "+20%")
        self.assertEqual(vf._normalize_rate("-10%"), "-10%")
        self.assertEqual(vf._normalize_rate("junk"), "+0%")

    def test_edge_plan(self):
        p = vf.EdgeTTSProvider(ar_voice="AR", en_voice="EN",
                               mixed_strategy="single")
        self.assertEqual(p.plan("hello", "en"), [("hello", "EN")])
        self.assertEqual(p.plan("تمام", "ar"), [("تمام", "AR")])
        self.assertEqual(p.plan("تمام done", "mixed"), [("تمام done", "AR")])
        p.mixed_strategy = "split"
        self.assertEqual(p.plan("تمام done", "mixed"),
                         [("تمام", "AR"), ("done", "EN")])


class Behaviour(unittest.TestCase):
    def test_speak_plays_and_is_speaking_transitions(self):
        v = make()
        self.assertFalse(v.is_speaking())
        self.assertTrue(v.speak("Hello there"))
        self.assertTrue(v.is_speaking())          # immediately, before audio
        self.assertTrue(wait_idle(v))
        self.assertEqual(len(v.events), 1)
        self.assertEqual(v._provider.calls[0][1], "en")
        v.shutdown()

    def test_invalid_text_is_ignored(self):
        v = make()
        for bad in ("", "   ", None, "✓✓✓"):
            self.assertFalse(v.speak(bad))
        self.assertEqual(v._provider.calls, [])

    def test_cache_hit_skips_provider(self):
        v = make()
        v.speak("Same phrase")
        wait_idle(v)
        v.speak("Same phrase")
        wait_idle(v)
        self.assertEqual(len(v._provider.calls), 1)
        self.assertEqual(len(v.events), 2)
        v.shutdown()

    def test_dedup_window(self):
        v = make()
        v.DEDUP_SECONDS = 5
        self.assertTrue(v.speak("Repeat me"))
        self.assertFalse(v.speak("Repeat me"))
        wait_idle(v)
        v.shutdown()

    def test_no_overlap_and_order(self):
        v = make(play_seconds="0.1")
        for i in range(4):
            self.assertTrue(v.speak(f"message number {i}"))
        self.assertTrue(wait_idle(v, 10))
        order = [c[0] for c in v._provider.calls]
        self.assertEqual(order, [f"message number {i}" for i in range(4)])
        starts = [t for _, t in v.events]
        for a, b in zip(starts, starts[1:]):
            self.assertGreaterEqual(b - a, 0.09)   # sequential, not parallel
        v.shutdown()

    def test_queue_limit(self):
        v = make(play_seconds="0.3")
        accepted = [v.speak(f"flood {i}") for i in range(20)]
        self.assertLessEqual(sum(accepted), v.MAX_PENDING)
        v.stop_speaking()
        v.shutdown()

    def test_stop_speaking_kills_playback_and_drops_queue(self):
        v = make(play_seconds="5")
        v.speak("first long one")
        v.speak("second queued one")
        time.sleep(0.4)                           # let playback start
        self.assertEqual(len(v.events), 1)
        t0 = time.monotonic()
        v.stop_speaking()
        self.assertTrue(wait_idle(v, 3))
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual(len(v.events), 1)        # queued one never played
        v.shutdown()

    def test_provider_failure_never_raises_and_backs_off(self):
        v = make(provider=FakeProvider(fail=True))
        for i in range(6):
            self.assertTrue(v.speak(f"offline test {i}"))
            wait_idle(v)
        self.assertEqual(len(v._provider.calls), v.BACKOFF_AFTER)
        self.assertEqual(v.events, [])
        v.shutdown()

    def test_missing_dependency_disables_quietly(self):
        class Missing(FakeProvider):
            def synthesize(self, *a):
                raise vf.ProviderUnavailable("edge-tts is not installed.")
        v = make(provider=Missing())
        v.speak("anything")
        wait_idle(v)
        self.assertFalse(v._enabled)
        self.assertFalse(v.speak("again"))
        v.shutdown()

    def test_no_audio_player_is_harmless(self):
        v = make()
        v._player_cmd = lambda path: None
        v.speak("no player here")
        self.assertTrue(wait_idle(v))
        v.shutdown()

    def test_disabled_is_silent(self):
        v = make()
        v.set_enabled(False)
        self.assertFalse(v.speak("muted"))
        self.assertEqual(v._provider.calls, [])
        v.set_enabled(True)
        self.assertTrue(v.speak("unmuted"))
        wait_idle(v)
        v.shutdown()

    def test_templates_follow_user_language(self):
        v = make()
        v.speak_success(context="افتح الملف")
        wait_idle(v)
        v.speak_success(context="open the file")
        wait_idle(v)
        v.speak_error(context="افتح Firefox")
        wait_idle(v)
        langs = [c[1] for c in v._provider.calls]
        self.assertEqual(langs, ["ar", "en", "mixed"])
        v.shutdown()

    def test_clarification_uses_short_engine_text_else_template(self):
        v = make()
        v.speak_clarification("Which folder do you mean?", context="x")
        wait_idle(v)
        self.assertEqual(v._provider.calls[-1][0], "Which folder do you mean?")
        v.speak_clarification("long " * 100, context="open")
        wait_idle(v)
        self.assertIn(v._provider.calls[-1][0], vf.TEMPLATES["clarify"]["en"])
        v.shutdown()

    def test_concurrent_callers(self):
        v = make(play_seconds="0.05")
        threads = [threading.Thread(target=v.speak, args=(f"thread {i}",))
                   for i in range(10)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertTrue(wait_idle(v, 10))
        self.assertEqual(v._pending, 0)
        v.shutdown()

    def test_interrupt_flag(self):
        v = make(play_seconds="5")
        v.speak("long one")
        time.sleep(0.3)
        v.speak("urgent", interrupt=True)
        time.sleep(0.5)
        self.assertEqual([c[0] for c in v._provider.calls],
                         ["long one", "urgent"])
        v.stop_speaking()
        v.shutdown()


class GuiHooks(unittest.TestCase):
    """Run the real VoxyApp methods that were added/changed, against a stub
    tkinter (no display). Mock-based, not a real GUI run."""

    @classmethod
    def setUpClass(cls):
        class W:
            def __init__(self, *a, **k): pass
            def __getattr__(self, n): return lambda *a, **k: None
        tk = types.ModuleType("tkinter")
        for n in ("Tk", "Canvas", "Frame", "Label", "Entry", "StringVar",
                  "OptionMenu", "PhotoImage"):
            setattr(tk, n, type(n, (W,), {}))
        tk.TclError = Exception
        font = types.ModuleType("tkinter.font")
        font.families = lambda: []
        font.Font = W
        mb = types.ModuleType("tkinter.messagebox")
        tk.font, tk.messagebox = font, mb
        stubs = {"tkinter": tk, "tkinter.font": font, "tkinter.messagebox": mb}
        for name, attr in (("audio_service_AI", "listen_and_transcribe"),
                           ("command_understanding", "CommandUnderstanding"),
                           ("execution", "LinuxExecutor")):
            m = types.ModuleType(name)
            setattr(m, attr, lambda *a, **k: None)
            stubs[name] = m
        cls._patch = mock.patch.dict(sys.modules, stubs)
        cls._patch.start()
        sys.modules.pop("voxy_gui_test", None)
        import voxy_gui_test
        cls.gui = voxy_gui_test

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        sys.modules.pop("voxy_gui_test", None)

    def app(self):
        a = object.__new__(self.gui.VoxyApp)
        a.continuous_listening = True
        a._audio_busy = False
        a.current_page = "Home"
        a.ui_state = "processing"
        a._voice_last_command = ""
        a._voice_last_status = None
        a._voice_proc_token = None
        a.after_calls = []
        a.after = lambda ms, fn=None, *args: a.after_calls.append((ms, fn, args))
        a.started = []
        a.start_listening = lambda: a.started.append(1)
        return a

    def fake_voice(self, speaking=False):
        fv = mock.MagicMock()
        fv.is_speaking.return_value = speaking
        return mock.patch.object(self.gui, "voice_feedback", fv), fv

    def test_gui_imports_with_and_without_module(self):
        self.assertIsNotNone(self.gui.voice_feedback)
        a = self.app()
        with mock.patch.object(self.gui, "voice_feedback", None):
            self.assertIsNone(a._vf("speak", "x"))   # no module -> no crash
            a._voice_schedule_processing_hint("cmd")
        self.assertEqual(a.after_calls, [])

    def test_vf_swallows_exceptions(self):
        a = self.app()
        p, fv = self.fake_voice()
        fv.speak.side_effect = RuntimeError("boom")
        with p:
            self.assertIsNone(a._vf("speak", "x"))

    def test_result_routing(self):
        cases = [("Success", True, "speak_success"),
                 ("Failed", False, "speak_error"),
                 ("Needs Clarification", False, "speak_clarification")]
        for status, ok, expected in cases:
            a = self.app()
            a._voice_last_status = status
            a._voice_last_command = "افتح الملف"
            p, fv = self.fake_voice()
            with p:
                a._voice_announce_result(ok, "msg")
            getattr(fv, expected).assert_called_once()
            for other in ("speak_success", "speak_error", "speak_clarification"):
                if other != expected:
                    getattr(fv, other).assert_not_called()
            self.assertIsNone(a._voice_last_status)

    def test_resume_listening_waits_while_speaking(self):
        a = self.app()
        p, fv = self.fake_voice(speaking=True)
        with p:
            a._resume_listening()
        self.assertEqual(a.started, [])                       # mic NOT opened
        self.assertEqual(a.after_calls[0][0], 300)            # re-check later

    def test_resume_listening_unchanged_when_silent(self):
        a = self.app()
        p, fv = self.fake_voice(speaking=False)
        with p:
            a._resume_listening()
        self.assertEqual(a.started, [1])                      # original path
        a2 = self.app()
        a2.continuous_listening = False
        with p:
            a2._resume_listening()
        self.assertEqual(a2.started, [])                      # original rule

    def test_resume_listening_without_voice_module(self):
        a = self.app()
        with mock.patch.object(self.gui, "voice_feedback", None):
            a._resume_listening()
        self.assertEqual(a.started, [1])

    def test_processing_hint_only_when_still_processing(self):
        a = self.app()
        p, fv = self.fake_voice()
        with p:
            a._voice_schedule_processing_hint("cmd")
            ms, fn, args = a.after_calls[0]
            self.assertEqual(ms, 6000)
            a.ui_state = "idle"                               # finished fast
            fn(*args)
            fv.speak_status.assert_not_called()
            a.ui_state = "processing"
            fn(*args)
            fv.speak_status.assert_called_once()
            a._voice_schedule_processing_hint("new")          # newer command
            fn(*args)                                         # stale token
            self.assertEqual(fv.speak_status.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
