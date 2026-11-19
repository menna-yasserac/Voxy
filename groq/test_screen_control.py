"""Automatic tests for screen_control.py and the click logic in execution.py.

Run from the folder that contains the files:
    python3 -m unittest test_screen_control -v

The OCR tests are skipped automatically when Tesseract / Pillow are missing.
"""
import glob
import shutil
import sys
import types
import unittest
from unittest import mock

import screen_control as sc

sys.modules.setdefault("groq", types.SimpleNamespace(Groq=object))


def word(text, left, top, width=40, height=12):
    return {"text": text, "left": left, "top": top, "width": width, "height": height}


# ---------------------------------------------------------------- text helpers
class TextHelpers(unittest.TestCase):
    def test_normalize_english(self):
        self.assertEqual(sc.normalize_label("  Sign-In!  "), "sign in")

    def test_normalize_arabic_marks_and_letters(self):
        self.assertEqual(sc.normalize_label("إِفْتَحْ"), sc.normalize_label("افتح"))
        self.assertEqual(sc.normalize_label("أحمد"), sc.normalize_label("احمد"))

    def test_strip_ui_words(self):
        self.assertEqual(sc.strip_ui_words("the Save button"), "save")
        self.assertEqual(sc.strip_ui_words("زر Continue"), "continue")
        self.assertEqual(sc.strip_ui_words("button"), "button")  # never empty

    def test_is_here(self):
        for text in ("here", "Here", "هنا", "this", "ده"):
            self.assertTrue(sc.is_here(text), text)
        self.assertFalse(sc.is_here("Save"))

    def test_is_dangerous(self):
        for text in ("Delete", "delete file", "Send", "Pay now", "Sign out",
                     "امسح", "حذف", "ارسال", "إرسال", "تسجيل الخروج"):
            self.assertTrue(sc.is_dangerous(text), text)
        for text in ("Save", "Cancel", "Continue with Google", "Settings", "فتح"):
            self.assertFalse(sc.is_dangerous(text), text)


# ---------------------------------------------------------------- matching
class Matching(unittest.TestCase):
    def test_finds_phrase_and_centre(self):
        words = [word("Continue", 100, 100, 60), word("with", 170, 100, 30),
                 word("Google", 210, 100, 50)]
        matches = sc.match_label(words, "Continue with Google")
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]["whole_line"])
        self.assertAlmostEqual(matches[0]["x"], 180, delta=1)
        self.assertAlmostEqual(matches[0]["y"], 106, delta=1)

    def test_fuzzy_typo(self):
        words = [word("Continue", 100, 100, 60), word("with", 170, 100, 30),
                 word("Google", 210, 100, 50)]
        self.assertTrue(sc.match_label(words, "Contnue with Gogle"))

    def test_short_label_must_be_exact(self):
        self.assertTrue(sc.match_label([word("OK", 10, 10)], "OK"))
        self.assertFalse(sc.match_label([word("OX", 10, 10)], "OK"))

    def test_whole_line_wins_over_partial(self):
        words = [word("Save", 100, 100), word("Save", 400, 300, 40),
                 word("As", 450, 300, 20)]
        best, reason = sc.pick_match(sc.match_label(words, "Save"))
        self.assertIsNone(reason)
        self.assertAlmostEqual(best["x"], 120, delta=1)
        self.assertTrue(best["whole_line"])

    def test_two_identical_buttons_are_ambiguous(self):
        words = [word("Cancel", 100, 100), word("Cancel", 600, 400)]
        best, reason = sc.pick_match(sc.match_label(words, "Cancel"))
        self.assertIsNone(best)
        self.assertEqual(reason, "ambiguous")

    def test_not_found(self):
        best, reason = sc.pick_match(sc.match_label([word("File", 1, 1)], "Save"))
        self.assertIsNone(best)
        self.assertEqual(reason, "not_found")

    def test_word_inside_long_sentence_is_ignored(self):
        sentence = "Please remember to save your work before closing the window".split()
        words = [word(w, 10 + i * 50, 600, 45) for i, w in enumerate(sentence)]
        self.assertEqual(sc.match_label(words, "save"), [])

    def test_arabic_label(self):
        words = [word("تسجيل", 200, 50, 50), word("الدخول", 130, 50, 60)]
        self.assertTrue(sc.match_label(words, "تسجيل الدخول"))


# ---------------------------------------------------------------- OCR on real images
def _find_font():
    for path in glob.glob("/usr/share/fonts/**/LiberationSans-Regular.ttf", recursive=True):
        return path
    return None


def _ocr_available():
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        return bool(shutil.which("tesseract")) and _find_font() is not None
    except ImportError:
        return False


