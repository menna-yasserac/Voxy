#!/usr/bin/env python3
"""
Voxy - Linux AI Assistant (new GUI)

Same backend as before (audio_service_AI, command_understanding, execution).
Only the GUI layer was rewritten: new look, animated logo, mic rings,
live level meter, rounded buttons, same Home / History / Settings pages.

Optional: `pip install sounddevice` for a REAL microphone level on the
animations. Without it the animation falls back to a smooth simulated level.
"""

import math
import os
import random
import threading
import time
import traceback
from array import array
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

from audio_service_AI import listen_and_transcribe
from command_understanding import CommandUnderstanding
from execution import LinuxExecutor

try:
    import voice_feedback
except Exception:  # voice feedback is optional; Voxy works without it
    voice_feedback = None

try:
    import sounddevice as sd
except Exception:
    sd = None

# Set to False if reading the mic for the animation ever conflicts with
# audio_service_AI on your machine (the animation then uses a simulated level).
LIVE_MIC_LEVEL = True

# Example commands shown as chips under the input. Replace with your own.
CHIPS = ["Open Firefox", "Create a folder", "What time is it?"]

# =====================================
# COLORS
# =====================================

ORANGE = "#F97316"
DEEP = "#D9480F"
DEEP_HOVER = "#EA5A14"
MIC = "#EA580C"
GREEN = "#34D399"
RED = "#F21F2B"

DARK = {
    "bg": "#0F0F14", "side": "#16161D", "side_line": "#23232E",
    "card": "#1B1B25", "line": "#2E2E3C", "field": "#17171F",
    "text": "#FFFFFF", "muted": "#B4B4C4", "hover": "#1E1E28",
    "chip_line": "#33333F", "toggle_on": "#2A2A36", "glow": "#2C1738",
}

LIGHT = {
    "bg": "#F3F3F5", "side": "#E9E9EC", "side_line": "#D5D5DB",
    "card": "#FFFFFF", "line": "#D5D5DB", "field": "#FFFFFF",
    "text": "#202126", "muted": "#5C5D63", "hover": "#DEDEE3",
    "chip_line": "#C9C9D1", "toggle_on": "#D5D5DB", "glow": "#F6D5E6",
}

STOPS = [(0.0, "#F97316"), (0.55, "#EC4899"), (1.0, "#A855F7")]
BAR_HEIGHTS = [24, 34, 46, 58, 70, 84, 96, 104, 104, 96, 84, 70, 58, 46, 34, 24]


def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def blend(fg, bg, alpha):
    """fg drawn over bg with the given alpha (0..1)."""
    f, b = _rgb(fg), _rgb(bg)
    return "#%02x%02x%02x" % tuple(
        int(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3)
    )


def grad(t):
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            return blend(c1, c0, (t - t0) / (t1 - t0))
    return STOPS[-1][1]


def rrect_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


# =====================================
# SMALL WIDGETS
# =====================================

class RButton(tk.Canvas):
    """Rounded button drawn on a canvas."""

    def __init__(self, parent, text, command, w, h, fill, hover, fg, bg,
                 font, radius=14, outline="", anchor="center", padx=18):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._bw, self._bh, self._br = w, h, radius
        self._text, self._command = text, command
        self._fill, self._hover, self._fg = fill, hover, fg
        self._font, self._outline = font, outline
        self._anchor, self._padx = anchor, padx
        self._current = fill
        self._draw()
        self.bind("<Enter>", lambda e: self._paint_with(self._hover))
        self.bind("<Leave>", lambda e: self._paint_with(self._fill))
        self.bind("<ButtonRelease-1>", self._click)

    def _draw(self):
        self.delete("all")
        self.create_polygon(
            rrect_points(1, 1, self._bw - 1, self._bh - 1, self._br),
            smooth=True, fill=self._current,
            outline=self._outline, width=1
        )
        if self._anchor == "w":
            self.create_text(self._padx, self._bh / 2, text=self._text,
                             fill=self._fg, font=self._font, anchor="w")
        else:
            self.create_text(self._bw / 2, self._bh / 2, text=self._text,
                             fill=self._fg, font=self._font)

    def _paint_with(self, color):
        self._current = color
        self._draw()

    def _click(self, event):
        if 0 <= event.x <= self._bw and 0 <= event.y <= self._bh:
            if self._command:
                self._command()

    def restyle(self, fill, hover, fg=None):
        self._fill, self._hover = fill, hover
        if fg:
            self._fg = fg
        self._current = fill
        self._draw()


