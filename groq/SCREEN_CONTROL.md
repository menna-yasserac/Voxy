# Voxy — Screen Control (click by name / click here)

Lets the user say things like **"دوس هنا"**, **"click Save"**, **"اضغط على Sign in"**, **"right click Documents"**.

## How it works

`execution.py → click_element()` tries these steps in order and stops at the first that works:

| # | Step | Used for |
|---|------|----------|
| 1 | **Pointer position** | `here` / `هنا` / `click` with no name: clicks where the mouse already is |
| 2 | **Coordinates** | the user said explicit numbers (`click at 500 300`) |
| 3 | **AT-SPI** (`atspi_controller.py`) | button names from the accessibility tree, the most accurate |
| 4 | **Screen reading (OCR)** — `screen_control.py` | screenshot → Tesseract → find the words → click their centre |

Safety rules built in:
- Words like **Delete, Send, Pay, Sign out, حذف, ارسال, دفع...** always ask for confirmation first.
- If the same name appears **twice** on screen, Voxy refuses and asks for a more specific name.
- If the name is found only **inside a longer text** (e.g. `Save` inside `Save As`), Voxy asks before clicking.
- Words inside normal sentences are ignored.
- Screenshots are deleted right after OCR.

## Files

| File | What changed |
|------|--------------|
| `screen_control.py` | **New.** Screenshot, OCR, matching, mouse click (Xorg + Wayland) and a self-test command line |
| `execution.py` | New `click_element` (steps above). Also contains the delete fix from before |
| `command_understanding.py` | Prompt rules for `here`, visible text, right / double click. Also contains the name-case fix |
| `test_screen_control.py` | 41 automatic tests |

## Install (Ubuntu)

```bash
sudo apt install tesseract-ocr tesseract-ocr-ara xdotool scrot
pip install pytesseract pillow
```

Wayland session (Ubuntu default) also needs:

```bash
sudo apt install ydotool gnome-screenshot     # GNOME
# start the ydotool daemon (needed for mouse control)
```

Simplest for the project: at the login screen choose **"Ubuntu on Xorg"** — then `xdotool` and `scrot` are enough.
Check your session with `echo $XDG_SESSION_TYPE`.

## Test it before using Voxy

```bash
python3 screen_control.py --check                 # environment report: every line should be [OK]
python3 screen_control.py --find "Files"          # find a visible word, no click
python3 screen_control.py --find "Files" --save-debug /tmp/debug.png   # draws a box on the match
python3 screen_control.py --click "Files"         # find and click
python3 screen_control.py --here                  # click at the mouse position
python3 screen_control.py --image shot.png --find "Save"   # test on a saved screenshot (no display needed)
python3 -m unittest test_screen_control -v        # automatic tests
```

## Settings (environment variables)

| Variable | Meaning | Default |
|----------|---------|---------|
| `VOXY_OCR_LANGS` | Tesseract languages, e.g. `eng+ara` | `eng+ara` if Arabic is installed, else `eng` |
| `VOXY_SCREEN_SCALE` | Divide OCR coordinates by this number (HiDPI / fractional scaling) | `1` |

## Known limits

- Icons with no text can only be clicked if AT-SPI knows their name.
- Tiny text, low contrast and very stylised fonts may not be read. Up to 6 OCR passes are tried, so a miss can take 10+ seconds.
- Arabic OCR needs `tesseract-ocr-ara` and is less accurate than English.
- Only the main screen is supported. Multi-monitor and fractional scaling need checking on a real machine.
- On Wayland the mouse tool `ydotool` needs its daemon and `/dev/uinput` permission. Without it Voxy reports the problem instead of pretending to click.
