import os
import re
import sys
import json
import time
import shutil
import difflib
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path
from urllib.parse import quote_plus, unquote

from audio_service_AI import (
    speak_clarification,
    speak_error,
    speak_success,
)
from security import SecurityManager

try:
    from atspi_controller import ATSPIController
    ATSPI_AVAILABLE = True
except (ImportError, OSError):
    ATSPIController = None
    ATSPI_AVAILABLE = False

try:
    from screen_control import (
        ScreenController, is_dangerous, is_here, strip_ui_words
    )
    SCREEN_CONTROL_AVAILABLE = True
except ImportError:
    ScreenController = None
    SCREEN_CONTROL_AVAILABLE = False


def _get_session_type():
    return (os.environ.get("XDG_SESSION_TYPE") or "x11").lower()


def which(name):
    return shutil.which(name)


class LinuxExecutor:

    SKIP_DIRS = {
        "proc", "sys", "dev", "run", "snap",
        "node_modules", "__pycache__", ".cache",
        "Trash", ".Trash-1000", ".git", ".venv", "venv"
    }

    PRIORITY_SUBDIRS = (
        "Desktop", "Documents", "Downloads", "Projects",
        "Videos", "Music", "Pictures"
    )

    APP_ALIASES = {
        "terminal": [
            "gnome-terminal", "ptyxis", "konsole", "xfce4-terminal",
            "mate-terminal", "tilix", "alacritty", "kitty", "x-terminal-emulator"
        ],
        "الترمنال": [
            "gnome-terminal", "ptyxis", "konsole", "xfce4-terminal", "x-terminal-emulator"
        ],
        "الترمينال": [
            "gnome-terminal", "ptyxis", "konsole", "xfce4-terminal", "x-terminal-emulator"
        ],
        "ترمينال": [
            "gnome-terminal", "ptyxis", "konsole", "xfce4-terminal", "x-terminal-emulator"
        ],
        "vs code": ["code"],
        "vscode": ["code"],
        "visual studio code": ["code"],
        "في اس كود": ["code"],
        "files": ["nautilus", "thunar", "dolphin", "nemo"],
        "file manager": ["nautilus", "thunar", "dolphin", "nemo"],
        "settings": ["gnome-control-center"],
        "calculator": ["gnome-calculator", "kcalc", "galculator"],
        "text editor": ["gnome-text-editor", "gedit", "xed", "mousepad", "kate"],
        "notepad": ["gnome-text-editor", "gedit", "xed", "mousepad", "kate"],
    }

    def __init__(self, understanding_engine=None):
        self.understanding_engine = understanding_engine
        self.security = SecurityManager()

        self.last_video_query = None
        self.last_video_ids = []
        self.last_video_titles = []

        self.last_search_candidates = []
        self.pending_operation = None   # "open" | "list" | "delete" | "move" | "rename"
        self.pending_extra = {}

        self.pending_confirmation_payload = None
        self.delete_batch = None
        self.pending_confirmation_question = None
        self._auto_save_editor_opened = False

        # Context persistence for accessibility chaining
        self.context_hold_duration = 30.0
        self.last_context_update_time = 0.0
        self.persisted_context_target = None

        self.memory_file = Path.home() / ".local" / "share" / "voxy" / "learned_sites.json"
        self.learned_sites = self._load_learned_sites()

        self.auto_save_file = Path.home() / ".local" / "share" / "voxy" / "auto_save.txt"
        self.clear_auto_save()

        self.atspi = None
        if ATSPI_AVAILABLE:
            try:
                self.atspi = ATSPIController()
                print("[AT-SPI] Controller initialized.")
            except Exception as error:
                print(f"[AT-SPI] Initialization failed: {error}")

        self.screen = None
        if SCREEN_CONTROL_AVAILABLE:
            try:
                self.screen = ScreenController()
                print("[Screen] Screen controller initialized.")
            except Exception as error:
                print(f"[Screen] Initialization failed: {error}")

    def clear_auto_save(self):
        self._auto_save_editor_opened = False
        try:
            self.auto_save_file.parent.mkdir(parents=True, exist_ok=True)
            self.auto_save_file.write_text("", encoding="utf-8")
        except OSError as error:
            print(f"[auto_save] Clear error: {error}")

    def _append_and_open_auto_save(self, folder_path: Path, items: list):
        try:
            self.auto_save_file.parent.mkdir(parents=True, exist_ok=True)
            existing = ""
            if self.auto_save_file.exists():
                existing = self.auto_save_file.read_text(encoding="utf-8")

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            block_lines = []
            if existing.strip():
                block_lines.append("")
                block_lines.append("=" * 65)
                block_lines.append("")

            block_lines.append(f"Folder Name : {folder_path.name}")
            block_lines.append(f"Full Path   : {folder_path}")
            block_lines.append(f"Listed At   : {timestamp}")
            block_lines.append("-" * 65)

            if not items:
                block_lines.append("    (Folder is empty)")
            else:
                for item in items:
                    kind = "[Folder]" if item.is_dir() else "[File]  "
                    block_lines.append(f"    {kind}    {item.name}")

            block_lines.append("")
            new_content = existing + "\n".join(block_lines) + "\n"
            self.auto_save_file.write_text(new_content, encoding="utf-8")

            if not self._auto_save_editor_opened:
                editor = (
                    which("gnome-text-editor")
                    or which("gedit")
                    or which("xed")
                    or which("mousepad")
                    or which("kate")
                    or which("xdg-open")
                )
                if editor:
                    subprocess.Popen(
                        [editor, str(self.auto_save_file)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                    self._auto_save_editor_opened = True
        except OSError as error:
            print(f"[auto_save] Write/Open error: {error}")

    def _sync_pending_candidates(self, candidates, operation=None, extra=None):
        self.last_search_candidates = list(candidates) if candidates else []
        self.pending_operation = operation if self.last_search_candidates else None
        self.pending_extra = dict(extra) if (self.last_search_candidates and extra) else {}

        if self.understanding_engine and hasattr(self.understanding_engine, "set_pending_file_selection"):
            safe_extra = {k: v for k, v in self.pending_extra.items() if k != "confirm_callback"}
            self.understanding_engine.set_pending_file_selection(
                bool(self.last_search_candidates),
                self.last_search_candidates,
                operation=self.pending_operation,
                extra=safe_extra
            )

    def update_persisted_context(self, target_identifier=None):
        if target_identifier:
            self.persisted_context_target = target_identifier
        self.last_context_update_time = time.time()

    def get_persisted_target(self):
        if time.time() - self.last_context_update_time < self.context_hold_duration:
            return self.persisted_context_target
        return None

    def clear_persisted_context(self):
        self.persisted_context_target = None
        self.last_context_update_time = 0.0

    def _request_voice_confirmation(self, question, payload):
        self.pending_confirmation_question = str(question)
        self.pending_confirmation_payload = payload
        if self.understanding_engine and hasattr(self.understanding_engine, "set_pending_confirmation"):
            self.understanding_engine.set_pending_confirmation(True, self.pending_confirmation_question)
        return "confirmation", self.pending_confirmation_question

    def clear_pending_confirmation(self):
        self.pending_confirmation_question = None
        self.pending_confirmation_payload = None
        if self.understanding_engine and hasattr(self.understanding_engine, "set_pending_confirmation"):
            self.understanding_engine.set_pending_confirmation(False)

    def run_command(self, args, timeout=15):
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def normalize_name(self, name):
        name = str(name or "").strip().lower()
        return re.sub(r"\s+", " ", name)

    def _ordered_candidates(self, primary, fallback_english=None):
        ordered = []
        for item in (primary, fallback_english):
            if item and str(item).strip():
                val = str(item).strip()
                if val not in ordered:
                    ordered.append(val)
        return ordered

    def _find_installed_desktop_app(self, query_names):
        clean_queries = [
            self.normalize_name(q) for q in query_names
            if q and str(q).strip()
        ]
        if not clean_queries:
            return None

        for q in clean_queries:
            if q in self.APP_ALIASES:
                for bin_candidate in self.APP_ALIASES[q]:
                    exe = which(bin_candidate)
                    if exe:
                        return [exe]

        desktop_dirs = [
            Path("/usr/share/applications"),
            Path("/usr/local/share/applications"),
            Path("/var/lib/snapd/desktop/applications"),
            Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local/share/applications",
            Path.home() / ".local/share/flatpak/exports/share/applications",
        ]

        for q in clean_queries:
            for cand in (q, q.replace(" ", "-"), q.replace(" ", "")):
                exe = which(cand)
                if exe:
                    return [exe]

            best_cmd = None
            best_score = 0

            for d in desktop_dirs:
                if not d.exists():
                    continue
                for desktop_file in d.glob("*.desktop"):
                    stem = desktop_file.stem.lower()
                    app_name = ""
                    generic_name = ""
                    keywords = ""
                    exec_cmd = ""
                    no_display = False

                    try:
                        for line in desktop_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                            if line.startswith("NoDisplay=true"):
                                no_display = True
                            elif line.startswith("Name=") and not app_name:
                                app_name = line.split("=", 1)[1].strip().lower()
                            elif line.startswith("GenericName=") and not generic_name:
                                generic_name = line.split("=", 1)[1].strip().lower()
                            elif line.startswith("Keywords=") and not keywords:
                                keywords = line.split("=", 1)[1].strip().lower()
                            elif line.startswith("Exec=") and not exec_cmd:
                                raw_exec = line.split("=", 1)[1].strip()
                                exec_cmd = re.sub(r"\s+%[a-zA-Z]", "", raw_exec).strip()
                    except OSError:
                        continue

                    if no_display or not exec_cmd:
                        continue

                    parts = exec_cmd.split()
                    if not parts or not which(parts[0]):
                        continue

                    score = 0
                    if q in (app_name, stem, generic_name):
                        score = 100
                    elif len(q) >= 3 and (q in app_name or q in stem):
                        score = 80
                    elif len(q) >= 3 and (q in generic_name or q in keywords):
                        score = 65

                    if score > best_score:
                        best_score = score
                        best_cmd = parts

            if best_cmd:
                return best_cmd

        return None

    def _get_process_info_map(self):
        my_pid = str(os.getpid())
        proc_map = {}
        res = self.run_command(["ps", "-eo", "pid=,comm=,args="], timeout=5)
        if res and res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) < 2:
                    continue
                pid, comm = parts[0], parts[1]
                args = parts[2] if len(parts) > 2 else comm
                if pid.isdigit() and pid != my_pid:
                    proc_map[pid] = {
                        "pid": pid,
                        "comm": comm.lower(),
                        "args": args.lower()
                    }
        return proc_map

    def get_live_open_state(self):
        proc_map = self._get_process_info_map()
        open_items = []
        seen_win_ids = set()

        if which("wmctrl"):
            res = self.run_command(["wmctrl", "-lpx"], timeout=5)
            if res and res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.split(None, 5)
                    if len(parts) < 5:
                        continue
                    win_id, desktop, pid, wm_class = parts[0], parts[1], parts[2], parts[3]
                    if desktop == "-1":
                        continue
                    title = parts[5].strip() if len(parts) > 5 else ""
                    p_info = proc_map.get(pid, {})
                    open_items.append({
                        "window_id": win_id,
                        "pid": pid,
                        "wm_class": wm_class.lower(),
                        "title": title,
                        "comm": p_info.get("comm", ""),
                        "args": p_info.get("args", "")
                    })
                    seen_win_ids.add(win_id)

        if which("xdotool"):
            res = self.run_command(["xdotool", "search", "--onlyvisible", "--name", ".*"], timeout=5)
            if res and res.returncode == 0:
                for win_id in res.stdout.splitlines():
                    win_id = win_id.strip()
                    if not win_id or win_id in seen_win_ids:
                        continue
                    pid_res = self.run_command(["xdotool", "getwindowpid", win_id], timeout=2)
                    name_res = self.run_command(["xdotool", "getwindowname", win_id], timeout=2)
                    pid = pid_res.stdout.strip() if pid_res and pid_res.returncode == 0 else ""
                    title = name_res.stdout.strip() if name_res and name_res.returncode == 0 else ""
                    p_info = proc_map.get(pid, {})
                    open_items.append({
                        "window_id": win_id,
                        "pid": pid,
                        "wm_class": "",
                        "title": title,
                        "comm": p_info.get("comm", ""),
                        "args": p_info.get("args", "")
                    })

        return open_items

    def _match_live_targets(self, query_names):
        clean_queries = []
        for q in query_names:
            if not q or not str(q).strip():
                continue
            norm = self.normalize_name(q)
            clean_queries.append(norm)
            clean_queries.append(norm.replace(" ", ""))

            installed_cmd = self._find_installed_desktop_app([norm])
            if installed_cmd:
                clean_queries.append(os.path.basename(installed_cmd[0]).lower())

        clean_queries = list(dict.fromkeys(q for q in clean_queries if q))
        if not clean_queries:
            return [], []

        live_windows = self.get_live_open_state()
        matched_windows = []
        matched_pids = set()

        for win in live_windows:
            title_cf = win["title"].casefold()
            wm_class_cf = win["wm_class"].casefold()
            comm_cf = win["comm"].casefold()
            args_cf = win["args"].casefold()

            haystack = f"{title_cf} {wm_class_cf} {comm_cf} {args_cf}"

            for q in clean_queries:
                q_cf = q.casefold()
                if (
                    q_cf == title_cf
                    or q_cf in wm_class_cf
                    or q_cf in comm_cf
                    or (len(q_cf) >= 3 and q_cf in haystack)
                ):
                    matched_windows.append(win)
                    if win["pid"]:
                        matched_pids.add(win["pid"])
                    break

        if not matched_windows and not matched_pids:
            proc_map = self._get_process_info_map()
            for pid, info in proc_map.items():
                for q in clean_queries:
                    q_cf = q.casefold()
                    if (
                        q_cf == info["comm"]
                        or info["comm"].startswith(q_cf)
                        or (len(q_cf) >= 4 and f"/{q_cf}" in info["args"])
                    ):
                        matched_pids.add(pid)
                        break

        return matched_windows, list(matched_pids)

    def _wait_until_new_window_or_app_opens(self, query_names, before_win_ids, timeout=8.0):
        start = time.time()
        while time.time() - start < timeout:
            live_now = self.get_live_open_state()
            new_wins = [w for w in live_now if w["window_id"] not in before_win_ids]
            if new_wins:
                return True

            matched_wins, matched_pids = self._match_live_targets(query_names)
            if matched_wins:
                return True
            if matched_pids and (time.time() - start) >= 1.2:
                return True

            time.sleep(0.25)

        _, matched_pids = self._match_live_targets(query_names)
        return bool(matched_pids)

    def _normalize_atspi_result(self, result, operation):
        if isinstance(result, dict):
            success = bool(result.get("success", False))
            message = (
                result.get("message")
                or result.get("error")
                or f"AT-SPI {operation} completed."
            )
            return success, str(message)

        if isinstance(result, tuple) and len(result) >= 2:
            return bool(result[0]), str(result[1])

        if isinstance(result, bool):
            return result, (
                f"AT-SPI {operation} completed."
                if result else f"AT-SPI {operation} failed."
            )

        return False, f"Unexpected AT-SPI {operation} response."

    def list_ui_elements(self):
        if not self.atspi:
            return False, "AT-SPI is not available.", []

        try:
            result = self.atspi.list_elements()
            if isinstance(result, dict):
                success = bool(result.get("success", False))
                message = result.get("message", "")
                elements = result.get("elements", [])
                if not success:
                    return False, message or "Could not read UI elements.", []
                return True, "UI elements retrieved.", elements
            return False, "Unexpected AT-SPI response.", []
        except Exception as error:
            return False, str(error), []

    def click_element(self, data, bypass_confirm=False):
        if not isinstance(data, dict):
            return False, "Invalid click data."

        element_name = (
            data.get("element_name")
            or data.get("element")
            or data.get("target")
            or data.get("selection")
        )

        if not element_name:
            persisted = self.get_persisted_target()
            if persisted:
                element_name = persisted

        click_kind = str(data.get("action") or "").lower()
        button = "right" if "right" in click_kind else "left"
        double = "double" in click_kind

        if not element_name or (SCREEN_CONTROL_AVAILABLE and is_here(element_name)):
            x = data.get("x")
            y = data.get("y")
            if x is None or y is None:
                if not self.screen:
                    return False, "Screen control is not available."
                return self.screen.click_here(button, double)

        if (
            not bypass_confirm
            and element_name
            and SCREEN_CONTROL_AVAILABLE
            and is_dangerous(element_name)
        ):
            payload = {"kind": "click", "data": dict(data)}
            return self._request_voice_confirmation(
                f"هل أنت متأكد أنك تريد الضغط على '{element_name}'؟ (قولي موافقة أو إلغاء)",
                payload
            )

        x = data.get("x")
        y = data.get("y")
        if x is not None and y is not None:
            try:
                px, py = int(x), int(y)
            except (TypeError, ValueError):
                return False, "Invalid coordinates."

            if self.screen:
                from screen_control import click_xy
                return click_xy(px, py, button=button, double=double)

            if not which("xdotool"):
                return False, "xdotool is not installed."

            result = self.run_command([
                "xdotool", "mousemove", str(px), str(py), "click", "1"
            ])
            if result and result.returncode == 0:
                self.update_persisted_context()
                return True, "Clicked coordinates."
            return False, "Coordinate click failed."

        if element_name and self.atspi and button == "left" and not double:
            try:
                result = self.atspi.click(str(element_name))
                success, message = self._normalize_atspi_result(result, "click")
                if success:
                    self.update_persisted_context(element_name)
                    return True, message
                print(f"[AT-SPI] Click failed: {message}")
            except Exception as error:
                print(f"[AT-SPI] Click error: {error}")

        if element_name and self.screen:
            cleaned = strip_ui_words(element_name)
            try:
                matches, _ = self.screen.find_text(cleaned)
                from screen_control import pick_match, click_xy
                match, reason = pick_match(matches)

                if reason == "not_found":
                    return False, f"I couldn't find '{element_name}' on the screen."
                if reason == "ambiguous":
                    return False, (
                        f"I found '{element_name}' in more than one place. "
                        "Please say a longer or more specific name."
                    )

                if not match["whole_line"] and not bypass_confirm:
                    payload = {
                        "kind": "click_xy",
                        "x": match["x"] / self.screen.scale,
                        "y": match["y"] / self.screen.scale,
                        "button": button,
                        "double": double,
                        "label": match["text"],
                    }
                    return self._request_voice_confirmation(
                        f"هل تقصدين الضغط على '{match['text']}' (جزء من '{match['line_text']}')؟ قولي موافقة أو إلغاء.",
                        payload
                    )

                ok, message = click_xy(
                    match["x"] / self.screen.scale,
                    match["y"] / self.screen.scale,
                    button=button,
                    double=double
                )
                if not ok:
                    return False, message
                self.update_persisted_context(match["text"])
                return True, f"Clicked '{match['text']}' (found by reading the screen)."
            except Exception as error:
                return False, str(error)

        if not self.atspi:
            return False, "AT-SPI and screen control are unavailable."

        return False, (
            f"Could not click '{element_name}'. "
            "The element may not be accessible or may not support clicking."
        )

    def _type_raw_text(self, text):
        text_str = str(text)
        sess = _get_session_type()

        if sess == "wayland" and which("ydotool"):
            res = self.run_command(["ydotool", "type", "--", text_str], timeout=20)
            if res and res.returncode == 0:
                self.update_persisted_context()
                return True, "Text typed into the focused element."

        if which("xdotool"):
            result = self.run_command([
                "xdotool", "type", "--clearmodifiers", "--delay", "2", "--", text_str
            ], timeout=20)
            if result and result.returncode == 0:
                self.update_persisted_context()
                return True, "Text typed into the focused element."

        return False, "Typing failed (ensure xdotool or ydotool is running)."

    def type_text(self, text, element_name=None):
        if text is None:
            return False, "No text provided."

        if not element_name:
            persisted = self.get_persisted_target()
            if persisted:
                element_name = persisted

        if element_name:
            if self.atspi:
                try:
                    result = self.atspi.type_text(str(element_name), str(text))
                    success, message = self._normalize_atspi_result(result, "typing")
                    if success:
                        self.update_persisted_context(element_name)
                        return True, message
                except Exception:
                    pass

            clicked, click_msg = self.click_element({"target": str(element_name)}, bypass_confirm=True)
            if not clicked:
                return False, f"Could not find input box '{element_name}': {click_msg}"

            time.sleep(0.2)
            ok, type_msg = self._type_raw_text(text)
            if ok:
                self.update_persisted_context(element_name)
                return True, f"Typed '{text}' into '{element_name}'."
            return False, type_msg

        return self._type_raw_text(text)

    def _load_learned_sites(self):
        try:
            if self.memory_file.exists():
                data = json.loads(self.memory_file.read_text(encoding="utf-8"))
                cleaned = {}
                for k, v in data.items():
                    if isinstance(v, dict) and v.get("url"):
                        cleaned[k] = {"url": v["url"]}
                    elif isinstance(v, str):
                        cleaned[k] = {"url": v}
                return cleaned
        except Exception:
            pass
        return {}

    def _save_learned_sites(self):
        try:
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            self.memory_file.write_text(
                json.dumps(self.learned_sites, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _read_active_firefox_url_for_domain(self, domain_hint):
        try:
            import lz4.block
        except ImportError:
            lz4 = None

        ff_dir = Path.home() / ".mozilla" / "firefox"
        if not ff_dir.exists() or lz4 is None:
            return None

        clean_hint = re.sub(r"[^a-z0-9]", "", str(domain_hint or "").lower())
        if len(clean_hint) < 3:
            return None

        for recovery_file in ff_dir.glob("*.default*/sessionstore-backups/recovery.jsonlz4"):
            try:
                raw = recovery_file.read_bytes()
                if raw[:8] != b"mozLz40\0":
                    continue
                decompressed = lz4.block.decompress(raw[8:])
                session_data = json.loads(decompressed.decode("utf-8", errors="ignore"))
                for win in session_data.get("windows", []):
                    for tab in win.get("tabs", []):
                        entries = tab.get("entries", [])
                        idx = tab.get("index", len(entries)) - 1
                        if 0 <= idx < len(entries):
                            url = entries[idx].get("url", "")
                            if clean_hint in url.lower() and url.startswith(("http://", "https://")):
                                return url
            except Exception:
                continue
        return None

    def _verify_website(self, url, timeout=4):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
                    )
                },
                method="GET"
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.geturl()
        except urllib.error.HTTPError as error:
            if error.code in (403, 405, 429):
                return url
            return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None

    def _fetch_top_search_url(self, query):
        try:
            ddg_url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
            req = urllib.request.Request(
                ddg_url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                match = re.search(r'uddg=(https?%3A%2F%2F[^&"]+)', html)
                if match:
                    url = unquote(match.group(1))
                    if "duckduckgo.com" not in url:
                        return url
        except Exception:
            pass
        return None

    def _resolve_website(self, website, english_phonetic=None):
        raw_key = self.normalize_name(website)
        phonetic_key = self.normalize_name(english_phonetic) if english_phonetic else ""
        lookup_keys = [k for k in (raw_key, phonetic_key) if k]

        if not lookup_keys:
            return None, "Website name is missing."

        for k in lookup_keys:
            live_ff_url = self._read_active_firefox_url_for_domain(k)
            if live_ff_url and "google.com/search" not in live_ff_url:
                for save_k in lookup_keys:
                    self.learned_sites[save_k] = {"url": live_ff_url}
                self._save_learned_sites()
                self.update_persisted_context(website)
                return live_ff_url, "learned_login_url"

        if raw_key.startswith(("https://", "http://")):
            self.learned_sites[raw_key] = {"url": raw_key}
            self._save_learned_sites()
            self.update_persisted_context(website)
            return raw_key, "explicit_url"

        for k in lookup_keys:
            entry = self.learned_sites.get(k)
            if entry and entry.get("url"):
                for save_k in lookup_keys:
                    self.learned_sites[save_k] = {"url": entry["url"]}
                self._save_learned_sites()
                self.update_persisted_context(website)
                return entry["url"], "learned_direct_url"

        candidate_slug = phonetic_key or raw_key
        resolved_url = None

        if re.match(r"^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(/.*)?$", candidate_slug):
            verified = self._verify_website("https://" + candidate_slug)
            if verified:
                resolved_url = verified

        if not resolved_url and re.fullmatch(r"[a-zA-Z0-9-]+", candidate_slug):
            slug = candidate_slug.lower()
            for cand in (f"https://www.{slug}.com", f"https://{slug}.com"):
                verified = self._verify_website(cand)
                if verified:
                    resolved_url = verified
                    break

        if not resolved_url:
            resolved_url = self._fetch_top_search_url(english_phonetic or website)

        if resolved_url:
            for save_k in lookup_keys:
                self.learned_sites[save_k] = {"url": resolved_url}
            self._save_learned_sites()
            self.update_persisted_context(website)
            return resolved_url, "learned_and_opened"

        return "https://www.google.com/search?q=" + quote_plus(website), "google_search"

    def open_multiple_websites_same_window(self, website_actions):
        firefox = which("firefox") or which("firefox-esr")
        if not firefox:
            return False, "Firefox is not installed."

        urls = []
        notes = []
        for act in website_actions:
            site = act.get("target") or act.get("platform")
            phonetic = act.get("english_phonetic")
            url, res = self._resolve_website(site, english_phonetic=phonetic)
            if url:
                urls.append(url)
                notes.append(f"{site} [{res}]")

        if not urls:
            return False, "Could not resolve any of the requested websites."

        try:
            before_ids = {w["window_id"] for w in self.get_live_open_state()}
            cmd = [firefox]
            for u in urls:
                cmd.extend(["--new-tab", u])

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            self._wait_until_new_window_or_app_opens(["firefox"], before_ids, timeout=8.0)
            self.update_persisted_context("browser_window")
            return True, f"Opened {', '.join(notes)} in the same Firefox window."
        except OSError as error:
            return False, f"Could not open Firefox tabs: {error}"

    def execute_actions(self, command_data, confirm_callback=None, speak_feedback=False):
        if not isinstance(command_data, dict):
            return {"success": False, "message": "Invalid command data.", "results": []}

        allowed, sec_message = self.security.validate_actions(command_data)
        if not allowed:
            output = {
                "success": False,
                "message": sec_message,
                "results": [{"success": False, "message": sec_message}]
            }
            if speak_feedback:
                self._speak_outcome(output, command_data)
            return output

        actions = command_data.get("actions")
        if not isinstance(actions, list) or not actions:
            actions = [command_data]

        valid_actions = [a for a in actions if isinstance(a, dict)]
        if not valid_actions:
            return {"success": False, "message": "No valid actions.", "results": []}

        intents_list = [str(a.get("intent") or "").lower() for a in valid_actions]
        has_duplicate_intents = len(intents_list) != len(set(intents_list))

        has_dependency = len(valid_actions) > 1 and (
            has_duplicate_intents
            or any(
                intent in (
                    "create_structure", "move_item", "delete_item", "rename_item",
                    "open_local_file", "list_directory", "select_search_result",
                    "click", "click_element", "type_text", "type_into_element", "scroll",
                    "confirm_action", "play_video"
                )
                for intent in intents_list
            )
        )

        website_actions = [a for a in valid_actions if a.get("intent") == "open_website"]
        other_actions = [a for a in valid_actions if a.get("intent") != "open_website"]

        results = []

        if len(website_actions) >= 2:
            ok, msg = self.open_multiple_websites_same_window(website_actions)
            results.append({"success": ok, "intent": "open_website", "message": msg})
            actions_to_run = other_actions
        else:
            actions_to_run = valid_actions

        if not actions_to_run:
            success = all(r.get("success", False) for r in results)
            output = {
                "success": success,
                "message": "All actions completed." if success else "One or more actions failed.",
                "results": results
            }
            if speak_feedback:
                self._speak_outcome(output, command_data)
            return output

        delete_actions = [a for a in actions_to_run if a.get("intent") == "delete_item"]
        if len(delete_actions) >= 2:
            other_run = [a for a in actions_to_run if a.get("intent") != "delete_item"]
            for action_data in other_run:
                res = self.execute_one(action_data, confirm_callback)
                results.append(res)
                if res.get("needs_confirmation") or res.get("needs_clarification"):
                    break
            else:
                results.append(self._run_delete_batch(delete_actions, confirm_callback))
            actions_to_run = []
        elif has_dependency or len(actions_to_run) == 1:
            for action_data in actions_to_run:
                res = self.execute_one(action_data, confirm_callback)
                results.append(res)
                if res.get("needs_confirmation") or res.get("needs_clarification"):
                    break
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(actions_to_run))) as pool:
                futures = [
                    pool.submit(self.execute_one, action_data, confirm_callback)
                    for action_data in actions_to_run
                ]
                for future in futures:
                    results.append(future.result())

        for r in results:
            if r.get("needs_confirmation"):
                output = {
                    "success": False,
                    "needs_confirmation": True,
                    "needs_clarification": True,
                    "message": r.get("message", "Please confirm this action."),
                    "results": results
                }
                if speak_feedback:
                    self._speak_outcome(output, command_data)
                return output

            if r.get("needs_clarification"):
                output = {
                    "success": False,
                    "needs_clarification": True,
                    "message": r.get("message", "Please clarify your choice."),
                    "pending_candidates": [str(p) for p in self.last_search_candidates],
                    "results": results
                }
                if speak_feedback:
                    self._speak_outcome(output, command_data)
                return output

        success = all(r.get("success", False) for r in results)
        output = {
            "success": success,
            "message": "All actions completed." if success else "One or more actions failed.",
            "results": results
        }
        if speak_feedback:
            self._speak_outcome(output, command_data)
        return output

    def _speak_outcome(self, outcome, command_data):
        context = str(
            command_data.get("target")
            or command_data.get("query")
            or command_data.get("response_text")
            or ""
        )
        if outcome.get("needs_confirmation") or outcome.get("needs_clarification"):
            speak_clarification(outcome.get("message"), context=context)
        elif outcome.get("success"):
            speak_success(context=context)
        else:
            speak_error(context=context)

    def execute_one(self, data, confirm_callback=None):
        intent = str(data.get("intent", "unknown")).lower()
        target = data.get("target") or data.get("application") or ""
        query = data.get("query") or target
        action = str(data.get("action") or "").lower()
        phonetic = data.get("english_phonetic")
        symbol_variant = data.get("symbol_variant")

        handlers = {
            "open_application":
                lambda: self.open_application(
                    target,
                    english_phonetic=phonetic,
                    symbol_variant=symbol_variant
                ),

            "close_application":
                lambda: self.close_application(target, english_phonetic=phonetic),

            "open_website":
                lambda: self.open_website(
                    target or data.get("platform"),
                    english_phonetic=phonetic
                ),

            "search_web":
                lambda: self.search_web(query, data.get("platform")),

            "search_video":
                lambda: self.search_video(query),

            "play_video":
                lambda: self.play_video(
                    query,
                    data.get("platform") or "youtube",
                    data.get("selection")
                ),

            "open_local_file":
                lambda: self.open_local_file(
                    target or query,
                    parent_folder=data.get("parent_folder"),
                    english_phonetic=phonetic,
                    symbol_variant=symbol_variant
                ),

            "select_search_result":
                lambda: self.select_search_result(
                    selection=data.get("selection"),
                    parent_hint=data.get("parent_folder") or target,
                    selected_path=data.get("selected_path"),
                    action=action,
                    needs_clarification=data.get("needs_clarification", False),
                    response_text=data.get("response_text"),
                    confirm_callback=confirm_callback
                ),

            "list_directory":
                lambda: self.list_directory(
                    target,
                    english_phonetic=phonetic,
                    symbol_variant=symbol_variant
                ),

            "click":
                lambda: self.click_element(data),

            "click_element":
                lambda: self.click_element(data),

            "type_text":
                lambda: self.type_text(
                    data.get("text") or target,
                    data.get("element_name") or data.get("element")
                ),

            "type_into_element":
                lambda: self.type_text(
                    data.get("text"),
                    data.get("element_name") or data.get("element") or target
                ),

            "list_ui_elements":
                lambda: self.list_ui_elements_result(),

            "scroll":
                lambda: self.scroll(action, data.get("amount", 4)),

            "go_back":
                lambda: self.browser_key("Alt+Left"),

            "go_forward":
                lambda: self.browser_key("Alt+Right"),

            "go_home":
                lambda: self.browser_key("Alt+Home"),

            "increase_volume":
                lambda: self.change_volume("up", data.get("amount", 5)),

            "decrease_volume":
                lambda: self.change_volume("down", data.get("amount", 5)),

            "set_volume":
                lambda: self.set_volume(data.get("value", 50)),

            "mute":
                lambda: self.mute(True),

            "unmute":
                lambda: self.mute(False),

            "create_structure":
                lambda: self.create_structure(
                    data.get("folder_name"),
                    data.get("file_name"),
                    data.get("content", ""),
                    target,
                    english_phonetic=phonetic
                ),

            "delete_item":
                lambda: self.delete_item(
                    data.get("file_name") or data.get("folder_name") or target,
                    confirm_callback,
                    english_phonetic=phonetic,
                    symbol_variant=symbol_variant
                ),

            "move_item":
                lambda: self.move_item(
                    data.get("source_path") or target,
                    data.get("destination_path"),
                    english_phonetic=phonetic,
                    symbol_variant=symbol_variant
                ),

            "rename_item":
                lambda: self.rename_item(
                    data.get("source_path") or target,
                    data.get("new_name") or data.get("destination_path"),
                    english_phonetic=phonetic,
                    symbol_variant=symbol_variant
                ),

            "confirm_action":
                lambda: self.confirm_pending_action(action),

            "conversational_response":
                lambda: (True, data.get("response_text", "Okay."))
        }

        handler = handlers.get(intent)
        if not handler:
            return {"success": False, "intent": intent, "message": f"Unsupported intent: {intent}"}

        try:
            outcome = handler()
            if isinstance(outcome, tuple) and len(outcome) >= 2:
                status_flag, message = outcome[0], outcome[1]
                if status_flag == "confirmation":
                    return {
                        "success": False,
                        "needs_confirmation": True,
                        "needs_clarification": True,
                        "intent": intent,
                        "message": message
                    }
                if status_flag == "clarification":
                    return {
                        "success": False,
                        "needs_clarification": True,
                        "intent": intent,
                        "message": message
                    }
                return {"success": bool(status_flag), "intent": intent, "message": message}
            return {"success": bool(outcome), "intent": intent, "message": ""}
        except Exception as error:
            return {"success": False, "intent": intent, "message": str(error)}

    def confirm_pending_action(self, decision):
        payload = self.pending_confirmation_payload
        self.clear_pending_confirmation()

        if payload is None:
            if self.last_search_candidates and str(decision or "").lower() != "confirm":
                self.delete_batch = None
                self._sync_pending_candidates([])
                return True, "تم إلغاء الاختيار."
            return False, "لا يوجد طلب معلق بانتظار التأكيد حالياً."

        if str(decision or "").lower() != "confirm":
            self.delete_batch = None
            return True, "تم إلغاء العملية."

        kind = payload.get("kind")

        if kind == "delete":
            return self._perform_actual_delete(Path(payload["path"]))

        if kind == "delete_many":
            done, failed = [], []
            for raw in payload.get("paths", []):
                ok, msg = self._perform_actual_delete(Path(raw))
                (done if ok else failed).append(msg)
            if failed:
                return False, "\n".join(done + failed)
            return True, f"تم مسح {len(done)} عناصر."

        if kind == "click":
            return self.click_element(payload["data"], bypass_confirm=True)

        if kind == "click_xy":
            if not self.screen:
                return False, "Screen control is not available."
            from screen_control import click_xy
            ok, msg = click_xy(
                payload["x"],
                payload["y"],
                button=payload.get("button", "left"),
                double=payload.get("double", False)
            )
            if ok:
                return True, f"Clicked '{payload.get('label', 'element')}'."
            return False, msg

        return False, "Unknown pending confirmation payload."

    def list_ui_elements_result(self):
        success, message, elements = self.list_ui_elements()
        if not success:
            return False, message
        return True, json.dumps(elements, ensure_ascii=False)

    def open_application(self, name, english_phonetic=None, symbol_variant=None):
        if not name:
            return False, "Application or website name is missing."

        candidates = self._ordered_candidates(name, english_phonetic)

        launch_cmd = self._find_installed_desktop_app(candidates)

        if launch_cmd:
            bin_name = os.path.basename(launch_cmd[0])
            if bin_name == "ptyxis" and "--new-window" not in launch_cmd:
                launch_cmd.append("--new-window")

            before_ids = {w["window_id"] for w in self.get_live_open_state()}

            try:
                proc = subprocess.Popen(
                    launch_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                opened = self._wait_until_new_window_or_app_opens(
                    candidates + [bin_name],
                    before_ids,
                    timeout=8.0
                )
                if opened or proc.poll() == 0:
                    self.update_persisted_context(name)
                    return True, f"Opened {name}."
                return False, f"Launched {name}, but its window did not appear in time."
            except OSError as error:
                return False, f"Could not launch {name}: {error}"

        matched_paths = self._search_with_literal_and_symbol_logic(
            target=name,
            english_phonetic=english_phonetic,
            symbol_variant=symbol_variant,
            max_depth=5
        )
        if len(matched_paths) == 1:
            self.update_persisted_context(name)
            return self._open_path_with_xdg(matched_paths[0])
        elif len(matched_paths) > 1:
            self._sync_pending_candidates(matched_paths[:30], operation="open")
            return self._format_disambiguation_prompt(name, self.last_search_candidates, "أفتح")

        return self.open_website(name, english_phonetic=english_phonetic)

    def close_application(self, name, english_phonetic=None):
        if not name:
            return False, "Application or folder name is missing."

        candidates = self._ordered_candidates(name, english_phonetic)
        matched_windows, matched_pids = self._match_live_targets(candidates)

        if not matched_windows and not matched_pids:
            return False, f"Could not find any open window, folder, or application matching '{name}'."

        if matched_windows:
            for win in matched_windows:
                win_id = win["window_id"]
                if which("wmctrl"):
                    self.run_command(["wmctrl", "-ic", win_id])
                elif which("xdotool"):
                    self.run_command(["xdotool", "windowclose", win_id])

            time.sleep(0.8)
            still_open_wins, _ = self._match_live_targets(candidates)
            if not still_open_wins:
                return True, f"Closed {name}."

        _, remaining_pids = self._match_live_targets(candidates)
        if remaining_pids:
            for pid in remaining_pids:
                self.run_command(["kill", "-TERM", pid])
            time.sleep(0.6)

        return True, f"Closed {name}."

    def open_website(self, website, english_phonetic=None):
        if not website:
            return False, "No website or search term was specified."

        norm_site = self.normalize_name(website)
        if not norm_site.startswith(("http://", "https://")):
            local_app = self._find_installed_desktop_app(
                self._ordered_candidates(website, english_phonetic)
            )
            if local_app:
                return self.open_application(website, english_phonetic=english_phonetic)

        url, resolution = self._resolve_website(website, english_phonetic=english_phonetic)
        if not url:
            return False, "Could not resolve the requested website."

        firefox = which("firefox") or which("firefox-esr")
        if not firefox:
            return False, "Firefox is not installed."

        try:
            before_ids = {w["window_id"] for w in self.get_live_open_state()}
            subprocess.Popen(
                [firefox, "--new-tab", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            self._wait_until_new_window_or_app_opens(["firefox"], before_ids, timeout=8.0)
            self.update_persisted_context(website)
            return True, f"Opened {url} in Firefox ({resolution})."
        except OSError as error:
            return False, f"Could not launch Firefox: {error}"

    def browser_navigate(self, url):
        return self.open_website(url)

    def search_web(self, query, platform=None):
        if not query:
            return False, "Search query is missing."

        if not platform:
            local_app = self._find_installed_desktop_app([query])
            if local_app:
                return self.open_application(query)

        platform = str(platform or "").lower()
        if platform in ("youtube", "يوتيوب"):
            url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        elif platform in ("google_images", "images", "صور", "google images"):
            url = "https://www.google.com/search?tbm=isch&q=" + quote_plus(query)
        else:
            url = "https://www.google.com/search?q=" + quote_plus(query)

        self.update_persisted_context(query)
        return self.browser_navigate(url)

    def search_video(self, query):
        if not query:
            return False, "Video name is missing."

        self.last_video_query = query
        command = ["yt-dlp"] if which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]

        result = self.run_command(
            command + ["--flat-playlist", "--dump-single-json", f"ytsearch10:{query}"],
            timeout=30
        )

        self.last_video_ids = []
        self.last_video_titles = []

        if result and result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                for entry in payload.get("entries") or []:
                    video_id = entry.get("id")
                    if video_id:
                        self.last_video_ids.append(video_id)
                        self.last_video_titles.append(entry.get("title", ""))
            except (json.JSONDecodeError, AttributeError):
                pass

        url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        self.update_persisted_context(query)
        success, message = self.browser_navigate(url)
        return (True, f"Showing YouTube results for {query}.") if success else (False, message)

    def play_video(self, query=None, platform="youtube", selection=None):
        platform = str(platform).lower()
        if platform not in ("youtube", "يوتيوب", ""):
            return False, "Only YouTube playback is supported."

        video_id = None
        if selection is not None:
            try:
                index = int(selection) - 1
            except (ValueError, TypeError):
                return False, "Invalid video selection."

            if 0 <= index < len(self.last_video_ids):
                video_id = self.last_video_ids[index]
            elif self.last_video_query:
                query = self.last_video_query
            else:
                return False, "Search for videos first."

        if not video_id:
            query = query or self.last_video_query
            if not query:
                return False, "Video name is missing."

            command = ["yt-dlp"] if which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]
            result = self.run_command(
                command + ["--no-warnings", "--skip-download", "--print", "id", f"ytsearch1:{query}"],
                timeout=30
            )
            if not result or result.returncode != 0 or not result.stdout.strip():
                return False, "Could not find the requested video."
            video_id = result.stdout.strip().splitlines()[0]

        self.update_persisted_context(query)
        return self.browser_navigate("https://www.youtube.com/watch?v=" + video_id)

    def volume_backend(self):
        if which("wpctl"):
            return "wpctl"
        if which("pactl"):
            return "pactl"
        return None

    def change_volume(self, direction, amount=5):
        backend = self.volume_backend()
        if not backend:
            return False, "No supported volume controller found."

        try:
            amount = max(1, min(100, int(amount)))
        except (ValueError, TypeError):
            amount = 5

        val = f"{amount}%+" if direction == "up" else f"{amount}%-"
        pval = f"+{amount}%" if direction == "up" else f"-{amount}%"

        if backend == "wpctl":
            result = self.run_command(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", val])
        else:
            result = self.run_command(["pactl", "set-sink-volume", "@DEFAULT_SINK@", pval])

        if result and result.returncode == 0:
            return True, f"Volume {'increased' if direction == 'up' else 'decreased'} by {amount}%."
        return False, "Volume change failed."

    def set_volume(self, value):
        backend = self.volume_backend()
        if not backend:
            return False, "No supported volume controller found."

        try:
            value = max(0, min(100, int(value)))
        except (ValueError, TypeError):
            return False, "Invalid volume percentage."

        if backend == "wpctl":
            result = self.run_command(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value}%"])
        else:
            result = self.run_command(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"])

        if result and result.returncode == 0:
            return True, f"Volume set to {value}%."
        return False, "Could not set volume."

    def mute(self, enabled=True):
        backend = self.volume_backend()
        if not backend:
            return False, "No supported volume controller found."

        value = "1" if enabled else "0"
        if backend == "wpctl":
            result = self.run_command(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", value])
        else:
            result = self.run_command(["pactl", "set-sink-mute", "@DEFAULT_SINK@", value])

        if result and result.returncode == 0:
            return True, "Volume muted." if enabled else "Volume unmuted."
        return False, "Could not change mute state."

    def _resolve_folder_path(self, folder_name, english_phonetic=None):
        home = Path.home().resolve()
        candidates = self._ordered_candidates(folder_name, english_phonetic)
        if not candidates:
            return home

        for cand in candidates:
            if cand.casefold() in ("home", "هوم", "الهوم"):
                return home

            p = Path(cand).expanduser()
            if not p.is_absolute():
                p = home / p
            norm_p = Path(os.path.normpath(p))
            if norm_p.exists():
                return norm_p

            try:
                for entry in home.iterdir():
                    if entry.is_dir() and entry.name.casefold() == cand.casefold():
                        return entry.resolve()
            except OSError:
                pass

        preferred = english_phonetic or folder_name
        p = Path(str(preferred).strip()).expanduser()
        if not p.is_absolute():
            p = home / p
        return Path(os.path.normpath(p))

    def _walk_directory_for_candidates(
        self,
        root: Path,
        norm_targets: set,
        compact_targets: set,
        exact_matches: list,
        fuzzy_matches: list,
        seen_paths: set,
        max_depth: int,
        only_dirs: bool,
        only_files: bool,
        max_results: int = 50
    ):
        for current, dirs, files in os.walk(root, followlinks=False):
            if len(exact_matches) >= max_results and len(fuzzy_matches) >= max_results:
                dirs[:] = []
                break

            rel_parts = Path(current).relative_to(root).parts
            if len(rel_parts) >= max_depth:
                dirs[:] = []
            else:
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".") and d not in self.SKIP_DIRS
                ]

            items_to_check = []
            if not only_files:
                items_to_check.extend(dirs)
            if not only_dirs:
                items_to_check.extend(files)

            for item in items_to_check:
                full_path = (Path(current) / item).resolve()
                p_str = str(full_path)
                if p_str in seen_paths:
                    continue

                item_lower = item.casefold()
                item_compact = re.sub(r"[\s_\-]+", "", item_lower)
                stem_lower = Path(item).stem.casefold()

                if (
                    item_lower in norm_targets
                    or (not only_files and stem_lower in norm_targets)
                    or item_compact in compact_targets
                ):
                    exact_matches.append(full_path)
                    seen_paths.add(p_str)
                    continue

                is_similar = False
                for nt in norm_targets:
                    if len(nt) >= 3 and (nt in item_lower or item_lower in nt):
                        is_similar = True
                        break
                    ratio = difflib.SequenceMatcher(None, nt, item_lower).ratio()
                    if ratio >= 0.72:
                        is_similar = True
                        break

                if is_similar:
                    fuzzy_matches.append(full_path)
                    seen_paths.add(p_str)

    def _fast_search_candidates(
        self,
        query_names,
        search_root=None,
        max_depth=5,
        only_dirs=False,
        only_files=False,
        max_results=50
    ):
        home = Path.home().resolve()
        root = Path(search_root).resolve() if search_root else home
        clean_queries = [
            str(q).strip().rstrip("/") for q in query_names
            if q and str(q).strip()
        ]

        if not clean_queries or not root.exists():
            return [], []

        for q in clean_queries:
            if q.casefold() in ("home", "هوم", "الهوم"):
                return [home], []

        exact_matches = []
        fuzzy_matches = []
        seen_paths = set()

        norm_targets = {Path(q).name.casefold() for q in clean_queries}
        compact_targets = {re.sub(r"[\s_\-]+", "", Path(q).name.casefold()) for q in clean_queries}

        if root == home:
            priority_roots = [home / name for name in self.PRIORITY_SUBDIRS if (home / name).is_dir()]
            for p_root in priority_roots:
                self._walk_directory_for_candidates(
                    p_root, norm_targets, compact_targets,
                    exact_matches, fuzzy_matches, seen_paths,
                    max_depth=max(1, max_depth - 1),
                    only_dirs=only_dirs, only_files=only_files,
                    max_results=max_results
                )
            if not exact_matches:
                self._walk_directory_for_candidates(
                    home, norm_targets, compact_targets,
                    exact_matches, fuzzy_matches, seen_paths,
                    max_depth=min(2, max_depth),
                    only_dirs=only_dirs, only_files=only_files,
                    max_results=max_results
                )
        else:
            self._walk_directory_for_candidates(
                root, norm_targets, compact_targets,
                exact_matches, fuzzy_matches, seen_paths,
                max_depth=max_depth,
                only_dirs=only_dirs, only_files=only_files,
                max_results=max_results
            )

        exact_matches.sort(key=lambda p: (len(p.parts), str(p)))
        fuzzy_matches.sort(key=lambda p: (len(p.parts), str(p)))
        return exact_matches[:max_results], fuzzy_matches[:max_results]

    def _search_with_literal_and_symbol_logic(
        self,
        target,
        english_phonetic=None,
        symbol_variant=None,
        search_root=None,
        max_depth=5,
        only_dirs=False,
        only_files=False
    ):
        literal_matches = []
        for cand in self._ordered_candidates(target, english_phonetic):
            exact, _ = self._fast_search_candidates(
                [cand],
                search_root=search_root,
                max_depth=max_depth,
                only_dirs=only_dirs,
                only_files=only_files
            )
            if exact:
                literal_matches = exact
                break

        symbol_matches = []
        if symbol_variant and str(symbol_variant).strip():
            sym_clean = str(symbol_variant).strip()
            if sym_clean.casefold() not in {
                c.casefold() for c in self._ordered_candidates(target, english_phonetic)
            }:
                sym_exact, _ = self._fast_search_candidates(
                    [sym_clean],
                    search_root=search_root,
                    max_depth=max_depth,
                    only_dirs=only_dirs,
                    only_files=only_files
                )
                symbol_matches = sym_exact

        if literal_matches and symbol_matches:
            merged = []
            seen = set()
            for p in literal_matches + symbol_matches:
                p_str = str(p.resolve())
                if p_str not in seen:
                    seen.add(p_str)
                    merged.append(p)
            return merged

        if literal_matches:
            return literal_matches

        if symbol_matches:
            return symbol_matches

        all_queries = self._ordered_candidates(target, english_phonetic)
        if symbol_variant and str(symbol_variant).strip():
            all_queries.append(str(symbol_variant).strip())
        _, fuzzy = self._fast_search_candidates(
            all_queries,
            search_root=search_root,
            max_depth=max_depth,
            only_dirs=only_dirs,
            only_files=only_files
        )
        return fuzzy

    def _open_path_with_xdg(self, path_obj):
        opener = which("xdg-open")
        if not opener:
            return False, "xdg-open is not installed."
        try:
            before_ids = {w["window_id"] for w in self.get_live_open_state()}
            subprocess.Popen(
                [opener, str(path_obj)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            if path_obj.is_dir():
                self._wait_until_new_window_or_app_opens([path_obj.name, "nautilus", "thunar", "dolphin"], before_ids, timeout=4.0)
            self.update_persisted_context(str(path_obj))
            return True, f"Opened {path_obj}"
        except OSError as error:
            return False, str(error)

    def _format_disambiguation_prompt(self, target, candidates, action_verb="أفتح"):
        lines = []
        for i, p in enumerate(candidates, 1):
            full_path = str(p.resolve())
            kind = "Folder" if p.is_dir() else "File"
            lines.append(f"{i}. {full_path}  [{kind}]")

        msg = (
            f"لقيت {len(candidates)} مسارات لـ '{target}'، تحبي {action_verb} أنهي واحد؟\n"
            + "\n".join(lines)
            + "\n(تقدري تختاري بالرقم، باسم الفولدر، بنوع الملف، أو الكابيتال/سمول)"
        )
        return "clarification", msg

    def open_local_file(self, target, parent_folder=None, english_phonetic=None, symbol_variant=None):
        if not target:
            return False, "File or folder name is missing."

        self._sync_pending_candidates([])

        if parent_folder:
            parent_matches = self._search_with_literal_and_symbol_logic(
                target=parent_folder,
                max_depth=3,
                only_dirs=True
            )
            if len(parent_matches) == 1 and parent_matches[0].is_dir():
                parent_path = parent_matches[0]
                matches = self._search_with_literal_and_symbol_logic(
                    target=target,
                    english_phonetic=english_phonetic,
                    symbol_variant=symbol_variant,
                    search_root=parent_path,
                    max_depth=2
                )
                if len(matches) == 1:
                    self.update_persisted_context(str(matches[0]))
                    return self._open_path_with_xdg(matches[0])
                elif len(matches) > 1:
                    self._sync_pending_candidates(matches[:30], operation="open")
                    return self._format_disambiguation_prompt(target, self.last_search_candidates, "أفتح")
                else:
                    return False, f"الملف أو الفولدر '{target}' غير موجود داخل '{parent_path}'."

        matches = self._search_with_literal_and_symbol_logic(
            target=target,
            english_phonetic=english_phonetic,
            symbol_variant=symbol_variant,
            max_depth=5
        )

        if not matches:
            return False, f"الملف أو الفولدر '{target}' غير موجود على الجهاز."

        if len(matches) == 1:
            self.update_persisted_context(str(matches[0]))
            return self._open_path_with_xdg(matches[0])

        self._sync_pending_candidates(matches[:30], operation="open")
        return self._format_disambiguation_prompt(target, self.last_search_candidates, "أفتح")

    def list_directory(self, target, english_phonetic=None, symbol_variant=None):
        if not target:
            return False, "Folder path is missing."

        self._sync_pending_candidates([])

        matches = self._search_with_literal_and_symbol_logic(
            target=target,
            english_phonetic=english_phonetic,
            symbol_variant=symbol_variant,
            max_depth=5,
            only_dirs=True
        )

        if not matches:
            return False, f"الفولدر '{target}' غير موجود على الجهاز."

        if len(matches) > 1:
            self._sync_pending_candidates(matches[:30], operation="list")
            return self._format_disambiguation_prompt(target, self.last_search_candidates, "أعرض محتويات")

        self.update_persisted_context(str(matches[0]))
        return self._execute_list_on_path(matches[0])

    def _execute_list_on_path(self, folder: Path):
        home = Path.home().resolve()
        try:
            folder = folder.resolve(strict=True)
            if home != folder and home not in folder.parents:
                return False, "Access outside your Home folder is not allowed."

            if not folder.is_dir():
                return False, "The requested path is not a folder."

            items = sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))

            self._append_and_open_auto_save(folder, items)

            if not items:
                return True, f"الفولدر '{folder}' فاضي (تم تسجيله في auto_save.txt)."

            lines = [
                f"{'[Folder]' if item.is_dir() else '[File]'} {item.name}"
                for item in items
            ]
            return True, f"تم حفظ وعرض محتويات {folder} في auto_save.txt:\n" + "\n".join(lines)

        except FileNotFoundError:
            return False, "Folder not found."
        except OSError as error:
            return False, str(error)

    def delete_item(self, target, confirm_callback=None, english_phonetic=None, symbol_variant=None):
        if not target:
            return False, "Target is missing."

        self.delete_batch = None
        self._sync_pending_candidates([])

        matches = self._search_with_literal_and_symbol_logic(
            target=target,
            english_phonetic=english_phonetic,
            symbol_variant=symbol_variant,
            max_depth=5
        )

        if not matches:
            return False, f"الملف أو الفولدر '{target}' غير موجود على الجهاز."

        if len(matches) > 1:
            self._sync_pending_candidates(
                matches[:30],
                operation="delete",
                extra={"confirm_callback": confirm_callback}
            )
            return self._format_disambiguation_prompt(target, self.last_search_candidates, "أمسح")

        return self._execute_delete_on_path(matches[0], confirm_callback)

    def _run_delete_batch(self, delete_actions, confirm_callback=None):
        self.delete_batch = {"paths": [], "notes": [], "queue": list(delete_actions)}
        try:
            status, message = self._advance_delete_batch(confirm_callback)
        except Exception:
            self.delete_batch = None
            raise

        if status == "confirmation":
            return {"success": False, "needs_confirmation": True, "needs_clarification": True,
                    "intent": "delete_item", "message": message}
        if status == "clarification":
            return {"success": False, "needs_clarification": True,
                    "intent": "delete_item", "message": message}
        self.delete_batch = None
        return {"success": bool(status), "intent": "delete_item", "message": message}

    def _advance_delete_batch(self, confirm_callback=None):
        batch = self.delete_batch
        while batch and batch["queue"]:
            data = batch["queue"].pop(0)
            target = data.get("file_name") or data.get("folder_name") or data.get("target")
            matches = self._search_with_literal_and_symbol_logic(
                target=target,
                english_phonetic=data.get("english_phonetic"),
                symbol_variant=data.get("symbol_variant"),
                max_depth=5
            )
            if not matches:
                batch["notes"].append(f"'{target}' غير موجود على الجهاز.")
                continue
            if len(matches) > 1:
                self._sync_pending_candidates(
                    matches[:30], operation="delete",
                    extra={"confirm_callback": confirm_callback}
                )
                return self._format_disambiguation_prompt(target, self.last_search_candidates, "أمسح")
            self._batch_add_path(matches[0])
        return self._finish_delete_batch()

    def _batch_add_path(self, path):
        batch = self.delete_batch
        allowed, resolved_path, sec_msg = self.security.validate_delete_target(path)
        if not allowed:
            batch["notes"].append(f"{Path(str(path)).name}: {sec_msg}")
            return
        home = Path.home().resolve()
        protected = {home} | {
            home / name for name in (
                "Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"
            )
        }
        parent = resolved_path.parent.resolve()
        if (parent != home and home not in parent.parents) or resolved_path in protected:
            batch["notes"].append(f"{resolved_path.name}: This item cannot be deleted.")
            return
        if resolved_path not in batch["paths"]:
            batch["paths"].append(resolved_path)

    def _finish_delete_batch(self):
        batch, self.delete_batch = self.delete_batch, None
        paths = list(batch["paths"])
        paths = [p for p in paths if not any(o != p and o in p.parents for o in paths)]
        notes = "\n".join(batch["notes"])
        if not paths:
            return False, notes or "مفيش حاجة تتمسح."
        listing = "\n".join(f"{i}. {p}" for i, p in enumerate(paths, 1))
        question = f"متأكدة إنك عايزة تمسحي {len(paths)} عناصر:\n{listing}\n"
        if notes:
            question += f"(اتخطيت:\n{notes})\n"
        question += "(قولي موافقة / تمام للتأكيد، أو إلغاء للتراجع)"
        return self._request_voice_confirmation(
            question, {"kind": "delete_many", "paths": [str(p) for p in paths]}
        )

    def _execute_delete_on_path(self, path: Path, confirm_callback=None):
        allowed, resolved_path, sec_msg = self.security.validate_delete_target(path)
        if not allowed:
            return False, sec_msg

        home = Path.home().resolve()
        parent = resolved_path.parent.resolve()

        protected = {home} | {
            home / name for name in (
                "Desktop", "Documents", "Downloads",
                "Pictures", "Music", "Videos"
            )
        }

        if (parent != home and home not in parent.parents) or resolved_path in protected:
            return False, "This item cannot be deleted."

        return self._request_voice_confirmation(
            f"متأكدة إنك عايزة تمسحي:\n{resolved_path}\n(قولي موافقة / تمام للتأكيد، أو إلغاء للتراجع)",
            {"kind": "delete", "path": str(resolved_path)}
        )

    def _perform_actual_delete(self, path: Path):
        allowed, resolved_path, sec_msg = self.security.validate_delete_target(path)
        if not allowed:
            return False, sec_msg

        try:
            if which("gio"):
                result = self.run_command(["gio", "trash", str(resolved_path)])
                if result and result.returncode == 0:
                    return True, f"Moved {resolved_path} to Trash."

            if resolved_path.is_symlink() or resolved_path.is_file():
                resolved_path.unlink()
            else:
                shutil.rmtree(resolved_path)

            return True, f"Deleted {resolved_path}."

        except OSError as error:
            return False, str(error)

    def move_item(self, source_path, destination_path, english_phonetic=None, symbol_variant=None):
        if not source_path or not destination_path:
            return False, "Source or destination path is missing."

        self._sync_pending_candidates([])

        src_matches = self._search_with_literal_and_symbol_logic(
            target=source_path,
            english_phonetic=english_phonetic,
            symbol_variant=symbol_variant,
            max_depth=5
        )

        if not src_matches:
            return False, f"العنصر '{source_path}' غير موجود على الجهاز."

        if len(src_matches) > 1:
            self._sync_pending_candidates(
                src_matches[:30],
                operation="move",
                extra={"destination_path": destination_path}
            )
            return self._format_disambiguation_prompt(source_path, self.last_search_candidates, "أنقل")

        return self._execute_move_on_path(src_matches[0], destination_path)

    def _execute_move_on_path(self, source_resolved: Path, destination_path: str):
        home = Path.home().resolve()

        dst_matches = self._search_with_literal_and_symbol_logic(
            target=destination_path,
            max_depth=4,
            only_dirs=True
        )
        if not dst_matches:
            return False, f"الفولدر الوجهة '{destination_path}' غير موجود على الجهاز."

        destination_resolved = dst_matches[0].resolve()

        try:
            source_resolved.relative_to(home)
            destination_resolved.relative_to(home)

            if not destination_resolved.is_dir():
                return False, "Destination must be an existing folder."

            if source_resolved == destination_resolved:
                return False, "Source and destination are the same."

            if source_resolved.is_dir():
                try:
                    destination_resolved.relative_to(source_resolved)
                    return False, "Cannot move a folder into itself."
                except ValueError:
                    pass

            new_path = destination_resolved / source_resolved.name
            if new_path.exists() or new_path.is_symlink():
                return False, "An item with the same name already exists."

            shutil.move(str(source_resolved), str(new_path))
            self.update_persisted_context(str(new_path))
            return True, f"Moved {source_resolved} to {new_path}."

        except FileNotFoundError:
            return False, "Source or destination was not found."
        except ValueError:
            return False, "Moving items outside your Home folder is not allowed."
        except OSError as error:
            return False, str(error)

    def rename_item(self, source_path, new_name, english_phonetic=None, symbol_variant=None):
        if not source_path or not new_name:
            return False, "Current name or new name is missing."

        self._sync_pending_candidates([])

        matches = self._search_with_literal_and_symbol_logic(
            target=source_path,
            english_phonetic=english_phonetic,
            symbol_variant=symbol_variant,
            max_depth=5
        )

        if not matches:
            return False, f"العنصر '{source_path}' غير موجود على الجهاز."

        if len(matches) > 1:
            self._sync_pending_candidates(
                matches[:30],
                operation="rename",
                extra={"new_name": new_name}
            )
            return self._format_disambiguation_prompt(source_path, self.last_search_candidates, "أغير اسم")

        return self._execute_rename_on_path(matches[0], new_name)

    def _execute_rename_on_path(self, source_resolved: Path, new_name: str):
        home = Path.home().resolve()
        clean_new_name = Path(str(new_name).strip()).name
        if not clean_new_name:
            return False, "Invalid new name."

        try:
            source_resolved.relative_to(home)
            target_path = source_resolved.parent / clean_new_name
            if target_path.exists():
                return False, f"يوجد بالفعل عنصر باسم '{clean_new_name}' في نفس المسار."

            source_resolved.rename(target_path)
            self.update_persisted_context(str(target_path))
            return True, f"Renamed '{source_resolved}' to '{target_path}'."
        except ValueError:
            return False, "Renaming items outside your Home folder is not allowed."
        except OSError as error:
            return False, str(error)

    def create_structure(
        self,
        folder_name=None,
        file_name=None,
        content="",
        target=None,
        english_phonetic=None
    ):
        home = Path.home().resolve()

        try:
            base_folder = self._resolve_folder_path(target, english_phonetic=english_phonetic).resolve()

            if home not in (base_folder, *base_folder.parents):
                return False, "Target folder must be inside home directory."

            folder = (base_folder / folder_name if folder_name else base_folder).resolve()

            if base_folder not in (folder, *folder.parents):
                return False, "Invalid folder path."

            folder.mkdir(parents=True, exist_ok=True)

            if file_name:
                file_path = (folder / file_name).resolve()
                if folder not in file_path.parents:
                    return False, "Invalid file path."
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(str(content or ""), encoding="utf-8")
                self.update_persisted_context(str(file_path))
                return True, f"Created file: {file_path}"

            self.update_persisted_context(str(folder))
            return True, f"Created folder: {folder}"

        except OSError as error:
            return False, str(error)

    def _run_pending_operation_on_chosen(self, chosen_path: Path, confirm_callback=None):
        op = self.pending_operation or "open"
        extra = dict(self.pending_extra)
        self._sync_pending_candidates([])

        if op == "list":
            return self._execute_list_on_path(chosen_path)
        elif op == "delete":
            cb = extra.get("confirm_callback") or confirm_callback
            if self.delete_batch is not None:
                self._batch_add_path(chosen_path)
                return self._advance_delete_batch(cb)
            return self._execute_delete_on_path(chosen_path, cb)
        elif op == "move":
            return self._execute_move_on_path(chosen_path, extra.get("destination_path", ""))
        elif op == "rename":
            return self._execute_rename_on_path(chosen_path, extra.get("new_name", ""))
        else:
            return self._open_path_with_xdg(chosen_path)

    def select_search_result(
        self,
        selection=None,
        parent_hint=None,
        selected_path=None,
        action=None,
        needs_clarification=False,
        response_text=None,
        confirm_callback=None
    ):
        if not self.last_search_candidates:
            return False, "There is no active file search list to choose from."

        if str(action or "").lower() == "cancel":
            self.delete_batch = None
            self._sync_pending_candidates([])
            return True, "تم إلغاء اختيار الملف."

        if needs_clarification:
            return "clarification", response_text or (
                f"مش واضح تقصدي أنهي واحد من الـ {len(self.last_search_candidates)} مسارات، وضحي أكتر."
            )

        if selected_path:
            target_str = str(selected_path).strip()
            for cand in self.last_search_candidates:
                if str(cand) == target_str or str(cand.resolve()) == target_str:
                    return self._run_pending_operation_on_chosen(cand, confirm_callback)

        if parent_hint:
            hint_resolved = self._resolve_folder_path(parent_hint)
            hint_cf = str(parent_hint).strip().casefold()
            parent_matches = [
                cand for cand in self.last_search_candidates
                if (
                    cand.parent == hint_resolved
                    or hint_cf in cand.parent.name.casefold()
                    or hint_cf in str(cand.parent).casefold()
                )
            ]
            if len(parent_matches) == 1:
                return self._run_pending_operation_on_chosen(parent_matches[0], confirm_callback)
            elif len(parent_matches) > 1:
                op = self.pending_operation
                extra = self.pending_extra
                self._sync_pending_candidates(parent_matches, operation=op, extra=extra)
                return self._format_disambiguation_prompt(parent_matches[0].name, parent_matches)

        if selection is not None:
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(self.last_search_candidates):
                    chosen = self.last_search_candidates[idx]
                    return self._run_pending_operation_on_chosen(chosen, confirm_callback)
            except (TypeError, ValueError):
                pass

        return "clarification", (
            f"اختاري رقم من 1 لـ {len(self.last_search_candidates)} "
            "أو اوصفي المسار/الاسم اللي عايزاه."
        )

    def scroll(self, direction, amount=4):
        try:
            amount = max(1, min(30, int(amount)))
        except (ValueError, TypeError):
            amount = 4

        direction = str(direction or "down").lower()
        is_up = direction in ("up", "upward", "أعلى", "فوق", "لفوق")

        if which("xdotool") and _get_session_type() != "wayland":
            button = "4" if is_up else "5"
            result = self.run_command([
                "xdotool", "click", "--repeat", str(amount), "--delay", "50", button
            ])
            if result and result.returncode == 0:
                self.update_persisted_context()
                return True, "Scrolled up." if is_up else "Scrolled down."

        if which("ydotool"):
            wheel_val = str(amount * 3) if is_up else str(-amount * 3)
            result = self.run_command(["ydotool", "mousewheel", "--", "0", wheel_val])
            if result and result.returncode == 0:
                self.update_persisted_context()
                return True, "Scrolled up." if is_up else "Scrolled down."

        try:
            from pynput.mouse import Controller
            mouse = Controller()
            step = amount if is_up else -amount
            mouse.scroll(0, step)
            self.update_persisted_context()
            return True, "Scrolled up." if is_up else "Scrolled down."
        except Exception:
            pass

        if which("xdotool"):
            button = "4" if is_up else "5"
            result = self.run_command([
                "xdotool", "click", "--repeat", str(amount), "--delay", "50", button
            ])
            if result and result.returncode == 0:
                self.update_persisted_context()
                return True, "Scrolled up." if is_up else "Scrolled down."

        return False, "Scroll failed. Please ensure xdotool or ydotool is installed."

    def browser_key(self, key):
        if not which("xdotool"):
            return False, "xdotool is not installed."

        result = self.run_command(["xdotool", "key", "--clearmodifiers", key])
        if result and result.returncode == 0:
            self.update_persisted_context()
            return True, "Navigation command sent."
        return False, "Navigation failed."