class Switch(tk.Canvas):
    """On/off switch used in Settings."""

    def __init__(self, parent, value, command, bg, off_color):
        super().__init__(parent, width=50, height=28, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        on = ORANGE if value else off_color
        self.create_polygon(rrect_points(1, 1, 49, 27, 13),
                            smooth=True, fill=on, outline="")
        x = 36 if value else 14
        self.create_oval(x - 10, 4, x + 10, 24, fill="white", outline="")
        self.bind("<ButtonRelease-1>", lambda e: command())


class SideCard(tk.Canvas):
    """Microphone card in the sidebar with a 7-bar live level meter."""

    def __init__(self, parent, P, family, w=188, h=78):
        super().__init__(parent, width=w, height=h, bg=P["side"],
                         highlightthickness=0, bd=0)
        self.P = P
        self.create_polygon(rrect_points(1, 1, w - 1, h - 1, 18), smooth=True,
                            fill=P["card"], outline=P["line"])
        self.create_text(16, 20, text="MICROPHONE", anchor="w",
                         fill=P["muted"], font=(family, 8))
        self.create_text(16, 50, text="Default input", anchor="w",
                         fill=P["text"], font=(family, 11))
        self.bars = [
            self.create_line(0, 0, 0, 0, width=4, capstyle="round", fill=ORANGE)
            for _ in range(7)
        ]
        self.w = w
        self.update_level(0.0, 0.0)

    def update_level(self, t, level):
        for i, bar in enumerate(self.bars):
            amp = 0.18 + 0.82 * min(
                1.0, level * (0.5 + 0.7 * abs(math.sin(t * 7 + i * 0.9)))
            )
            x = self.w - 16 - (6 - i) * 8
            half = 11 * amp
            self.coords(bar, x, 50 - half + 2, x, 50 + half - 2)


class Stage(tk.Canvas):
    """Home visual: glow, animated logo, VOXY title, status pill, mic + rings."""

    W, H = 520, 400
    MIC_Y = 300

    def __init__(self, parent, P, family, on_mic):
        super().__init__(parent, width=self.W, height=self.H, bg=P["bg"],
                         highlightthickness=0, bd=0)
        self.P, self.family, self.on_mic = P, family, on_mic
        self.cx = self.W / 2
        self.ox, self.oy = self.cx - 100, 14
        self.amps = [0.45] * 16
        self._dy = 0.0
        self._text = None
        cx, bg = self.cx, P["bg"]

        # soft pink glow behind the logo
        self.glow = [self.create_oval(0, 0, 1, 1, fill=bg, outline="")
                     for _ in range(7)]

        # 16 bars behind the V
        self.bars = [
            self.create_line(0, 0, 0, 0, width=6, capstyle="round",
                             fill=blend(grad(i / 15), bg, 0.5))
            for i in range(16)
        ]

        # the V (gradient, round caps)
        for leg in ((68, 20, 100, 100), (100, 100, 132, 20)):
            for s in range(12):
                a, b = s / 12, (s + 1) / 12
                x1 = leg[0] + (leg[2] - leg[0]) * a
                y1 = leg[1] + (leg[3] - leg[1]) * a
                x2 = leg[0] + (leg[2] - leg[0]) * b
                y2 = leg[1] + (leg[3] - leg[1]) * b
                t = (((x1 + x2) / 2 - 68) / 64 + ((y1 + y2) / 2 - 20) / 80) / 2
                self.create_line(
                    self.ox + x1, self.oy + y1, self.ox + x2, self.oy + y2,
                    width=16, capstyle="round", fill=grad(t), tags="vlogo"
                )

        # VOXY title with gradient letters
        title_font = tkfont.Font(family=family, size=26, weight="bold")
        letters, gap = "VOXY", 7
        widths = [title_font.measure(c) for c in letters]
        x = cx - (sum(widths) + gap * 3) / 2
        for i, ch in enumerate(letters):
            self.create_text(x, 162, text=ch, anchor="w", font=title_font,
                             fill=grad(i / 3 * 0.55))
            x += widths[i] + gap

        # status pill
        self.pill_font = tkfont.Font(family=family, size=13)
        self.pill = self.create_polygon(0, 0, 0, 0, 0, 0, smooth=True,
                                        fill=P["card"], outline=P["line"])
        self.dot = self.create_oval(0, 0, 0, 0, fill=ORANGE, outline="")
        self.pill_text = self.create_text(0, 206, anchor="w", text="",
                                          fill=P["text"], font=self.pill_font)

        # mic button + rings
        my = self.MIC_Y
        self.rings = [
            self.create_oval(0, 0, 1, 1, outline=ORANGE, width=2, state="hidden")
            for _ in range(2)
        ]
        self.create_oval(cx - 52, my - 52, cx + 52, my + 52,
                         fill=blend(ORANGE, bg, 0.10), outline="", tags="mic")
        self.create_oval(cx - 45, my - 45, cx + 45, my + 45,
                         fill=blend(ORANGE, bg, 0.20), outline="", tags="mic")
        self.mic = self.create_oval(cx - 38, my - 38, cx + 38, my + 38,
                                    fill=MIC, outline="", tags="mic")
        self.create_line(cx, my - 12, cx, my - 1, width=11, capstyle="round",
                         fill="white", tags="mic")
        self.create_arc(cx - 12, my - 9, cx + 12, my + 13, start=180,
                        extent=180, style="arc", outline="white", width=2.5,
                        tags="mic")
        self.create_line(cx, my + 13, cx, my + 20, width=2.5, fill="white",
                         tags="mic")
        self.create_line(cx - 6, my + 20, cx + 6, my + 20, width=2.5,
                         fill="white", capstyle="round", tags="mic")

        self.tag_bind("mic", "<Button-1>", lambda e: self.on_mic())
        self.tag_bind("mic", "<Enter>", lambda e: (
            self.itemconfig(self.mic, fill="#FB6A1C"),
            self.configure(cursor="hand2")))
        self.tag_bind("mic", "<Leave>", lambda e: (
            self.itemconfig(self.mic, fill=MIC),
            self.configure(cursor="")))

        self.create_text(cx, 390, text="Press the mic or say “Voxy”",
                         fill=P["muted"], font=(family, 10))

    def set_text(self, text):
        if text == self._text:
            return
        self._text = text
        w = max(300, self.pill_font.measure(text) + 28 * 2 + 24)
        left, cx = self.cx - w / 2, self.cx
        self.coords(self.pill, *rrect_points(left, 184, left + w, 228, 22))
        self.coords(self.dot, left + 25, 201, left + 35, 211)
        self.coords(self.pill_text, left + 49, 206)
        self.itemconfig(self.pill_text, text=text)

    def update_anim(self, t, state, level):
        P, cx, my = self.P, self.cx, self.MIC_Y
        pulse = 0.5 - 0.5 * math.cos(2 * math.pi * t / 4)
        dy = -6 * math.sin(2 * math.pi * t / 4)

        # glow
        for j, oval in enumerate(self.glow):
            r = (150 - j * 17) * (1 + 0.10 * pulse)
            a = ((j + 1) / 7) * (0.75 + 0.25 * pulse)
            cy = self.oy + 66
            self.coords(oval, cx - r, cy - r * 0.6, cx + r, cy + r * 0.6)
            self.itemconfig(oval, fill=blend(P["glow"], P["bg"], a))

        # bars
        for i, h in enumerate(BAR_HEIGHTS):
            if state == "listening":
                e = abs(math.sin(t * 6.0 + i * 0.85))
                target = 0.4 + 0.6 * min(1.0, level * (0.45 + 0.9 * e))
            elif state == "processing":
                target = 0.4 + 0.35 * (0.5 + 0.5 * math.sin(t * 5.7 + (i % 8) * 0.8))
            else:
                target = 0.42 + 0.06 * math.sin(t * 0.9 + i * 0.5)
            self.amps[i] += (target - self.amps[i]) * 0.35
            half = h * self.amps[i] / 2
            x = self.ox + 10 + i * 11.6 + 3
            c = self.oy + 60 + dy
            self.coords(self.bars[i], x, c - half + 3, x, c + half - 3)

        # float the V together with the bars
        self.move("vlogo", 0, dy - self._dy)
        self._dy = dy

        # status dot
        if state == "listening":
            a = 0.3 + 0.7 * (0.5 + 0.5 * math.cos(2 * math.pi * t / 1.2))
            dot = blend(ORANGE, P["card"], a)
        elif state == "processing":
            dot = ORANGE
        else:
            dot = P["muted"]
        self.itemconfig(self.dot, fill=dot)

        # expanding rings while listening
        for k, ring in enumerate(self.rings):
            if state == "listening":
                p = ((t / 2.4) + k * 0.5) % 1.0
                r = 38 * (1 + 0.9 * p)
                self.coords(ring, cx - r, my - r, cx + r, my + r)
                self.itemconfig(ring, state="normal",
                                outline=blend(ORANGE, P["bg"], 0.55 * (1 - p)))
            else:
                self.itemconfig(ring, state="hidden")


# =====================================
# LIVE MICROPHONE LEVEL (for animation only)
# =====================================

class MicLevel:

    def __init__(self):
        self.value = 0.0
        self.stream = None
        self.active = False

    def start(self):
        if sd is None or not LIVE_MIC_LEVEL or self.stream is not None:
            return
        try:
            self.stream = sd.RawInputStream(
                samplerate=16000, channels=1, dtype="int16",
                blocksize=800, callback=self._callback
            )
            self.stream.start()
            self.active = True
        except Exception:
            self.stream = None
            self.active = False

    def stop(self):
        stream, self.stream = self.stream, None
        self.active = False
        self.value = 0.0
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _callback(self, indata, frames, time_info, status):
        try:
            samples = array("h", bytes(indata))
            if samples:
                rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768
                self.value = min(1.0, rms * 10)
        except Exception:
            pass


# =====================================
# MAIN APP
# =====================================

class VoxyApp(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title("Voxy - Linux AI Assistant")
        self.geometry("1100x700")
        self.minsize(880, 640)

        families = set(tkfont.families())
        self.family = next(
            (f for f in ("Space Grotesk", "Inter", "Ubuntu", "Noto Sans",
                         "DejaVu Sans") if f in families),
            "TkDefaultFont"
        )
        self.option_add("*Font", (self.family, 11))

        self.light_mode = False
        self._app_icon = None

        self.history = []
        self.current_page = "Home"

        self.sound_feedback = False
        self.confirm_before_action = True

        self._audio_busy = False
        self.continuous_listening = True

        # voice feedback bookkeeping (see voice_feedback.py)
        self._voice_last_command = ""
        self._voice_last_status = None
        self._voice_proc_token = None

        api_key = os.environ.get("GROQ_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is missing.\n"
                "Set your API key before starting Voxy."
            )

        self.command_engine = CommandUnderstanding(api_key)
        self.execution = LinuxExecutor()

        self.language = tk.StringVar(value="English")
        self.status_message = tk.StringVar(value="How Can I Help You Today ?")
        self.command_var = tk.StringVar()
        self.status_message.trace_add("write", self._on_status)

        # visual state: "idle" | "listening" | "processing"
        self.ui_state = "idle"
        self.notice = None  # result / error card shown under the stage

        self.stage = None
        self.side_card = None
        self.bottom = None
        self.mic_level = MicLevel()
        self.level = 0.0
        self._t0 = time.time()

        try:
            assets = Path(__file__).resolve().parent / "voxy_v2" / "assets"
            self._app_icon = tk.PhotoImage(file=str(assets / "voxy_icon.png"))
            self.iconphoto(True, self._app_icon)
        except tk.TclError:
            pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_shell()
        self.show_page("Home")
        self.after(33, self._tick)

    # -------------------------------------
    # helpers
    # -------------------------------------

    @property
    def P(self):
        return LIGHT if self.light_mode else DARK

    def f(self, size, weight="normal"):
        return (self.family, size, weight)

    # -------------------------------------
    # voice feedback (optional, see voice_feedback.py)
    # -------------------------------------

    def _vf(self, name, *args, **kwargs):
        """Call voice_feedback.<name>; can never raise into the GUI."""
        if voice_feedback is None:
            return None
        try:
            return getattr(voice_feedback, name)(*args, **kwargs)
        except Exception as error:
            print("[Voice] ignored error:", repr(error), flush=True)
            return None

    def _voice_announce_result(self, success, message):
        status = self._voice_last_status
        command = self._voice_last_command
        self._voice_last_status = None

        if status == "Needs Clarification":
            self._vf("speak_clarification", message, context=command)
        elif success:
            self._vf("speak_success", context=command)
        else:
            self._vf("speak_error", context=command)

    def _voice_schedule_processing_hint(self, command):
        if voice_feedback is None:
            return
        token = object()
        self._voice_proc_token = token
        self.after(6000, self._voice_processing_hint, token, command)

    def _voice_processing_hint(self, token, command):
        if (
            self.ui_state == "processing"
            and self._voice_proc_token is token
            and not self._vf("is_speaking")
        ):
            self._vf("speak_status", context=command)

    def _on_close(self):
        self.mic_level.stop()
        self._vf("shutdown")
        self.destroy()

    def _on_status(self, *args):
        if self.stage is not None and self.stage.winfo_exists():
            self.stage.set_text(self.status_message.get())

    def _btn(self, parent, text, command, w, h, bg, fill=None, hover=None,
             fg="white", outline="", radius=14, size=12, weight="bold",
             anchor="center"):
        return RButton(
            parent, text, command, w, h,
            fill or DEEP, hover or DEEP_HOVER, fg, bg,
            self.f(size, weight), radius, outline, anchor
        )

    # -------------------------------------
    # animation loop (30 fps)
    # -------------------------------------

    def _tick(self):
        now = time.time() - self._t0

        if self.ui_state == "listening":
            if self.mic_level.active:
                raw = self.mic_level.value
            else:
                raw = (0.30 + 0.45 * abs(math.sin(now * 3.1))
                       * (0.6 + 0.4 * abs(math.sin(now * 7.3 + 1)))
                       + random.uniform(0, 0.08))
        else:
            raw = 0.0
        self.level += (raw - self.level) * 0.3

        try:
            if self.stage is not None and self.stage.winfo_exists():
                self.stage.update_anim(now, self.ui_state, self.level)
            if self.side_card is not None and self.side_card.winfo_exists():
                self.side_card.update_level(now, self.level)
        except tk.TclError:
            pass

        self.after(33, self._tick)

    # =====================================
    # MAIN INTERFACE
    # =====================================

    def _build_shell(self):
        P = self.P
        self.configure(bg=P["bg"])

        self.body = tk.Frame(self, bg=P["bg"])
        self.body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(self.body, bg=P["side"], width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(self.body, bg=P["side_line"], width=1).pack(side="left", fill="y")

        # logo mark + name
        logo = tk.Canvas(self.sidebar, width=44, height=30, bg=P["side"],
                         highlightthickness=0)
        logo.pack(pady=(26, 0))
        pts = [(20, 20), (100, 108), (180, 20)]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            for s in range(8):
                a, b = s / 8, (s + 1) / 8
                logo.create_line(
                    (x1 + (x2 - x1) * a) * 0.2 + 2, (y1 + (y2 - y1) * a) * 0.2 + 3,
                    (x1 + (x2 - x1) * b) * 0.2 + 2, (y1 + (y2 - y1) * b) * 0.2 + 3,
                    width=4, capstyle="round",
                    fill=grad((x1 + (x2 - x1) * a - 20) / 320)
                )
        tk.Label(self.sidebar, text="Voxy", fg=P["text"], bg=P["side"],
                 font=self.f(14, "bold")).pack(pady=(2, 22))

        self.nav_buttons = {}
        for name, icon in (("Home", "⌂"), ("History", "◴"), ("Settings", "⚙")):
            button = self._btn(
                self.sidebar, f"{icon}    {name}",
                lambda n=name: self.show_page(n), 188, 46, P["side"],
                fill=P["side"], hover=P["hover"], fg=P["text"], size=12,
                weight="normal", anchor="w"
            )
            button.pack(pady=3)
            self.nav_buttons[name] = button

        tk.Frame(self.sidebar, bg=P["side"]).pack(fill="both", expand=True)

        self.side_card = SideCard(self.sidebar, P, self.family)
        self.side_card.pack(pady=(0, 20))

        # right side: top bar + content
        main = tk.Frame(self.body, bg=P["bg"])
        main.pack(side="left", fill="both", expand=True)

        topbar = tk.Frame(main, bg=P["bg"], height=56)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        self._theme_toggle(topbar).pack(side="right", padx=22, pady=10)

        self.content = tk.Frame(main, bg=P["bg"])
        self.content.pack(fill="both", expand=True, padx=28, pady=(0, 14))

    def _theme_toggle(self, parent):
        P = self.P
        box = tk.Frame(parent, bg=P["card"], highlightthickness=1,
                       highlightbackground=P["line"])
        for symbol, light in (("☼", True), ("☾", False)):
            active = self.light_mode == light
            self._btn(
                box, symbol, lambda l=light: self.set_theme(l), 38, 32,
                P["card"], fill=P["toggle_on"] if active else P["card"],
                hover=P["toggle_on"], fg=P["text"], radius=10, size=13,
                weight="normal"
            ).pack(side="left", padx=3, pady=3)
        return box

    def _style_nav(self):
        P = self.P
        for name, button in self.nav_buttons.items():
            if name == self.current_page:
                button.restyle(DEEP, DEEP_HOVER, "white")
            else:
                button.restyle(P["side"], P["hover"], P["text"])

    def clear_content(self):
        self.stage = None
        self.bottom = None
        for widget in self.content.winfo_children():
            widget.destroy()

    def show_page(self, page):
        self.current_page = page
        self._style_nav()
        self.clear_content()

        if page == "Home":
            self._home_page()
        elif page == "History":
            self._history_page()
        else:
            self._settings_page()

    def set_theme(self, light):
        if self.light_mode == light:
            return
        self.light_mode = light
        self._rebuild()

    def toggle_theme(self):
        self.set_theme(not self.light_mode)

    def _rebuild(self):
        self.stage = None
        self.side_card = None
        self.bottom = None
        self.body.destroy()
        self._build_shell()
        self.show_page(self.current_page)

    # =====================================
    # HOME PAGE
    # =====================================

    def _home_page(self):
        P = self.P
        wrap = tk.Frame(self.content, bg=P["bg"])
        wrap.pack(expand=True)

        self.stage = Stage(wrap, P, self.family, self.start_listening)
        self.stage.pack()
        self.stage.set_text(self.status_message.get())

        self.bottom = tk.Frame(wrap, bg=P["bg"])
        self.bottom.pack(pady=(4, 0))
        self._render_bottom()

    def _render_bottom(self):
        if self.bottom is None or not self.bottom.winfo_exists():
            return
        for widget in self.bottom.winfo_children():
            widget.destroy()

        if self.notice:
            self._notice_card(self.bottom)
        else:
            self._input_row(self.bottom)

    def _input_row(self, parent):
        P = self.P

        row = tk.Frame(parent, bg=P["bg"])
        row.pack()

        box = tk.Canvas(row, width=340, height=48, bg=P["bg"],
                        highlightthickness=0)
        box.pack(side="left", padx=(0, 10))
        outline = box.create_polygon(
            rrect_points(1, 1, 339, 47, 14), smooth=True,
            fill=P["field"], outline=P["line"]
        )
        entry = tk.Entry(
            box, textvariable=self.command_var, bg=P["field"], fg=P["text"],
            insertbackground=P["text"], relief="flat", bd=0,
            highlightthickness=0, font=self.f(12)
        )
        box.create_window(18, 24, window=entry, anchor="w", width=304, height=28)
        entry.bind("<Return>", lambda e: self.submit_command())
        entry.bind("<FocusIn>", lambda e: box.itemconfig(outline, outline=ORANGE))
        entry.bind("<FocusOut>", lambda e: box.itemconfig(outline, outline=P["line"]))

        self._btn(row, "Run", self.submit_command, 96, 48, P["bg"]).pack(side="left")

        chips = tk.Frame(parent, bg=P["bg"])
        chips.pack(pady=(16, 0))
        tk.Label(chips, text="TRY SAYING", fg=P["muted"], bg=P["bg"],
                 font=self.f(8)).pack(side="left", padx=(0, 10))
        chip_font = tkfont.Font(family=self.family, size=10)
        for text in CHIPS:
            self._btn(
                chips, text, lambda t=text: self._run_chip(t),
                chip_font.measure(text) + 32, 34, P["bg"], fill=P["field"],
                hover=P["card"], fg=P["text"], outline=P["chip_line"],
                radius=17, size=10, weight="normal"
            ).pack(side="left", padx=4)

    def _run_chip(self, text):
        self.command_var.set(text)
        self.submit_command()

    def _notice_card(self, parent):
        P, n = self.P, self.notice
        card = tk.Frame(parent, bg=P["bg"])
        card.pack()

        color = GREEN if n["ok"] else RED
        icon = tk.Canvas(card, width=52, height=52, bg=P["bg"],
                         highlightthickness=0)
        icon.pack(pady=(0, 6))
        icon.create_oval(2, 2, 50, 50, fill=color, outline="")
        icon.create_text(26, 26, text="✓" if n["ok"] else "!", fill="white",
                         font=self.f(20, "bold"))

        tk.Label(card, text=n["title"], fg=P["text"] if n["ok"] else RED,
                 bg=P["bg"], font=self.f(13, "bold")).pack()
        tk.Label(card, text=n["message"], fg=P["text"], bg=P["bg"],
                 font=self.f(11), wraplength=460,
                 justify="left").pack(pady=(6, 10))
        self._btn(card, n["button"], n["command"], 180, 40, P["bg"],
                  fill=P["card"], hover=P["hover"], fg=P["text"],
                  outline=P["line"], size=11).pack()

    def _dismiss_notice(self):
        self.notice = None
        self._render_bottom()

    # =====================================
    # MICROPHONE
    # =====================================

    def start_listening(self):

        if self._audio_busy:
            return

        self._vf("stop_speaking")

        self._audio_busy = True
        self.ui_state = "listening"
        self.notice = None
        self._render_bottom()

        self.status_message.set("Listening… Speak now!")
        self.mic_level.start()

        threading.Thread(
            target=self._audio_worker,
            daemon=True
        ).start()

    def _update_audio_status(self, message):

        def update():
            self.status_message.set(message)

        self.after(0, update)

    def _audio_worker(self):

        try:

            recognized_text = listen_and_transcribe(
                status_callback=self._update_audio_status
            )

            self.after(
                0,
                self._process_recognized_speech,
                recognized_text
            )

        except Exception as error:

            print("AUDIO WORKER ERROR:", flush=True)
            traceback.print_exc()

            self.after(
                0,
                self._show_audio_error,
                str(error)
            )

    def _process_recognized_speech(self, recognized_text):

        self._audio_busy = False
        self.mic_level.stop()

        if not recognized_text or not recognized_text.strip():

            self._show_audio_error(
                "No clear speech detected."
            )

            return

        self.command_var.set(recognized_text)
        self.submit_command()

    def _show_audio_error(self, error_message):

        self._audio_busy = False
        self.mic_level.stop()
        self.ui_state = "idle"

        print("Audio error:", error_message, flush=True)

        self.status_message.set("Listening error. Please try again.")

        self.notice = {
            "ok": False,
            "title": "Microphone / Transcription Error",
            "message": error_message,
            "button": "Try Again",
            "command": self.start_listening,
        }
        self._render_bottom()

        if self.continuous_listening:
            self.after(3000, self._resume_listening)

    def _resume_listening(self):

        if self._vf("is_speaking"):
            self.after(300, self._resume_listening)
            return

        if (
            self.continuous_listening
            and not self._audio_busy
            and self.current_page == "Home"
        ):

            self.start_listening()

    # =====================================
    # COMMAND SUBMISSION
    # =====================================

    def submit_command(self):

        command = self.command_var.get().strip()

        if not command:

            self.status_message.set("Please enter a command first.")

            return

        self._processing_screen(command)

    def _processing_screen(self, command):

        self.ui_state = "processing"
        self.notice = None
        self.status_message.set("Processing your command…")
        self._render_bottom()

        self._voice_last_command = command
        self._voice_schedule_processing_hint(command)

        threading.Thread(
            target=self._execute_real_pipeline,
            args=(command,),
            daemon=True
        ).start()

    # =====================================
    # SECURITY CONFIRMATION
    # =====================================

    def request_delete_confirmation(self, item_name):

        result = {"confirmed": False}
        finished = threading.Event()

        def show_dialog():

            try:

                result["confirmed"] = messagebox.askyesno(
                    "Security Confirmation",
                    (
                        "Are you sure you want to delete "
                        f"this item?\n\n{item_name}"
                    ),
                    parent=self
                )

            finally:
                finished.set()

        self.after(0, show_dialog)

        if not finished.wait(timeout=120):
            return False

        return result["confirmed"]

    # =====================================
    # PIPELINE HELPERS
    # =====================================

    def _format_execution_result(self, result):

        if not isinstance(result, dict):
            return str(result)

        message = result.get("message", "")

        details = result.get("results", [])

        if not isinstance(details, list) or not details:
            return str(message or result)

        lines = []

        for index, item in enumerate(details, start=1):

            if isinstance(item, dict):

                item_message = item.get(
                    "message",
                    item.get("error", str(item))
                )

                item_success = item.get("success")

                mark = (
                    "✓" if item_success is True
                    else "✗" if item_success is False
                    else "•"
                )

                lines.append(
                    f"{mark} {index}. {item_message}"
                )

            else:

                lines.append(f"• {index}. {item}")

        return "\n".join(lines)

    # =====================================
    # GROQ + EXECUTION PIPELINE
    # =====================================

    def _execute_real_pipeline(self, command):

        try:

            print(
                f"\n[Pipeline] Processing command: {command}",
                flush=True
            )

            # Step 1: Understand command
            structured_json = self.command_engine.understand(
                command
            )

            print(
                "[Pipeline] Groq JSON Output:",
                structured_json,
                flush=True
            )

            if not isinstance(structured_json, dict):

                raise ValueError(
                    "Groq returned invalid command data."
                )

            actions = structured_json.get("actions") or []

            # Step 2: Clarification
            if structured_json.get("needs_clarification"):

                success = False

                message = structured_json.get(
                    "response_text",
                    "Please clarify your command."
                )

                status = "Needs Clarification"

            # Step 3: Unknown command with no actions
            elif (
                structured_json.get("intent") == "unknown"
                and not actions
            ):

                success = False

                message = structured_json.get(
                    "response_text",
                    "I couldn't identify the requested action."
                )

                status = "Failed"

            # Step 4: Validate actions
            elif actions and not all(
                isinstance(action, dict)
                and action.get("intent")
                and action.get("intent") != "unknown"
                for action in actions
            ):

                success = False

                message = (
                    "One or more actions could not be understood. "
                    "Please repeat the command."
                )

                status = "Failed"

            else:

                print(
                    "[Pipeline] Sending command to LinuxExecutor...",
                    flush=True
                )

                # Step 5: Execute
                result = self.execution.execute_actions(
                    structured_json,
                    confirm_callback=self.request_delete_confirmation
                )

                print(
                    "[Pipeline] Execution Result:",
                    repr(result),
                    flush=True
                )

                if not isinstance(result, dict):

                    raise TypeError(
                        "LinuxExecutor returned an invalid result: "
                        f"{type(result).__name__}"
                    )

                success = bool(result.get("success", False))

                message = self._format_execution_result(result)

                if not message:
                    message = (
                        "Command execution completed."
                        if success
                        else "The command could not be executed."
                    )

                status = "Success" if success else "Failed"

        except Exception as error:

            print(
                "\n[Pipeline Exception]",
                flush=True
            )

            traceback.print_exc()

            success = False
            message = f"Execution error: {error}"
            status = "Failed"

        print(
            f"[Pipeline] Final Status: {status}",
            flush=True
        )

        self._voice_last_status = status

        self.after(
            0,
            self._add_history,
            command,
            status
        )

        self.after(
            0,
            self._result_screen,
            success,
            message
        )

    # =====================================
    # RESULT
    # =====================================

    def _result_screen(self, success, message):

        self.ui_state = "idle"

        self._voice_announce_result(success, message)

        self.notice = {
            "ok": success,
            "title": "Done!" if success else "Something Went Wrong",
            "message": message,
            "button": "⌂  Back to Home",
            "command": self._dismiss_notice,
        }

        self.status_message.set("How Can I Help You Today ?")
        self.command_var.set("")

        if self.current_page == "Home":
            self._render_bottom()

        if self.continuous_listening:
            self.after(1500, self._resume_listening)

    # =====================================
    # HISTORY
    # =====================================

    def _add_history(self, command, status):

        self.history.insert(
            0,
            {
                "command": command,
                "time": datetime.now().strftime("%I:%M %p"),
                "status": status
            }
        )

    def _history_page(self):
        P = self.P

        tk.Label(self.content, text="Command History", fg=P["text"],
                 bg=P["bg"], font=self.f(22, "bold")).pack(anchor="w", pady=(6, 14))

        top = tk.Frame(self.content, bg=P["bg"])
        top.pack(fill="x", pady=(0, 10))

        tk.Label(top, text="Recent commands", fg=P["muted"], bg=P["bg"],
                 font=self.f(10)).pack(side="left")

        self._btn(top, "▤  Clear History", self.clear_history, 150, 36,
                  P["bg"], fill=P["card"], hover=P["hover"], fg=P["text"],
                  outline=P["line"], radius=12, size=10,
                  weight="normal").pack(side="right")

        table = tk.Frame(self.content, bg=P["bg"])
        table.pack(fill="both", expand=True)

        header = tk.Frame(table, bg=P["card"], highlightthickness=1,
                          highlightbackground=P["line"])
        header.pack(fill="x", pady=(0, 6))

        for label, width in (("Command", 1), ("Time", 12), ("Status", 12)):

            tk.Label(
                header,
                text=label,
                bg=P["card"],
                fg=P["muted"],
                anchor="w",
                padx=12,
                pady=9,
                width=width,
                font=self.f(10, "bold")
            ).pack(
                side="left",
                fill="x",
                expand=(label == "Command")
            )

        if not self.history:

            tk.Label(
                table,
                text="No commands yet",
                bg=P["bg"],
                fg=P["muted"],
                font=self.f(11)
            ).pack(pady=35)

        for item in self.history:

            row = tk.Frame(table, bg=P["card"], highlightthickness=1,
                           highlightbackground=P["line"])
            row.pack(fill="x", pady=3)

            tk.Label(
                row,
                text="◉  " + item["command"],
                bg=P["card"],
                fg=P["text"],
                anchor="w",
                padx=12,
                pady=10,
                font=self.f(11)
            ).pack(
                side="left",
                fill="x",
                expand=True
            )

            tk.Label(
                row,
                text=item["time"],
                bg=P["card"],
                fg=P["muted"],
                width=12,
                font=self.f(10)
            ).pack(side="left")

            ok = item["status"] == "Success"

            mark = (
                "✓" if ok
                else "×" if item["status"] == "Failed"
                else "•"
            )

            tk.Label(
                row,
                text=mark,
                bg=P["card"],
                fg=GREEN if ok else (
                    RED if item["status"] == "Failed" else P["muted"]
                ),
                width=5,
                font=self.f(15, "bold")
            ).pack(side="right")

    def clear_history(self):

        if messagebox.askyesno(
            "Clear History",
            "Delete all command history?",
            parent=self
        ):

            self.history.clear()
            self.show_page("History")

    # =====================================
    # SETTINGS
    # =====================================

    def _settings_page(self):
        P = self.P

        tk.Label(self.content, text="Settings", fg=P["text"], bg=P["bg"],
                 font=self.f(22, "bold")).pack(anchor="w", pady=(6, 14))

        panel = tk.Frame(self.content, bg=P["bg"])
        panel.pack(fill="x")

        self._setting_row(panel, "◎", "Language", self._language_control)
        self._setting_row(panel, "◖", "Sound Feedback", self._sound_control)
        self._setting_row(panel, "◇", "Confirmation before action",
                          self._confirmation_control)
        self._setting_row(panel, "☼", "Mode", self._mode_control)

    def _setting_row(self, parent, icon, title, control_builder):
        P = self.P

        row = tk.Frame(parent, bg=P["card"], highlightthickness=1,
                       highlightbackground=P["line"])
        row.pack(fill="x", pady=5, ipady=4)

        tk.Label(row, text=icon, bg=P["card"], fg=ORANGE,
                 font=self.f(15), width=3).pack(side="left", padx=(8, 2),
                                                pady=8)

        tk.Label(row, text=title, bg=P["card"], fg=P["text"],
                 font=self.f(12), anchor="w").pack(side="left", fill="x",
                                                   expand=True, pady=10)

        control_builder(row)

    def _language_control(self, row):
        P = self.P

        menu = tk.OptionMenu(row, self.language, "English", "Arabic")

        menu.configure(
            bg=P["field"],
            fg=P["text"],
            activebackground=ORANGE,
            activeforeground="white",
            highlightthickness=1,
            highlightbackground=P["line"],
            bd=0,
            relief="flat",
            width=10,
            font=self.f(11)
        )

        menu["menu"].configure(
            bg=P["field"],
            fg=P["text"],
            activebackground=ORANGE,
            activeforeground="white"
        )

        menu.pack(side="right", padx=14, pady=6)

    def _sound_control(self, row):

        Switch(
            row, self.sound_feedback,
            lambda: self._set_sound(not self.sound_feedback),
            self.P["card"], self.P["line"]
        ).pack(side="right", padx=16)

    def _set_sound(self, value):

        self.sound_feedback = value
        self.show_page("Settings")

    def _confirmation_control(self, row):

        Switch(
            row, self.confirm_before_action,
            lambda: self._set_confirmation(not self.confirm_before_action),
            self.P["card"], self.P["line"]
        ).pack(side="right", padx=16)

    def _set_confirmation(self, value):

        self.confirm_before_action = value
        self.show_page("Settings")

    def _mode_control(self, row):

        self._theme_toggle(row).pack(side="right", padx=12, pady=6)


if __name__ == "__main__":

    app = VoxyApp()
    app.mainloop()