@unittest.skipUnless(_ocr_available(), "Tesseract / Pillow / font not available")
class OcrOnImages(unittest.TestCase):
    @staticmethod
    def make_page(items, dark=False):
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(_find_font(), 16)
        bg = (32, 33, 36) if dark else (255, 255, 255)
        fill = (60, 64, 67) if dark else (232, 234, 237)
        fg = (232, 234, 237) if dark else (32, 33, 36)
        image = Image.new("RGB", (1366, 768), bg)
        draw = ImageDraw.Draw(image)
        for text, x, y in items:
            width = draw.textlength(text, font=font)
            draw.rounded_rectangle([x, y, x + width + 36, y + 38], radius=6, fill=fill)
            draw.text((x + 18, y + 9), text, font=font, fill=fg)
        return image

    ITEMS = [("Save", 300, 300), ("Cancel", 560, 300), ("OK", 900, 300),
             ("Sign in", 300, 480), ("Continue with Google", 300, 400)]

    def check_page(self, dark):
        page = self.make_page(self.ITEMS, dark=dark)
        controller = sc.ScreenController(langs="eng")
        for label, x, y in self.ITEMS:
            matches, _ = controller.find_text(label, image=page)
            best, reason = sc.pick_match(matches)
            self.assertIsNotNone(best, f"{label}: {reason}")
            self.assertLess(abs(best["x"] - (x + 20)), 120, label)
            self.assertLess(abs(best["y"] - (y + 19)), 25, label)

    def test_light_theme(self):
        self.check_page(dark=False)

    def test_dark_theme(self):
        self.check_page(dark=True)

    def test_missing_text(self):
        page = self.make_page(self.ITEMS)
        matches, _ = sc.ScreenController(langs="eng").find_text("Nothing here", image=page)
        self.assertEqual(matches, [])

    def test_click_text_uses_found_position(self):
        page = self.make_page(self.ITEMS)
        with mock.patch.object(sc, "click_xy", return_value=(True, "Clicked.")) as click:
            ok, message = sc.ScreenController(langs="eng").click_text("Cancel", image=page)
        self.assertTrue(ok, message)
        x, y = click.call_args[0][:2]
        self.assertLess(abs(x - 603), 40)
        self.assertLess(abs(y - 318), 20)


# ---------------------------------------------------------------- click_text logic
class ClickTextLogic(unittest.TestCase):
    def controller_with(self, matches):
        controller = sc.ScreenController(langs="eng")
        controller.find_text = lambda label, image=None: (matches, None)
        return controller

    def match(self, whole=True, x=100, y=50):
        return {"score": 1.0, "whole_line": whole, "text": "Save",
                "line_text": "Save As" if not whole else "Save",
                "box": (80, 40, 120, 60), "x": x, "y": y}

    def test_not_found_message(self):
        ok, message = self.controller_with([]).click_text("Save")
        self.assertFalse(ok)
        self.assertIn("couldn't find", message)

    def test_ambiguous_does_not_click(self):
        matches = [self.match(x=100), self.match(x=600, y=400)]
        with mock.patch.object(sc, "click_xy") as click:
            ok, message = self.controller_with(matches).click_text("Save")
        self.assertFalse(ok)
        self.assertIn("more than one place", message)
        click.assert_not_called()

    def test_partial_match_refused_without_confirmation(self):
        with mock.patch.object(sc, "click_xy") as click:
            ok, _ = self.controller_with([self.match(whole=False)]).click_text("Save")
        self.assertFalse(ok)
        click.assert_not_called()

    def test_partial_match_confirmed(self):
        with mock.patch.object(sc, "click_xy", return_value=(True, "ok")) as click:
            ok, _ = self.controller_with([self.match(whole=False)]).click_text(
                "Save", confirm_callback=lambda q: True)
        self.assertTrue(ok)
        click.assert_called_once()

    def test_partial_match_declined(self):
        with mock.patch.object(sc, "click_xy") as click:
            ok, message = self.controller_with([self.match(whole=False)]).click_text(
                "Save", confirm_callback=lambda q: False)
        self.assertFalse(ok)
        self.assertEqual(message, "Click cancelled.")
        click.assert_not_called()

    def test_scale_is_applied(self):
        controller = self.controller_with([self.match(x=200, y=100)])
        controller.scale = 2.0
        with mock.patch.object(sc, "click_xy", return_value=(True, "ok")) as click:
            controller.click_text("Save")
        self.assertEqual(click.call_args[0][:2], (100.0, 50.0))


