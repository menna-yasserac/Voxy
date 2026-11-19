"""Voxy screen control: find something on the screen by its text and click it.

How it fits in
--------------
execution.py first tries AT-SPI (the accessibility tree), which is the most
accurate way to click a button by name. When that fails, this module takes over:

    1. take a screenshot,
    2. read the words on it with OCR (Tesseract),
    3. find the words the user asked for,
    4. move the mouse to the middle of those words and click.

It also handles "click here" (click where the mouse pointer already is).

Requirements (Ubuntu):
    sudo apt install tesseract-ocr tesseract-ocr-ara xdotool scrot
    pip install pytesseract pillow
    # Wayland sessions also need:  sudo apt install ydotool  (+ ydotoold running)
    # and a screenshot tool: gnome-screenshot (GNOME) / grim (wlroots) / spectacle (KDE)

Self test (no Voxy needed):
    python3 screen_control.py --check
    python3 screen_control.py --find "Save"
    python3 screen_control.py --click "Save"
    python3 screen_control.py --image some_screenshot.png --find "Save"
"""

import difflib
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata


# =============================================================
# TEXT HELPERS
# =============================================================

_ARABIC_MARKS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")

_ARABIC_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ؤ": "و",
    "ة": "ه",
})

# Words people say that are not part of the text written on the element.
UI_WORDS = {
    "button", "icon", "link", "tab", "option", "the", "a", "an",
    "زر", "الزر", "لينك", "الرابط", "رابط", "ايقونه", "الايقونه",
}

# "click here" means: click where the mouse pointer is.
HERE_WORDS = {"here", "this", "that", "هنا", "ده", "دي", "هذا", "هذه"}


