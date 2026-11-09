
#!/usr/bin/env python3

from datetime import datetime
from pathlib import Path
import os
import threading
import traceback
import tkinter as tk
from tkinter import messagebox

from audio_service_AI import listen_and_transcribe
from command_understanding import CommandUnderstanding
from execution import LinuxExecutor


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

        self.title("Voxy - Linux AI Assistant")
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
        self.continuous_listening = True

        api_key = os.environ.get("GROQ_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is missing.\n"
                "Set your API key before starting Voxy."
            )

        self.command_engine = CommandUnderstanding(api_key)
        self.execution = LinuxExecutor()

        self.language = tk.StringVar(value="English")

        self.status_message = tk.StringVar(
            value="How Can I Help You Today ?"
        )

        self.command_var = tk.StringVar()

        try:
            assets = (
                Path(__file__).resolve().parent
                / "voxy_v2"
                / "assets"
            )

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

    # =====================================
    # MAIN INTERFACE
    # =====================================

    def _build_shell(self):

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(
            self.body,
            bg=SIDEBAR,
            width=175
        )

        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo = tk.Frame(
            self.sidebar,
            bg=SIDEBAR,
            height=88
        )

        logo.pack(fill="x")
        logo.pack_propagate(False)

        tk.Label(
            logo,
            text="〰V〰",
            fg=ORANGE,
            bg=SIDEBAR,
            font=("Arial", 23, "bold")
        ).pack(pady=(12, 0))

        tk.Label(
            logo,
            text="Voxy",
            fg=TEXT,
            bg=SIDEBAR,
            font=FONT_SMALL
        ).pack()

        self.nav_buttons = {}

        for name, icon in (
            ("Home", "⌂"),
            ("History", "◴"),
            ("Settings", "⚙")
        ):

            button = tk.Button(
                self.sidebar,
                text=f"{icon}    {name}",
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
            side="left",
            fill="both",
            expand=True,
            padx=18,
            pady=14
        )

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

    # =====================================
    # LOGO
    # =====================================

    def _logo_mark(self, parent, size=64):

        if self._logo_image is not None:

            factor = max(
                1,
                round(400 / max(size, 1))
            )

            image = self._logo_image.subsample(
                factor,
                max(1, factor // 2)
            )

            label = tk.Label(
                parent,
                image=image,
                bg=self._palette()["bg"],
                bd=0
            )

            label.image = image
            label.pack()

            return label

        canvas = tk.Canvas(
            parent,
            width=size,
            height=size,
            bg=self._palette()["bg"],
            highlightthickness=0
        )

        canvas.pack()

        canvas.create_text(
            size / 2,
            size / 2,
            text="〰V〰",
            fill=ORANGE,
            font=("Arial", int(size * 0.25), "bold")
        )

        return canvas

    # =====================================
    # HOME PAGE
    # =====================================

    def _home_page(self):

        center = tk.Frame(self.content, bg=BG)

        center.place(
            relx=0.5,
            rely=0.48,
            anchor="center"
        )

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
            text="Press 🎙 to start continuous mode",
            bg=BG,
            fg=TEXT,
            font=FONT_SMALL
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

        entry.pack(
            side="left",
            ipady=8,
            padx=(0, 7)
        )

        entry.bind(
            "<Return>",
            lambda event: self.submit_command()
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

    # =====================================
    # MICROPHONE
    # =====================================

    def start_listening(self):

        if self._audio_busy:
            return

        self._audio_busy = True

        self.status_message.set("Listening… Speak now!")
        self._show_audio_status("Listening… Speak now!")

        threading.Thread(
            target=self._audio_worker,
            daemon=True
        ).start()

    def _show_audio_status(self, message):

        self.clear_content()

        frame = tk.Frame(self.content, bg=BG)
        frame.pack(fill="both", expand=True)

        inner = tk.Frame(frame, bg=BG)

        inner.place(
            relx=0.5,
            rely=0.48,
            anchor="center"
        )

        self._logo_mark(inner, 105)

        tk.Label(
            inner,
            text="VOXY",
            fg=TEXT,
            bg=BG,
            font=FONT_TITLE
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

        self.after_idle(self._apply_theme_tree)

    def _update_audio_status(self, message):

        def update():

            if hasattr(self, "audio_status_label"):

                if self.audio_status_label.winfo_exists():
                    self.audio_status_label.configure(
                        text=message
                    )

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

        if not recognized_text or not recognized_text.strip():

            self._show_audio_error(
                "No clear speech detected."
            )

            return

        self.command_var.set(recognized_text)
        self.submit_command()

    def _show_audio_error(self, error_message):

        self._audio_busy = False

        print("Audio error:", error_message, flush=True)

        self.status_message.set(
            "Listening error. Please try again."
        )

        self.clear_content()

        frame = tk.Frame(self.content, bg=BG)
        frame.pack(fill="both", expand=True)

        card = tk.Frame(frame, bg=BG)

        card.place(
            relx=0.5,
            rely=0.48,
            anchor="center"
        )

        tk.Label(
            card,
            text="Microphone / Transcription Error",
            fg=RED,
            bg=BG,
            font=FONT_BOLD
        ).pack(pady=8)

        tk.Label(
            card,
            text=error_message,
            fg=TEXT,
            bg=BG,
            wraplength=400,
            justify="center"
        ).pack(pady=8)

        tk.Button(
            card,
            text="Try Again",
            command=self.start_listening,
            bg=BUTTON,
            fg="white",
            bd=0,
            padx=20,
            pady=8
        ).pack(pady=8)

        if self.continuous_listening:
            self.after(3000, self._resume_listening)

    def _resume_listening(self):

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

            self.status_message.set(
                "Please enter a command first."
            )

            return

        self._processing_screen(command)

    def _processing_screen(self, command):

        self.clear_content()

        outer = tk.Frame(self.content, bg=BG)
        outer.pack(fill="both", expand=True)

        card = tk.Frame(outer, bg=BG)

        card.place(
            relx=0.5,
            rely=0.48,
            anchor="center"
        )

        tk.Label(
            card,
            text="⚙",
            fg="#DCE8F8",
            bg="#3D4653",
            font=("Arial", 25),
            padx=12,
            pady=5
        ).pack(pady=12)

        tk.Label(
            card,
            text="Processing your command…",
            fg=TEXT,
            bg=BG,
            font=FONT
        ).pack(pady=8)

        bar = tk.Frame(
            card,
            bg="#D8D8D8",
            width=250,
            height=7
        )

        bar.pack(pady=3)
        bar.pack_propagate(False)

        fill = tk.Frame(
            bar,
            bg=ORANGE,
            height=7
        )

        fill.place(
            x=0,
            y=0,
            relheight=1,
            relwidth=0.8
        )

        tk.Label(
            card,
            text="Consulting Groq AI & Executing…",
            fg=MUTED,
            bg=BG,
            font=FONT_SMALL
        ).pack(pady=10)

        self.after_idle(self._apply_theme_tree)

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
    # RESULT SCREEN
    # =====================================

    def _result_screen(self, success, message):

        self.clear_content()

        frame = tk.Frame(self.content, bg=BG)
        frame.pack(fill="both", expand=True)

        card = tk.Frame(frame, bg=BG)

        card.place(
            relx=0.5,
            rely=0.48,
            anchor="center"
        )

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
            wraplength=450,
            justify="left"
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

        self.status_message.set(
            "How Can I Help You Today ?"
        )

        self.command_var.set("")

        self.after_idle(self._apply_theme_tree)

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
            top,
            text="Recent commands",
            fg=MUTED,
            bg=BG,
            font=FONT_SMALL
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
            ).pack(
                side="left",
                fill="x",
                expand=True
            )

            tk.Label(
                row,
                text=item["time"],
                bg="#292B30",
                fg=TEXT,
                width=12
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

    # =====================================
    # SETTINGS
    # =====================================

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
            panel,
            "◎",
            "Language",
            self._language_control
        )

        self._setting_row(
            panel,
            "◖",
            "Sound Feedback",
            self._sound_control
        )

        self._setting_row(
            panel,
            "◇",
            "Confirmation before action",
            self._confirmation_control
        )

        self._setting_row(
            panel,
            "☼",
            "Mode",
            self._mode_control
        )

    def _setting_row(
        self,
        parent,
        icon,
        title,
        control_builder
    ):

        row = tk.Frame(parent, bg="#292B30")
        row.pack(fill="x", pady=4)

        tk.Label(
            row,
            text=icon,
            bg="#292B30",
            fg=MUTED,
            font=("Arial", 15),
            width=3
        ).pack(
            side="left",
            padx=(6, 2),
            pady=7
        )

        tk.Label(
            row,
            text=title,
            bg="#292B30",
            fg=TEXT,
            font=FONT,
            anchor="w"
        ).pack(
            side="left",
            fill="x",
            expand=True,
            pady=10
        )

        control_builder(row)

    def _language_control(self, row):

        menu = tk.OptionMenu(
            row,
            self.language,
            "English",
            "Arabic"
        )

        menu.configure(
            bg="#D8D8D8",
            fg="#17191D",
            activebackground=ORANGE,
            bd=0,
            width=10
        )

        menu["menu"].configure(
            bg="#D8D8D8",
            fg="#17191D"
        )

        menu.pack(
            side="right",
            padx=10,
            pady=5
        )

    def _sound_control(self, row):

        self._toggle_button(
            row,
            self.sound_feedback,
            lambda: self._set_sound(
                not self.sound_feedback
            )
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
        ).pack(
            side="right",
            padx=12,
            pady=6
        )

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
        ).pack(
            side="right",
            padx=10,
            pady=5
        )

    # =====================================
    # THEMES
    # =====================================

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
            "black": (
                "#FFFFFF" if self.light_mode else "black"
            ),
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

                    old_bg = str(widget.cget("bg"))

                    if old_bg in bg_map:
                        widget.configure(
                            bg=bg_map[old_bg]
                        )

                if "foreground" in options or "fg" in options:

                    old_fg = str(widget.cget("fg"))

                    if old_fg in fg_map:
                        widget.configure(
                            fg=fg_map[old_fg]
                        )

                if "insertbackground" in options:
                    widget.configure(
                        insertbackground=pal["text"]
                    )

            except Exception:
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