# ---------------------------------------------------------------- mouse backends
class MouseBackends(unittest.TestCase):
    def run_click(self, session, tools, call=lambda: sc.click_xy(10, 20)):
        calls = []

        def fake_run(args, timeout=10):
            calls.append(args)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(sc, "session_type", return_value=session), \
             mock.patch.object(sc.shutil, "which", side_effect=lambda n: n if n in tools else None), \
             mock.patch.object(sc, "_run", side_effect=fake_run):
            result = call()
        return result, calls

    def test_x11_uses_xdotool(self):
        (ok, _), calls = self.run_click("x11", {"xdotool"})
        self.assertTrue(ok)
        self.assertEqual(calls[0][:2], ["xdotool", "mousemove"])
        self.assertEqual(calls[1], ["xdotool", "click", "1"])

    def test_x11_double_and_right(self):
        (_, _), calls = self.run_click(
            "x11", {"xdotool"}, lambda: sc.click_xy(1, 2, button="right", double=True))
        self.assertEqual(calls[1], ["xdotool", "click", "--repeat", "2", "--delay", "80", "3"])

    def test_wayland_uses_ydotool(self):
        (ok, _), calls = self.run_click("wayland", {"ydotool", "xdotool"})
        self.assertTrue(ok)
        self.assertEqual(calls[0][0], "ydotool")
        self.assertEqual(calls[1], ["ydotool", "click", "0xC0"])

    def test_wayland_without_ydotool_fails_honestly(self):
        (ok, message), calls = self.run_click("wayland", {"xdotool"})
        self.assertFalse(ok)
        self.assertIn("ydotool", message)
        self.assertEqual(calls, [])   # never pretends to click with xdotool

    def test_click_here_x11(self):
        (ok, _), calls = self.run_click("x11", {"xdotool"}, sc.click_here)
        self.assertTrue(ok)
        self.assertEqual(calls, [["xdotool", "click", "1"]])

    def test_missing_xdotool(self):
        (ok, message), _ = self.run_click("x11", set())
        self.assertFalse(ok)
        self.assertIn("xdotool", message)


# ---------------------------------------------------------------- executor integration
class ExecutorClick(unittest.TestCase):
    def setUp(self):
        import execution
        self.execution = execution
        self.executor = execution.LinuxExecutor()
        self.executor.screen = mock.Mock()
        self.executor.screen.click_here.return_value = (True, "Clicked at the mouse position.")
        self.executor.screen.click_text.return_value = (True, "Clicked 'Save' (found by reading the screen).")
        self.executor.atspi = mock.Mock()

    def click(self, data, confirm=None):
        return self.executor.click_element(data, confirm)

    def test_click_here(self):
        ok, message = self.click({"intent": "click_element", "target": "here"})
        self.assertTrue(ok)
        self.executor.screen.click_here.assert_called_once_with("left", False)
        self.executor.atspi.click.assert_not_called()

    def test_click_here_arabic(self):
        self.click({"intent": "click_element", "target": "هنا"})
        self.executor.screen.click_here.assert_called_once()

    def test_atspi_success_skips_ocr(self):
        self.executor.atspi.click.return_value = {"success": True, "message": "Clicked Save."}
        ok, message = self.click({"target": "Save"})
        self.assertTrue(ok)
        self.executor.screen.click_text.assert_not_called()

    def test_atspi_failure_falls_back_to_ocr(self):
        self.executor.atspi.click.return_value = {"success": False, "message": "not found"}
        ok, _ = self.click({"target": "Save"})
        self.assertTrue(ok)
        self.executor.screen.click_text.assert_called_once()

    def test_right_click_skips_atspi(self):
        self.click({"target": "Documents", "action": "right_click"})
        self.executor.atspi.click.assert_not_called()
        kwargs = self.executor.screen.click_text.call_args.kwargs
        self.assertEqual(kwargs["button"], "right")

    def test_double_click(self):
        self.click({"target": "Downloads", "action": "double_click"})
        kwargs = self.executor.screen.click_text.call_args.kwargs
        self.assertTrue(kwargs["double"])

    def test_dangerous_requires_confirmation(self):
        ok, message = self.click({"target": "Delete"})
        self.assertFalse(ok)
        self.assertIn("requires confirmation", message)
        self.executor.atspi.click.assert_not_called()
        self.executor.screen.click_text.assert_not_called()

    def test_dangerous_declined(self):
        ok, message = self.click({"target": "Send"}, confirm=lambda q: False)
        self.assertFalse(ok)
        self.assertEqual(message, "Click cancelled.")
        self.executor.screen.click_text.assert_not_called()

    def test_dangerous_confirmed(self):
        self.executor.atspi.click.return_value = {"success": True, "message": "Clicked."}
        ok, _ = self.click({"target": "Delete"}, confirm=lambda q: True)
        self.assertTrue(ok)

    def test_ui_words_are_removed_before_ocr(self):
        self.executor.atspi.click.return_value = {"success": False, "message": "x"}
        self.click({"target": "the Save button"})
        self.assertEqual(self.executor.screen.click_text.call_args.args[0], "save")

    def test_explicit_coordinates(self):
        with mock.patch("screen_control.click_xy", return_value=(True, "ok")) as click:
            ok, _ = self.click({"intent": "click", "x": 10, "y": 20})
        self.assertTrue(ok)
        click.assert_called_once_with(10, 20, button="left", double=False)

    def test_execute_one_passes_confirm_callback(self):
        asked = []
        result = self.executor.execute_one(
            {"intent": "click_element", "target": "Delete"},
            confirm_callback=lambda q: asked.append(q) or False)
        self.assertTrue(asked)
        self.assertFalse(result[0] if isinstance(result, tuple) else result.get("success", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