def normalize_label(text):
    """Lower-case, remove punctuation / Arabic diacritics, unify Arabic letters."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = _ARABIC_MARKS.sub("", text)
    text = text.translate(_ARABIC_MAP)
    text = text.casefold()
    text = text.replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_ui_words(label):
    """'the Save button' -> 'save' (only if something is left)."""
    tokens = normalize_label(label).split()
    kept = [t for t in tokens if t not in UI_WORDS]
    return " ".join(kept) if kept else " ".join(tokens)


def is_here(label):
    return normalize_label(label) in {normalize_label(w) for w in HERE_WORDS}


# Clicking these can cause damage, so the executor asks for confirmation first.
_DANGEROUS_WORDS = {
    "delete", "remove", "erase", "format", "uninstall", "wipe", "send",
    "pay", "purchase", "buy", "checkout", "submit", "reset",
    "حذف", "مسح", "امسح", "ازاله", "إزالة", "ارسال", "إرسال",
    "دفع", "شراء", "اشتري", "تهيئة", "افراغ", "إفراغ",
}
_DANGEROUS_PHRASES = {
    "sign out", "log out", "logout", "place order", "empty trash",
    "تسجيل الخروج", "تاكيد الدفع", "تأكيد الدفع",
}
_DANGEROUS_WORDS_N = {normalize_label(w) for w in _DANGEROUS_WORDS}
_DANGEROUS_PHRASES_N = {normalize_label(p) for p in _DANGEROUS_PHRASES}


def is_dangerous(label):
    normalized = normalize_label(label)
    tokens = set(normalized.split())
    if tokens & _DANGEROUS_WORDS_N:
        return True
    return any(phrase in normalized for phrase in _DANGEROUS_PHRASES_N)


# =============================================================
# SESSION / SUBPROCESS HELPERS
# =============================================================

def session_type():
    """Return 'wayland', 'x11' or 'unknown'."""
    kind = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if kind in ("wayland", "x11"):
        return kind
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _run(args, timeout=10):
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


class ScreenError(Exception):
    """Raised with a message that is safe to show to the user."""


# =============================================================
# SCREENSHOT
# =============================================================

def _capture_backends(session):
    wayland = [
        ("grim", lambda p: ["grim", p]),
        ("gnome-screenshot", lambda p: ["gnome-screenshot", "-f", p]),
        ("spectacle", lambda p: ["spectacle", "-b", "-n", "-f", "-o", p]),
    ]
    x11 = [
        ("scrot", lambda p: ["scrot", "-o", p]),
        ("maim", lambda p: ["maim", p]),
        ("import", lambda p: ["import", "-window", "root", p]),
        ("gnome-screenshot", lambda p: ["gnome-screenshot", "-f", p]),
    ]
    if session == "wayland":
        return wayland
    if session == "x11":
        return x11
    return x11 + wayland


def capture_screen():
    """Return (PIL image, backend name). Raises ScreenError if nothing works."""
    try:
        from PIL import Image
    except ImportError:
        raise ScreenError("Pillow is not installed. Run: pip install pillow")

    tried = []

    for name, build in _capture_backends(session_type()):
        if not shutil.which(name):
            continue

        fd, path = tempfile.mkstemp(suffix=".png", prefix="voxy_screen_")
        os.close(fd)

        try:
            result = _run(build(path), timeout=15)

            if result and result.returncode == 0 and os.path.getsize(path) > 0:
                image = Image.open(path).convert("RGB")
                image.load()
                return image, name

            tried.append(name)

        except Exception:
            tried.append(name)

        finally:
            try:
                os.remove(path)  # do not leave screenshots on disk
            except OSError:
                pass

    # Last resort: Pillow's own grabber (works on X11).
    try:
        from PIL import ImageGrab
        image = ImageGrab.grab().convert("RGB")
        return image, "PIL.ImageGrab"
    except Exception:
        pass

    if session_type() == "wayland":
        hint = "sudo apt install gnome-screenshot (GNOME) or grim (wlroots)"
    else:
        hint = "sudo apt install scrot"

    failed = f" (failed: {', '.join(tried)})" if tried else ""
    raise ScreenError(f"Could not take a screenshot{failed}. Install: {hint}")


# =============================================================
# OCR
# =============================================================

_LANG_CACHE = {}


def default_ocr_languages():
    """eng+ara when the Arabic model is installed, otherwise eng."""
    if "langs" in _LANG_CACHE:
        return _LANG_CACHE["langs"]

    langs = "eng"

    try:
        import pytesseract
        available = set(pytesseract.get_languages(config=""))
        if "ara" in available and "eng" in available:
            langs = "eng+ara"
        elif "ara" in available:
            langs = "ara"
    except Exception:
        pass

    _LANG_CACHE["langs"] = langs
    return langs


def ocr_words(image, langs, psm=11, mult=1.0, min_conf=30):
    """Read all words from the image. Returns a list of word dicts."""
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image
    except ImportError:
        raise ScreenError(
            "OCR is not installed. Run: sudo apt install tesseract-ocr "
            "&& pip install pytesseract pillow"
        )

    # Small UI text reads much better when enlarged.
    width = image.width
    base = 2.0 if width <= 1920 else (1.5 if width <= 2560 else 1.0)
    factor = base * mult

    work = image
    if factor != 1.0:
        work = image.resize(
            (int(image.width * factor), int(image.height * factor)),
            Image.LANCZOS
        )

    try:
        data = pytesseract.image_to_data(
            work,
            lang=langs,
            config=f"--psm {psm}",
            output_type=Output.DICT
        )
    except pytesseract.TesseractNotFoundError:
        raise ScreenError(
            "Tesseract is not installed. Run: sudo apt install tesseract-ocr"
        )
    except pytesseract.TesseractError as error:
        raise ScreenError(f"OCR failed: {error}")

    words = []

    for i, text in enumerate(data["text"]):
        text = (text or "").strip()

        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1

        if not text or conf < min_conf:
            continue

        words.append({
            "text": text,
            "left": data["left"][i] / factor,
            "top": data["top"][i] / factor,
            "width": data["width"][i] / factor,
            "height": data["height"][i] / factor,
        })

    return words


def group_lines(words):
    """Group words that sit next to each other on the same row."""
    lines = []

    for word in sorted(words, key=lambda w: (w["top"], w["left"])):
        cy = word["top"] + word["height"] / 2
        placed = False

        for line in lines:
            last = line[-1]
            last_cy = last["top"] + last["height"] / 2
            height = max(word["height"], last["height"], 1)
            gap = word["left"] - (last["left"] + last["width"])

            if abs(cy - last_cy) < 0.5 * height and -height <= gap <= 1.8 * height:
                line.append(word)
                placed = True
                break

        if not placed:
            lines.append([word])

    for line in lines:
        line.sort(key=lambda w: w["left"])

    return lines


def _box(words):
    left = min(w["left"] for w in words)
    top = min(w["top"] for w in words)
    right = max(w["left"] + w["width"] for w in words)
    bottom = max(w["top"] + w["height"] for w in words)
    return left, top, right, bottom


def _threshold(target):
    size = len(target.replace(" ", ""))
    if size <= 3:
        return 1.0     # short labels such as "OK" must match exactly
    if size <= 5:
        return 0.9
    return 0.85


def match_label(words, label):
    """Find the words of `label` in the OCR words. Returns match dicts."""
    target = normalize_label(label)
    if not target:
        return []

    n_tokens = len(target.split())
    limit = _threshold(target)
    has_arabic = bool(re.search(r"[\u0600-\u06FF]", target))
    found = []

    for line in group_lines(words):
        normalized = [normalize_label(w["text"]) for w in line]
        usable = [i for i, text in enumerate(normalized) if text]

        if not usable:
            continue

        line_words = [line[i] for i in usable]
        line_text = [normalized[i] for i in usable]
        count = len(line_words)

        for size in range(max(1, n_tokens - 1), n_tokens + 2):
            for start in range(0, count - size + 1):
                window_text = line_text[start:start + size]
                candidates = [" ".join(window_text)]

                if has_arabic:
                    candidates.append(" ".join(reversed(window_text)))

                ratio = 0.0
                for candidate in candidates:
                    ratio = max(
                        ratio,
                        difflib.SequenceMatcher(None, candidate, target).ratio(),
                        difflib.SequenceMatcher(
                            None,
                            candidate.replace(" ", ""),
                            target.replace(" ", "")
                        ).ratio()
                    )

                if ratio < limit:
                    continue

                # A word inside a long sentence is normal text, not a button.
                if size < count and count > n_tokens + 4:
                    continue

                score = ratio
                if size == count:
                    score += 0.02     # the text is the whole line: likely a button
                if size == n_tokens:
                    score += 0.005

                left, top, right, bottom = _box(line_words[start:start + size])

                found.append({
                    "whole_line": size == count,
                    "line_text": " ".join(w["text"] for w in line_words),
                    "score": score,
                    "text": " ".join(w["text"] for w in line_words[start:start + size]),
                    "box": (left, top, right, bottom),
                    "x": (left + right) / 2,
                    "y": (top + bottom) / 2,
                })

    return dedupe_matches(found)


def dedupe_matches(found):
    """Remove overlapping duplicates, keeping the best score."""
    found = sorted(found, key=lambda m: -m["score"])
    unique = []

    for match in found:
        too_close = any(
            abs(match["x"] - kept["x"]) < 0.6 * (kept["box"][2] - kept["box"][0])
            and abs(match["y"] - kept["y"]) < 0.8 * (kept["box"][3] - kept["box"][1])
            for kept in unique
        )
        if not too_close:
            unique.append(match)

    return unique


def pick_match(matches):
    """Return (match, reason). reason is 'not_found' or 'ambiguous' on failure."""
    if not matches:
        return None, "not_found"

    ordered = sorted(matches, key=lambda m: -m["score"])
    best = ordered[0]

    for other in ordered[1:]:
        if other["score"] < best["score"] - 0.015:
            break

        distance = abs(other["x"] - best["x"]) + abs(other["y"] - best["y"])
        if distance > 25:
            return None, "ambiguous"

    return best, None


# =============================================================
# MOUSE
# =============================================================

_XDO_BUTTON = {"left": "1", "middle": "2", "right": "3"}
_YDO_BUTTON = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}


def _wayland_pointer_help():
    return (
        "Clicking on Wayland needs ydotool: sudo apt install ydotool "
        "and start ydotoold (or log in with 'Ubuntu on Xorg')."
    )


def _click_current_position(button="left", double=False):
    session = session_type()

    if session == "wayland":
        if not shutil.which("ydotool"):
            return False, _wayland_pointer_help()

        code = _YDO_BUTTON.get(button, "0xC0")
        for _ in range(2 if double else 1):
            result = _run(["ydotool", "click", code])
            if not result or result.returncode != 0:
                return False, "ydotool click failed. Is ydotoold running?"
        return True, "Clicked."

    if not shutil.which("xdotool"):
        return False, "xdotool is not installed. Run: sudo apt install xdotool"

    args = ["xdotool", "click"]
    if double:
        args += ["--repeat", "2", "--delay", "80"]
    args.append(_XDO_BUTTON.get(button, "1"))

    result = _run(args)
    if result and result.returncode == 0:
        return True, "Clicked."
    return False, "xdotool click failed."


def click_here(button="left", double=False):
    """Click at the current mouse pointer position."""
    ok, message = _click_current_position(button, double)
    if ok:
        return True, "Clicked at the mouse position."
    return False, message


def click_xy(x, y, button="left", double=False):
    """Move the mouse to (x, y) in screen pixels and click."""
    x, y = int(round(x)), int(round(y))
    session = session_type()

    if session == "wayland":
        if not shutil.which("ydotool"):
            return False, _wayland_pointer_help()

        result = _run(["ydotool", "mousemove", "--absolute", "-x", str(x), "-y", str(y)])
        if not result or result.returncode != 0:
            return False, "ydotool could not move the mouse. Is ydotoold running?"

        return _click_current_position(button, double)

    if not shutil.which("xdotool"):
        return False, "xdotool is not installed. Run: sudo apt install xdotool"

    result = _run(["xdotool", "mousemove", str(x), str(y)])
    if not result or result.returncode != 0:
        return False, "xdotool could not move the mouse."

    return _click_current_position(button, double)


# =============================================================
# CONTROLLER
# =============================================================

class ScreenController:
    def __init__(self, langs=None, scale=None):
        self.langs = langs or os.environ.get("VOXY_OCR_LANGS") or None

        try:
            self.scale = float(
                scale or os.environ.get("VOXY_SCREEN_SCALE") or 1
            )
        except ValueError:
            self.scale = 1.0

    def _langs(self):
        return self.langs or default_ocr_languages()

    # (invert colours, tesseract page mode, size multiplier)
    # Tesseract is inconsistent on sparse screen text, so the passes are
    # tried one by one until a confident whole-line match is found.
    _PASSES = [
        (False, 11, 1.0),
        (False, 12, 1.0),
        (False, 12, 1.5),
        (False, 11, 1.5),
        (True, 11, 1.0),
        (True, 12, 1.0),
    ]

    def find_text(self, label, image=None):
        """Return (matches, image_used). Reads the screen if no image is given."""
        label = strip_ui_words(label)

        if image is None:
            image, _ = capture_screen()

        langs = self._langs()
        inverted = None
        collected = []

        for invert, psm, mult in self._PASSES:
            source = image

            if invert:
                if inverted is None:
                    from PIL import ImageOps
                    inverted = ImageOps.invert(image.convert("L")).convert("RGB")
                source = inverted

            words = ocr_words(source, langs, psm=psm, mult=mult)
            collected = dedupe_matches(collected + match_label(words, label))

            if any(m["whole_line"] and m["score"] >= 1.0 for m in collected):
                break

        return collected, image

    def click_text(self, label, button="left", double=False, image=None,
                   confirm_callback=None):
        """Find `label` on the screen and click it. Returns (success, message)."""
        label = str(label or "").strip()

        if not label:
            return False, "No element name was given."

        try:
            matches, _ = self.find_text(label, image=image)
        except ScreenError as error:
            return False, str(error)

        match, reason = pick_match(matches)

        if reason == "not_found":
            return False, f"I couldn't find '{label}' on the screen."

        if reason == "ambiguous":
            return False, (
                f"I found '{label}' in more than one place. "
                "Please say a longer or more specific name."
            )

        # The words were found only as part of a longer text (for example
        # "Save" inside "Save As"). Ask before clicking something uncertain.
        if not match["whole_line"]:
            question = (
                f"Click '{match['text']}' "
                f"(part of '{match['line_text']}')?"
            )

            if confirm_callback is None:
                return False, (
                    f"I only found '{label}' inside '{match['line_text']}'. "
                    "Please say the full name."
                )

            try:
                approved = confirm_callback(question)
            except Exception:
                approved = False

            if not approved:
                return False, "Click cancelled."

        ok, message = click_xy(
            match["x"] / self.scale,
            match["y"] / self.scale,
            button=button,
            double=double
        )

        if not ok:
            return False, message

        return True, f"Clicked '{match['text']}' (found by reading the screen)."

    def click_here(self, button="left", double=False):
        return click_here(button, double)

    def check_environment(self):
        """Return a list of (item, ok, detail) lines for a quick diagnosis."""
        report = []
        session = session_type()
        report.append(("Session type", session != "unknown", session))

        try:
            import PIL
            report.append(("Pillow", True, PIL.__version__))
        except ImportError:
            report.append(("Pillow", False, "pip install pillow"))

        try:
            import pytesseract
            version = pytesseract.get_tesseract_version()
            langs = default_ocr_languages()
            report.append(("Tesseract", True, f"{version}, languages used: {langs}"))
            if "ara" not in langs:
                report.append((
                    "Arabic OCR", False,
                    "sudo apt install tesseract-ocr-ara"
                ))
        except Exception:
            report.append((
                "Tesseract / pytesseract", False,
                "sudo apt install tesseract-ocr && pip install pytesseract"
            ))

        shots = [n for n, _ in _capture_backends(session) if shutil.which(n)]
        report.append((
            "Screenshot tool", bool(shots),
            ", ".join(shots) if shots else "none found"
        ))

        if session == "wayland":
            report.append((
                "ydotool (mouse on Wayland)",
                bool(shutil.which("ydotool")),
                "found" if shutil.which("ydotool") else _wayland_pointer_help()
            ))
        else:
            report.append((
                "xdotool (mouse on X11)",
                bool(shutil.which("xdotool")),
                "found" if shutil.which("xdotool") else "sudo apt install xdotool"
            ))

        try:
            image, backend = capture_screen()
            report.append((
                "Test screenshot", True,
                f"{image.width}x{image.height} via {backend} "
                f"(if your real resolution is different, set VOXY_SCREEN_SCALE)"
            ))
        except ScreenError as error:
            report.append(("Test screenshot", False, str(error)))

        return report


# =============================================================
# COMMAND LINE SELF TEST
# =============================================================

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="Voxy screen control self test")
    parser.add_argument("--check", action="store_true", help="check the environment")
    parser.add_argument("--find", metavar="TEXT", help="find TEXT on screen, do not click")
    parser.add_argument("--click", metavar="TEXT", help="find TEXT on screen and click it")
    parser.add_argument("--here", action="store_true", help="click at the mouse position")
    parser.add_argument("--image", metavar="FILE", help="use this image instead of the screen")
    parser.add_argument("--save-debug", metavar="FILE", help="save an image with the matches drawn")
    args = parser.parse_args()

    controller = ScreenController()

    if args.check:
        for item, ok, detail in controller.check_environment():
            print(f"[{'OK' if ok else '!!'}] {item}: {detail}")
        return

    image = None
    if args.image:
        from PIL import Image
        image = Image.open(args.image).convert("RGB")

    if args.find:
        matches, used = controller.find_text(args.find, image=image)
        if not matches:
            print("No match.")
        for m in sorted(matches, key=lambda m: -m["score"]):
            print(f"score={m['score']:.2f} text='{m['text']}' "
                  f"center=({m['x']:.0f},{m['y']:.0f}) box={tuple(int(v) for v in m['box'])}")

        if args.save_debug:
            from PIL import ImageDraw
            canvas = used.copy()
            draw = ImageDraw.Draw(canvas)
            for m in matches:
                draw.rectangle(m["box"], outline=(255, 0, 0), width=3)
            canvas.save(args.save_debug)
            print("Saved", args.save_debug)
        return

    if args.click:
        print(controller.click_text(args.click, image=image))
        return

    if args.here:
        print(controller.click_here())
        return

    parser.print_help()


if __name__ == "__main__":
    _main()
