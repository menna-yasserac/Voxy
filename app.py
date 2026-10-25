
#!/usr/bin/env python3
"""
Voxy - Linux voice assistant GUI.
Tkinter interface connected to Faster-Whisper.
"""

import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import webbrowser
import subprocess
import os
import shutil
import threading
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "audio_module"))
from command_understanding import understand_command

from audio_service import listen_and_transcribe


BG = "#17191D"
PANEL = "#202226"
SIDEBAR = "#3A3A3A"
ORANGE = "#E95420"
BUTTON = "#C96A45"
TEXT = "#F4F0F0"
MUTED = "#B8B5B8"
GREEN = "#45D66B"
RED = "#F21F2B"

FONT = ("Inria Serif", 11)
FONT_SMALL = ("Inria Serif", 9)
FONT_TITLE = ("Inria Serif", 23)
FONT_BOLD = ("Inria Serif", 12, "bold")


class VoxyApp(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title("Voxy")
        self.geometry("1000x620")
        self.minsize(850, 540)
        self.configure(bg=BG)
        self.option_add("*Font", FONT)

        self.light_mode = False
        self._logo_image = None
        self._app_icon = None

        self.history = []
        self.current_page = "Home"
        self.sound_feedback = False
        self.confirm_before_action = True
        self._audio_busy = False

        self.language = tk.StringVar(value="English")
        self.status_message = tk.StringVar(
            value="How Can I Help You Today ?"
        )
        self.command_var = tk.StringVar()

        try:
            assets = Path(__file__).resolve().parent / "voxy_v2" / "assets"
            self._logo_image = tk.PhotoImage(
                file=str(assets / "voxy_logo_mark.png")
            )
            self._app_icon = tk.PhotoImage(
                file=str(assets / "voxy_icon.png")
            )
            self.iconphoto(True, self._app_icon)
        except tk.TclError:
            pass

        self._build_shell()
        self.show_page("Home")

    # -------------------- Main layout --------------------

   
    def _build_shell(self):
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(
            self.body, bg=SIDEBAR, width=175
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo = tk.Frame(self.sidebar, bg=SIDEBAR, height=88)
        logo.pack(fill="x")
        logo.pack_propagate(False)

        tk.Label(
            logo, text="〰V〰", fg=ORANGE,
            bg=SIDEBAR, font=("Arial", 23, "bold")
        ).pack(pady=(12, 0))

        tk.Label(
            logo, text="Voxy", fg=TEXT,
            bg=SIDEBAR, font=FONT_SMALL
        ).pack()

        self.nav_buttons = {}

        for name, icon in (
            ("Home", "⌂"),
            ("History", "◴"),
            ("Settings", "⚙")
        ):
            button = tk.Button(
                self.sidebar,
                text=f"{icon}   {name}",
                anchor="w",
                command=lambda n=name: self.show_page(n),
                bg=SIDEBAR,
                fg=TEXT,
                activebackground=ORANGE,
                activeforeground="white",
                bd=0,
                padx=15,
                pady=9,
                font=FONT
            )
            button.pack(fill="x", pady=1)
            self.nav_buttons[name] = button

        self.content = tk.Frame(self.body, bg=BG)
        self.content.pack(
            side="left", fill="both", expand=True,
            padx=18, pady=14
        )


    def _toggle_maximize(self):
        try:
            self.state(
                "zoomed" if self.state() != "zoomed" else "normal"
            )
        except tk.TclError:
            pass

    def clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    def show_page(self, page):
        self.current_page = page

        for name, button in self.nav_buttons.items():
            button.configure(
                bg=ORANGE if name == page else SIDEBAR
            )

        self.clear_content()

        if page == "Home":
            self._home_page()
        elif page == "History":
            self._history_page()
        else:
            self._settings_page()

        self.after_idle(self._apply_theme_tree)

    # -------------------- Home page --------------------

    def _logo_mark(self, parent, size=64):
        if self._logo_image is not None:
            factor = max(1, round(400 / max(size, 1)))
            image = self._logo_image.subsample(
                factor, max(1, factor // 2)
            )
            label = tk.Label(
                parent, image=image,
                bg=self._palette()["bg"], bd=0
            )
            label.image = image
            label.pack()
            return label

        canvas = tk.Canvas(
            parent, width=size, height=size,
            bg=self._palette()["bg"], highlightthickness=0
        )
        canvas.pack()
        canvas.create_text(
            size / 2, size / 2,
            text="〰V〰", fill=ORANGE,
            font=("Arial", int(size * 0.25), "bold")
        )
        return canvas

    def _home_page(self):
        center = tk.Frame(self.content, bg=BG)
        center.place(relx=0.5, rely=0.48, anchor="center")

        self._logo_mark(center, 94)

      
        tk.Label(
            center,
            text="VOXY",
            bg=BG,
            fg="#000000" if self.light_mode else "#FFFFFF",
            font=("Inria Serif", 20, "bold")
        ).pack(pady=(2, 15))

        tk.Label(
            center,
            textvariable=self.status_message,
            bg="#343438",
            fg=TEXT,
            font=FONT,
            padx=25,
            pady=9,
            relief="solid",
            bd=1
        ).pack(pady=(0, 12))

        self.mic_button = tk.Button(
            center,
            text="🎙",
            command=self.start_listening,
            bg="#A7440D",
            fg="white",
            activebackground=ORANGE,
            bd=2,
            relief="ridge",
            font=("Arial", 20),
            width=3,
            height=1,
            cursor="hand2"
        )
        self.mic_button.pack()

        tk.Label(
            center,
            text='Press 🎙 or say “Voxy”',
            bg=BG, fg=TEXT, font=FONT_SMALL
        ).pack(pady=(8, 12))

        row = tk.Frame(center, bg=BG)
        row.pack(fill="x")

        entry = tk.Entry(
            row,
            textvariable=self.command_var,
            width=38,
            bg="#292B30",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=FONT
        )
        entry.pack(side="left", ipady=8, padx=(0, 7))
        entry.bind(
            "<Return>", lambda event: self.submit_command()
        )

        tk.Button(
            row,
            text="Run",
            command=self.submit_command,
            bg=BUTTON,
            fg="white",
            activebackground=ORANGE,
            bd=0,
            padx=15,
            pady=8
        ).pack(side="left")

    # -------------------- Real microphone integration --------------------

    def start_listening(self):
        if self._audio_busy:
            return

        self._audio_busy = True
        self.status_message.set("Preparing microphone…")
        self._show_audio_status("Preparing microphone…")

        worker = threading.Thread(
            target=self._audio_worker,
            daemon=True
        )
        worker.start()

    def _show_audio_status(self, message):
        self.clear_content()

        frame = tk.Frame(self.content, bg=BG)
        frame.pack(fill="both", expand=True)

        inner = tk.Frame(frame, bg=BG)
        inner.place(relx=0.5, rely=0.48, anchor="center")

        self._logo_mark(inner, 105)

        tk.Label(
            inner, text="VOXY",
            fg=TEXT, bg=BG, font=FONT_TITLE
        ).pack(pady=(8, 5))

        self.audio_status_label = tk.Label(
            inner,
            text=message,
            fg=TEXT,
            bg=BG,
            font=FONT_BOLD,
            wraplength=450
        )
        self.audio_status_label.pack(pady=10)

        tk.Button(
            inner,
            text="Back to Home",
            command=lambda: self.show_page("Home"),
            bg=BUTTON,
            fg="white",
            bd=0,
            padx=12,
            pady=6
        ).pack(pady=8)

        self.after_idle(self._apply_theme_tree)

    def _audio_worker(self):
        try:
            result = listen_and_transcribe(
                status_callback=lambda message: self.after(
                    0, self._update_audio_status, message
                )
            )
            self.after(
                0, self._show_transcription_result, result
            )

        except Exception as error:
            self.after(
                0, self._show_audio_error, str(error)
            )

    def _update_audio_status(self, message):
        if not self.winfo_exists():
            return

        if hasattr(self, "audio_status_label"):
            try:
                self.audio_status_label.configure(text=message)
            except tk.TclError:
                pass

    def _show_transcription_result(self, result):
        self._audio_busy = False

        if self.current_page != "Home":
            return

        self.clear_content()

        frame = tk.Frame(self.content, bg=BG)
        frame.pack(fill="both", expand=True)

        card = tk.Frame(frame, bg=BG)
        card.place(relx=0.5, rely=0.45, anchor="center")

        recognized_text = result["text"]

        if recognized_text:
            self._use_recognized_text(recognized_text)
            return

        tk.Label(
            card,
            text=(
                "Speech Recognized"
                if recognized_text else "No Speech Recognized"
            ),
            fg=GREEN if recognized_text else RED,
            bg=BG,
            font=FONT_TITLE
        ).pack(pady=10)

        tk.Label(
            card,
            text=recognized_text or
                 "I couldn't recognize the speech. Please try again.",
            fg=TEXT,
            bg=BG,
            font=FONT,
            wraplength=500,
            justify="center"
        ).pack(pady=12)

        tk.Label(
            card,
            text=(
                f"Detected language: {result['language']}\n"
                f"Model load time: {result['load_time']:.2f} seconds\n"
                f"Recognition time: {result['transcribe_time']:.2f} seconds"
            ),
            fg=MUTED,
            bg=BG,
            font=FONT_SMALL,
            justify="center"
        ).pack(pady=8)

        buttons = tk.Frame(card, bg=BG)
        buttons.pack(pady=10)

        if recognized_text:
            tk.Button(
                buttons,
                text="Use This Text",
                command=lambda: self._use_recognized_text(
                    recognized_text
                ),
                bg=BUTTON,
                fg="white",
                bd=0,
                padx=12,
                pady=7
            ).pack(side="left", padx=5)

        tk.Button(
            buttons,
            text="Try Again",
            command=self.start_listening,
            bg="#343438",
            fg=TEXT,
            bd=0,
            padx=12,
            pady=7
        ).pack(side="left", padx=5)

        tk.Button(
            buttons,
            text="Home",
            command=lambda: self.show_page("Home"),
            bg="#343438",
            fg=TEXT,
            bd=0,
            padx=12,
            pady=7
        ).pack(side="left", padx=5)

        self.after_idle(self._apply_theme_tree)

    def _show_audio_error(self, error_message):
        self._audio_busy = False

        if self.current_page != "Home":
            return

        self.clear_content()

        frame = tk.Frame(self.content, bg=BG)
        frame.pack(fill="both", expand=True)

        card = tk.Frame(frame, bg=BG)
        card.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(
            card,
            text="Microphone Error",
            fg=RED,
            bg=BG,
            font=FONT_TITLE
        ).pack(pady=10)

        tk.Label(
            card,
            text=error_message,
            fg=TEXT,
            bg=BG,
            font=FONT,
            wraplength=450,
            justify="center"
        ).pack(pady=12)

        tk.Button(
            card,
            text="Try Again",
            command=self.start_listening,
            bg=BUTTON,
            fg="white",
            bd=0,
            padx=15,
            pady=7
        ).pack(pady=8)

        tk.Button(
            card,
            text="Back to Home",
            command=lambda: self.show_page("Home"),
            bg="#343438",
            fg=TEXT,
            bd=0,
            padx=15,
            pady=7
        ).pack(pady=5)

        self.after_idle(self._apply_theme_tree)

    def _use_recognized_text(self, text):
        self.command_var.set(text)
        self.show_page("Home")
        self.submit_command()

    # -------------------- Command demo --------------------
    def submit_command(self):
        command = self.command_var.get().strip()
        if not command:
            self.status_message.set("Please enter a command first.")
            return

        self.status_message.set(
            f"Command received: {command}"
        )
        self._processing_screen(command)



    def _processing_screen(self, command):
        self.clear_content()

        outer = tk.Frame(self.content, bg=BG)
        outer.pack(fill="both", expand=True)

        card = tk.Frame(outer, bg=BG)
        card.place(relx=0.5, rely=0.48, anchor="center")

        tk.Label(
            card, text="⚙", fg="#DCE8F8",
            bg="#3D4653", font=("Arial", 25),
            padx=12, pady=5
        ).pack(pady=12)

        tk.Label(
            card, text="Processing your command…",
            fg=TEXT, bg=BG, font=FONT
        ).pack(pady=8)

        bar = tk.Frame(
            card, bg="#D8D8D8", width=250, height=7
        )
        bar.pack(pady=3)
        bar.pack_propagate(False)

        fill = tk.Frame(bar, bg=ORANGE, height=7)
        fill.place(x=0, y=0, relheight=1, relwidth=0.8)

        tk.Label(
            card, text="Executing demo command…",
            fg=MUTED, bg=BG, font=FONT_SMALL
        ).pack(pady=10)

        self.after_idle(self._apply_theme_tree)
        self.after(
            650, lambda: self._execute_demo(command)
        )

    def _execute_demo(self, command):
        success, message = self._run_safe_command(command)
        status = "Success" if success else "Failed"

        if self.history:
            self.history[0]["status"] = status
            self.history[0]["time"] = datetime.now().strftime(
                "%I:%M %p"
            )

        self._result_screen(success, message)

    def _run_safe_command(self, command):
        """Limited demo router; not the final command executor."""
        understood = understand_command(command)

        if understood["intent"] == "open_app":
            target = understood["target"]

            if target in ("youtube", "google"):
                command = f"open {target}"
            else:
                app_urls = {
                    "facebook": "https://www.facebook.com",
                    "instagram": "https://www.instagram.com",
                    "whatsapp": "https://web.whatsapp.com",
                }

                if target in app_urls:
                    webbrowser.open(app_urls[target])
                    return True, f"Opened {target.title()}"

        text = command.lower().strip()

        if text.startswith("open youtube"):
            webbrowser.open("https://www.youtube.com")
            query = text.partition("search for")[2].strip()

            if query:
                from urllib.parse import quote_plus
                webbrowser.open(
                    "https://www.youtube.com/results?search_query="
                    + quote_plus(query)
                )

            return True, (
                "Opened YouTube"
                + (f" and searched for {query}" if query else "")
            )

        if text.startswith("open google"):
            webbrowser.open("https://www.google.com")
            return True, "Opened Google"

        if (
            text.startswith("open browser")
            or text.startswith("open firefox")
        ):
            if shutil.which("firefox"):
                subprocess.Popen(
                    ["firefox", "https://www.google.com"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                webbrowser.open("https://www.google.com")

            return True, "Opened browser"

        if text in ("open terminal", "launch terminal"):
            terminal = next(
                (
                    item for item in (
                        "x-terminal-emulator",
                        "gnome-terminal",
                        "konsole",
                        "xfce4-terminal"
                    )
                    if shutil.which(item)
                ),
                None
            )

            if terminal:
                subprocess.Popen(
                    [terminal],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True, "Opened terminal"

            return False, "No supported terminal was found."

        if text.startswith("search for "):
            from urllib.parse import quote_plus
            query = command[len("search for "):].strip()
            webbrowser.open(
                "https://www.google.com/search?q="
                + quote_plus(query)
            )
            return True, f"Searched for {query}"

        if text.startswith("make a folder called "):
            folder = command[len("make a folder called "):].strip()

            if (
                not folder
                or "/" in folder
                or folder in (".", "..")
            ):
                return False, "Please provide a simple folder name."

            path = os.path.join(os.path.expanduser("~"), folder)

            try:
                os.makedirs(path, exist_ok=True)
                return True, f"Folder created: {path}"
            except OSError as error:
                return False, str(error)

        if text in ("take a screenshot", "screenshot"):
            if shutil.which("gnome-screenshot"):
                subprocess.Popen(
                    ["gnome-screenshot"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True, "Screenshot tool launched"

            return False, "Screenshot tool is unavailable."

        if text in ("turn off the lights", "turn on the lights"):
            return False, "Smart-home control is not implemented."

        return False, (
            "Command not recognized by this GUI demo. "
            "Try 'open YouTube', 'open Google', "
            "'open terminal', or 'search for cats'."
        )

    def _result_screen(self, success, message):
        self.clear_content()

        frame = tk.Frame(self.content, bg=BG)
        frame.pack(fill="both", expand=True)

        card = tk.Frame(frame, bg=BG)
        card.place(relx=0.5, rely=0.48, anchor="center")

        color = GREEN if success else RED
        symbol = "✓" if success else "!"

        tk.Label(
            card,
            text=symbol,
            fg="white",
            bg=color,
            font=("Arial", 27, "bold"),
            width=3,
            height=1,
            relief="ridge",
            bd=3
        ).pack(pady=8)

        tk.Label(
            card,
            text="Done!" if success else "Something Went Wrong",
            fg=TEXT,
            bg=BG,
            font=FONT_BOLD
        ).pack(pady=(4, 7))

        tk.Label(
            card,
            text=message,
            fg=TEXT,
            bg=BG,
            font=FONT,
            wraplength=390,
            justify="center"
        ).pack(pady=(0, 16))

        tk.Button(
            card,
            text="⌂  Back to Home",
            command=lambda: self.show_page("Home"),
            bg="#343438",
            fg="white",
            bd=0,
            padx=20,
            pady=8
        ).pack()

        self.status_message.set("How Can I Help You Today ?")
        self.after_idle(self._apply_theme_tree)

    # -------------------- History --------------------

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
        tk.Label(
            self.content,
            text="Command History",
            fg=TEXT,
            bg=BG,
            font=FONT_TITLE
        ).pack(anchor="w", pady=(12, 18))

        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", pady=(0, 8))

        tk.Label(
            top, text="Recent commands",
            fg=MUTED, bg=BG, font=FONT_SMALL
        ).pack(side="left")

        tk.Button(
            top,
            text="▤  Clear History",
            command=self.clear_history,
            bg="#343438",
            fg=TEXT,
            activebackground=ORANGE,
            bd=0,
            padx=10,
            pady=6
        ).pack(side="right")

        table = tk.Frame(self.content, bg=BG)
        table.pack(fill="both", expand=True)

        header = tk.Frame(table, bg="#343438")
        header.pack(fill="x", pady=(0, 5))

        for label, width in (
            ("Command", 1),
            ("Time", 12),
            ("Status", 12)
        ):
            tk.Label(
                header,
                text=label,
                bg="#343438",
                fg=TEXT,
                anchor="w",
                padx=8,
                pady=7,
                width=width
            ).pack(
                side="left",
                fill="x",
                expand=(label == "Command")
            )

        if not self.history:
            tk.Label(
                table,
                text="No commands yet",
                bg=BG,
                fg=MUTED,
                font=FONT
            ).pack(pady=35)

        for item in self.history:
            row = tk.Frame(table, bg="#292B30")
            row.pack(fill="x", pady=2)

            tk.Label(
                row,
                text="🎙 " + item["command"],
                bg="#292B30",
                fg=TEXT,
                anchor="w",
                padx=8,
                pady=8
            ).pack(side="left", fill="x", expand=True)

            tk.Label(
                row,
                text=item["time"],
                bg="#292B30",
                fg=TEXT,
                width=12
            ).pack(side="left")

            ok = item["status"] == "Success"
            mark = (
                "✓" if ok else
                ("×" if item["status"] == "Failed" else "•")
            )

            tk.Label(
                row,
                text=mark,
                bg="#292B30",
                fg=GREEN if ok else (
                    RED if item["status"] == "Failed" else MUTED
                ),
                width=5,
                font=("Arial", 15, "bold")
            ).pack(side="right")

    def clear_history(self):
        if messagebox.askyesno(
            "Clear History",
            "Delete all command history?",
            parent=self
        ):
            self.history.clear()
            self.show_page("History")

    # -------------------- Settings --------------------

    def _settings_page(self):
        tk.Label(
            self.content,
            text="Settings",
            fg=TEXT,
            bg=BG,
            font=FONT_TITLE
        ).pack(anchor="w", pady=(12, 18))

        panel = tk.Frame(self.content, bg=BG)
        panel.pack(fill="x")

        self._setting_row(
            panel, "◎", "Language", self._language_control
        )
        self._setting_row(
            panel, "◖", "Sound Feedback", self._sound_control
        )
        self._setting_row(
            panel, "◇", "Confirmation before action",
            self._confirmation_control
        )
        self._setting_row(
            panel, "☼", "Mode", self._mode_control
        )

    def _setting_row(self, parent, icon, title, control_builder):
        row = tk.Frame(parent, bg="#292B30")
        row.pack(fill="x", pady=4)

        tk.Label(
            row, text=icon, bg="#292B30",
            fg=MUTED, font=("Arial", 15), width=3
        ).pack(side="left", padx=(6, 2), pady=7)

        tk.Label(
            row, text=title, bg="#292B30",
            fg=TEXT, font=FONT, anchor="w"
        ).pack(side="left", fill="x", expand=True, pady=10)

        control_builder(row)

    def _language_control(self, row):
        menu = tk.OptionMenu(
            row, self.language, "English", "Arabic"
        )
        menu.configure(
            bg="#D8D8D8", fg="#17191D",
            activebackground=ORANGE, bd=0, width=10
        )
        menu["menu"].configure(
            bg="#D8D8D8", fg="#17191D"
        )
        menu.pack(side="right", padx=10, pady=5)

    def _sound_control(self, row):
        self._toggle_button(
            row,
            self.sound_feedback,
            lambda: self._set_sound(not self.sound_feedback)
        )

    def _set_sound(self, value):
        self.sound_feedback = value
        self.show_page("Settings")

    def _confirmation_control(self, row):
        self._toggle_button(
            row,
            self.confirm_before_action,
            lambda: self._set_confirmation(
                not self.confirm_before_action
            )
        )

    def _set_confirmation(self, value):
        self.confirm_before_action = value
        self.show_page("Settings")

    def _toggle_button(self, row, value, command):
        tk.Button(
            row,
            text="●" if value else "○",
            command=command,
            bg=GREEN if value else "#77797D",
            fg="white",
            activebackground=ORANGE,
            bd=0,
            width=4,
            font=("Arial", 13, "bold")
        ).pack(side="right", padx=12, pady=6)

    def _mode_control(self, row):
        tk.Button(
            row,
            text="☼   ☾",
            command=self.toggle_theme,
            bg="#41454D",
            fg=TEXT,
            activebackground=ORANGE,
            bd=0,
            padx=12,
            pady=5
        ).pack(side="right", padx=10, pady=5)

    # -------------------- Themes --------------------

    def _palette(self):
        if self.light_mode:
            return {
                "bg": "#F3F3F5",
                "panel": "#FFFFFF",
                "sidebar": "#E3E3E6",
                "text": "#202126",
                "muted": "#5C5D63",
                "row": "#E8E8EC",
                "header": "#D8D9DE",
                "button": "#C96A45",
                "entry": "#FFFFFF"
            }

        return {
            "bg": BG,
            "panel": PANEL,
            "sidebar": SIDEBAR,
            "text": TEXT,
            "muted": MUTED,
            "row": "#292B30",
            "header": "#343438",
            "button": BUTTON,
            "entry": "#292B30"
        }

    def _apply_theme_tree(self):
        pal = self._palette()

        bg_map = {
            "#17191D": pal["bg"],
            "#202226": pal["panel"],
            "#3A3A3A": pal["sidebar"],
            "#292B30": pal["row"],
            "#343438": pal["header"],
            "#41454D": pal["header"],
            "#D8D8D8": (
                "#E1E1E5" if self.light_mode else "#D8D8D8"
            ),
            "black": "#FFFFFF" if self.light_mode else "black",
            "#F3F3F5": pal["bg"],
            "#FFFFFF": pal["panel"],
            "#E3E3E6": pal["sidebar"],
            "#E8E8EC": pal["row"],
            "#D8D9DE": pal["header"],
            "#5C5D63": pal["muted"]
        }

        fg_map = {
            "#F4F0F0": pal["text"],
            "#202126": pal["text"],
            "#B8B5B8": pal["muted"],
            "#5C5D63": pal["muted"]
        }

        def visit(widget):
            try:
                options = widget.configure()

                if "background" in options or "bg" in options:
                    old_bg = widget.cget("bg")
                    if old_bg in bg_map:
                        widget.configure(bg=bg_map[old_bg])

                if "foreground" in options or "fg" in options:
                    old_fg = widget.cget("fg")
                    if old_fg in fg_map:
                        widget.configure(fg=fg_map[old_fg])

                if "insertbackground" in options:
                    widget.configure(insertbackground=pal["text"])

            except (tk.TclError, KeyError):
                pass

            for child in widget.winfo_children():
                visit(child)

        visit(self)

    def toggle_theme(self):
        self.light_mode = not self.light_mode
        self.show_page(self.current_page)


if __name__ == "__main__":
    app = VoxyApp()
    app.mainloop()
