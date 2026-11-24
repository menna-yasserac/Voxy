#!/usr/bin/env python3
"""Apply the Voxy wake-word/session integration to the teammate's app.py.

Run this from the directory containing app.py:
    python3 apply_wake_merge.py
A timestamped backup is created before app.py is changed.
"""
from pathlib import Path
from datetime import datetime
import re
import shutil
import sys

APP = Path(__file__).resolve().parent / "app.py"
if not APP.is_file():
    raise SystemExit("ERROR: app.py must be in the same folder as this script.")

source = APP.read_text(encoding="utf-8")
original = source

def replace_once(old, new, label):
    global source
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: expected exactly one match for {label}, found {count}. "
            "No changes were written."
        )
    source = source.replace(old, new, 1)

# Import the dedicated wake-word service.
replace_once(
    "from security import SecurityManager\n",
    "from security import SecurityManager\nfrom wake_word_service import WakeWordService\n",
    "wake-word import",
)

# Create the service before building the UI.  Its callback is marshalled
# onto Tk's main thread by _on_wake_detected().
replace_once(
    "        self.mic_level = MicLevel()\n",
    "        self.mic_level = MicLevel()\n"
    "        self.wake_word = WakeWordService(\n"
    "            on_wake=self._on_wake_detected,\n"
    "            model_path=Path(__file__).resolve().parent / \"models\" / \"voxy_single.onnx\",\n"
    "            threshold=0.50,\n"
    "        )\n",
    "wake-word service initialization",
)

# Start automatic wake detection after Tk has finished constructing.
replace_once(
    "        self.after(33, self._tick)\n",
    "        self.after(33, self._tick)\n"
    "        # Start hands-free wake detection automatically on launch.\n"
    "        self.after(1000, self.wake_word.start)\n",
    "automatic wake-word startup",
)

# Add the thread-safe callback.
replace_once(
    "    # =====================================\n"
    "    # SESSION MANAGEMENT\n"
    "    # =====================================\n\n"
    "    def start_session(self):\n",
    "    # =====================================\n"
    "    # SESSION MANAGEMENT\n"
    "    # =====================================\n\n"
    "    def _on_wake_detected(self):\n"
    "        \"\"\"Wake-word callback; Tk operations must run on the UI thread.\"\"\"\n"
    "        try:\n"
    "            self.after(0, self.start_session)\n"
    "        except tk.TclError:\n"
    "            pass\n\n"
    "    def start_session(self):\n",
    "wake-word callback",
)

# Stop the wake listener before opening the command-recording microphone.
replace_once(
    "        if self.session_active:\n"
    "            self._reset_session_timeout()\n",
    "        # The wake listener and command recorder must never share the mic.\n"
    "        if not self.session_active:\n"
    "            self.wake_word.stop()\n\n"
    "        if self.session_active:\n"
    "            self._reset_session_timeout()\n",
    "stop wake listener on session start",
)

# Restart wake detection only after the session is fully inactive.
replace_once(
    "        if self.current_page == \"Home\":\n"
    "            self._render_bottom()\n\n"
    "    # =====================================\n"
    "    # VOICE FEEDBACK HELPERS\n",
    "        if self.current_page == \"Home\":\n"
    "            self._render_bottom()\n\n"
    "        # Return to hands-free wake-word mode after the 60-second idle timeout.\n"
    "        if not getattr(self, \"_closing\", False):\n"
    "            self.after(300, self.wake_word.start)\n\n"
    "    # =====================================\n"
    "    # VOICE FEEDBACK HELPERS\n",
    "restart wake listener after session ends",
)

# Ensure shutdown closes the wake listener and prevents it restarting.
replace_once(
    "    def _on_close(self):\n"
    "        if hasattr(self.execution, \"clear_auto_save\"):\n",
    "    def _on_close(self):\n"
    "        self._closing = True\n"
    "        self.wake_word.stop()\n"
    "        if hasattr(self.execution, \"clear_auto_save\"):\n",
    "wake listener shutdown",
)

# Avoid accidentally starting a session after window close.
if "self._closing = False" not in source:
    replace_once(
        "        self._audio_busy = False\n\n        # Session state\n",
        "        self._audio_busy = False\n"
        "        self._closing = False\n\n"
        "        # Session state\n",
        "closing flag",
    )

if source == original:
    raise SystemExit("No changes made: app.py already appears patched.")

backup = APP.with_name(
    f"app.py.backup_before_wake_merge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
)
shutil.copy2(APP, backup)

# Syntax-check before writing the modified file.
compile(source, str(APP), "exec")
APP.write_text(source, encoding="utf-8")

print(f"Updated: {APP}")
print(f"Backup:  {backup}")
print("Wake-word integration added.")
print("The detector starts on launch, stops while a voice session is active,")
print("and restarts after the 60-second idle session timeout.")
