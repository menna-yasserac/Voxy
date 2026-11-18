import os
import re
import json
import time
import shutil
import difflib
import subprocess
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path
from urllib.parse import quote_plus, unquote

try:
    from atspi_controller import ATSPIController
    ATSPI_AVAILABLE = True
except (ImportError, OSError):
    ATSPIController = None
    ATSPI_AVAILABLE = False


def which(name):
    return shutil.which(name)


class LinuxExecutor:

    # Launch binary candidates (includes common Arabic transliterations)
    APP_ALIASES = {
        "firefox": ["firefox", "firefox-esr"],
        "فايرفوكس": ["firefox", "firefox-esr"],
        "الفايرفوكس": ["firefox", "firefox-esr"],
        "chrome": [
            "google-chrome", "google-chrome-stable",
            "chromium", "chromium-browser"
        ],
        "كروم": [
            "google-chrome", "google-chrome-stable",
            "chromium", "chromium-browser"
        ],
        "جوجل كروم": [
            "google-chrome", "google-chrome-stable",
            "chromium", "chromium-browser"
        ],
        "terminal": [
            "gnome-terminal", "ptyxis", "x-terminal-emulator", "xfce4-terminal"
        ],
        "ترمينال": ["gnome-terminal", "ptyxis", "x-terminal-emulator", "xfce4-terminal"],
        "تيرمينال": ["gnome-terminal", "ptyxis", "x-terminal-emulator", "xfce4-terminal"],
        "التيرمينال": ["gnome-terminal", "ptyxis", "x-terminal-emulator", "xfce4-terminal"],
        "الترمينال": ["gnome-terminal", "ptyxis", "x-terminal-emulator", "xfce4-terminal"],
        "files": ["nautilus", "thunar", "dolphin"],
        "file manager": ["nautilus", "thunar", "dolphin"],
        "الملفات": ["nautilus", "thunar", "dolphin"],
        "فايلز": ["nautilus", "thunar", "dolphin"],
        "calculator": ["gnome-calculator", "kcalc"],
        "الحاسبة": ["gnome-calculator", "kcalc"],
        "كالكوليتور": ["gnome-calculator", "kcalc"],
        "الكالكوليتور": ["gnome-calculator", "kcalc"],
        "كلكوليتور": ["gnome-calculator", "kcalc"],
        "settings": ["gnome-control-center"],
        "الإعدادات": ["gnome-control-center"],
        "سيتينجز": ["gnome-control-center"],
        "text editor": ["gnome-text-editor", "gedit", "mousepad"],
        "المفكرة": ["gnome-text-editor", "gedit", "mousepad"],
        "vs code": ["code"],
        "vscode": ["code"],
        "كود": ["code"],
    }

    # Actual Linux process patterns (handles Snap, Flatpak, -bin, server daemons)
    PROCESS_PATTERNS = {
        "firefox": ["firefox", "firefox-bin", "firefox-esr"],
        "فايرفوكس": ["firefox", "firefox-bin", "firefox-esr"],
        "الفايرفوكس": ["firefox", "firefox-bin", "firefox-esr"],
        "chrome": ["chrome", "google-chrome", "chromium"],
        "كروم": ["chrome", "google-chrome", "chromium"],
        "جوجل كروم": ["chrome", "google-chrome", "chromium"],
        "files": ["nautilus", "thunar", "dolphin"],
        "file manager": ["nautilus", "thunar", "dolphin"],
        "الملفات": ["nautilus", "thunar", "dolphin"],
        "فايلز": ["nautilus", "thunar", "dolphin"],
        "calculator": ["gnome-calculator", "kcalc"],
        "الحاسبة": ["gnome-calculator", "kcalc"],
        "كالكوليتور": ["gnome-calculator", "kcalc"],
        "الكالكوليتور": ["gnome-calculator", "kcalc"],
        "settings": ["gnome-control-center"],
        "الإعدادات": ["gnome-control-center"],
        "text editor": ["gnome-text-editor", "gedit", "mousepad"],
        "المفكرة": ["gnome-text-editor", "gedit", "mousepad"],
        "terminal": ["gnome-terminal-server", "gnome-terminal", "ptyxis", "xfce4-terminal"],
        "ترمينال": ["gnome-terminal-server", "gnome-terminal", "ptyxis", "xfce4-terminal"],
        "تيرمينال": ["gnome-terminal-server", "gnome-terminal", "ptyxis", "xfce4-terminal"],
        "التيرمينال": ["gnome-terminal-server", "gnome-terminal", "ptyxis", "xfce4-terminal"],
        "vs code": ["code"],
        "vscode": ["code"],
        "كود": ["code"],
    }

    FOLDER_ALIASES = {
        "داول لوت": "Downloads",
        "داونلودز": "Downloads",
        "داون لود": "Downloads",
        "downloads": "Downloads",
        "ديسكتوب": "Desktop",
        "desktop": "Desktop",
        "دوكيومنتس": "Documents",
        "documents": "Documents",
        "هوم": "",
        "الهوم": "",
        "home": "",
        "صور": "Pictures",
        "pictures": "Pictures",
        "فيديوهات": "Videos",
        "videos": "Videos",
    }

    SKIP_DIRS = {
        "proc", "sys", "dev", "run", "snap",
        "node_modules", "__pycache__", ".cache",
        "Trash", ".Trash-1000", ".git", ".venv", "venv"
    }

    def __init__(self):
        self.last_video_query = None
        self.last_video_ids = []
        self.last_video_titles = []
        self.last_search_candidates = []

        # Adaptive Self-Learning Cache for websites
        self.memory_file = Path.home() / ".local" / "share" / "voxy" / "learned_sites.json"
        self.learned_sites = self._load_learned_sites()

        self.atspi = None

        if ATSPI_AVAILABLE:
            try:
                self.atspi = ATSPIController()
                print("[AT-SPI] Controller initialized.")
            except Exception as error:
                print(f"[AT-SPI] Initialization failed: {error}")

    # =========================================
    # GENERAL HELPERS
    # =========================================

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

    def get_app_candidates(self, name):
        name = self.normalize_name(name)
        if name in self.APP_ALIASES:
            return self.APP_ALIASES[name]
        return [name.replace(" ", "-")] if name else []

    def get_process_patterns(self, name):
        norm = self.normalize_name(name)
        if norm in self.PROCESS_PATTERNS:
            return self.PROCESS_PATTERNS[norm]
        return list(set(self.get_app_candidates(norm) + [norm]))

    def _find_installed_desktop_app(self, query_names):
        """
        Searches Ubuntu's installed applications (.desktop entries & PATH)
        before falling back to web search.
        Returns executable command list or None.
        """
        clean_queries = [
            self.normalize_name(q) for q in query_names
            if q and str(q).strip()
        ]
        if not clean_queries:
            return None

        # 1. Check aliases & direct PATH binaries first
        for q in clean_queries:
            for candidate in self.get_app_candidates(q):
                exe = which(candidate)
                if exe:
                    return [exe]

        # 2. Scan Ubuntu .desktop application directories
        desktop_dirs = [
            Path("/usr/share/applications"),
            Path("/usr/local/share/applications"),
            Path("/var/lib/snapd/desktop/applications"),
            Path.home() / ".local/share/applications",
        ]

        for d in desktop_dirs:
            if not d.exists():
                continue
            for desktop_file in d.glob("*.desktop"):
                stem = desktop_file.stem.lower()
                app_name = ""
                exec_cmd = ""
                try:
                    for line in desktop_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.startswith("Name=") and not app_name:
                            app_name = line.split("=", 1)[1].strip().lower()
                        elif line.startswith("Exec=") and not exec_cmd:
                            raw_exec = line.split("=", 1)[1].strip()
                            exec_cmd = re.sub(r"\s+%[a-zA-Z]", "", raw_exec).strip()
                except OSError:
                    continue

                if not exec_cmd:
                    continue

                for q in clean_queries:
                    if (
                        q == app_name
                        or q == stem
                        or (len(q) >= 3 and (q in app_name or q in stem))
                    ):
                        parts = exec_cmd.split()
                        if parts and which(parts[0]):
                            return parts

        return None

    # =========================================
    # AT-SPI HELPERS
    # =========================================

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

    def click_element(self, data):
        if not isinstance(data, dict):
            return False, "Invalid click data."

        element_name = (
            data.get("element_name")
            or data.get("element")
            or data.get("target")
            or data.get("selection")
        )

        if element_name and self.atspi:
            try:
                result = self.atspi.click(str(element_name))
                success, message = self._normalize_atspi_result(result, "click")
                if success:
                    return True, message
                print(f"[AT-SPI] Click failed: {message}")
            except Exception as error:
                print(f"[AT-SPI] Click error: {error}")

        x = data.get("x")
        y = data.get("y")

        if x is not None and y is not None:
            if not which("xdotool"):
                return False, "xdotool is not installed."

            result = self.run_command([
                "xdotool", "mousemove", str(int(x)), str(int(y)), "click", "1"
            ])
            if result and result.returncode == 0:
                return True, "Clicked coordinates."
            return False, "Coordinate click failed."

        if not self.atspi:
            return False, "AT-SPI is unavailable and no coordinates were provided."

        return False, (
            f"Could not click '{element_name}'. "
            "The element may not be accessible or may not support clicking."
        )

    def type_text(self, text, element_name=None):
        if text is None:
            return False, "No text provided."

        if element_name:
            if not self.atspi:
                return False, "AT-SPI is not available."
            try:
                result = self.atspi.type_text(str(element_name), str(text))
                return self._normalize_atspi_result(result, "typing")
            except Exception as error:
                return False, f"AT-SPI typing failed: {error}"

        if not which("xdotool"):
            return False, "xdotool is not installed."

        result = self.run_command([
            "xdotool", "type", "--clearmodifiers", "--delay", "2", str(text)
        ], timeout=20)

        if result and result.returncode == 0:
            return True, "Text typed into the focused element."
        return False, "Typing failed."

    # =========================================
    # PROCESS AND WINDOW DISCOVERY & WAIT
    # =========================================

    def _get_process_pids(self, process_name):
        process_name = os.path.basename(str(process_name)).strip()
        if not process_name:
            return []

        pids = set()
        res_exact = self.run_command(["pgrep", "-ix", process_name])
        if res_exact and res_exact.returncode == 0:
            for line in res_exact.stdout.splitlines():
                if line.strip().isdigit():
                    pids.add(line.strip())

        my_pid = str(os.getpid())
        res_full = self.run_command(["pgrep", "-if", process_name])
        if res_full and res_full.returncode == 0:
            for line in res_full.stdout.splitlines():
                pid = line.strip()
                if pid.isdigit() and pid != my_pid:
                    pids.add(pid)

        return list(pids)

    def _get_process_windows(self, pids):
        if not pids:
            return []

        windows = []

        if which("wmctrl"):
            result = self.run_command(["wmctrl", "-lp"])
            if result and result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split(None, 4)
                    if len(parts) < 4:
                        continue
                    window_id, pid = parts[0], parts[2]
                    title = parts[4] if len(parts) > 4 else ""
                    if pid in pids:
                        windows.append({"id": window_id, "pid": pid, "title": title})

        if which("xdotool"):
            for pid in pids:
                result = self.run_command([
                    "xdotool", "search", "--onlyvisible", "--pid", pid
                ])
                if result and result.returncode == 0:
                    for window_id in result.stdout.splitlines():
                        window_id = window_id.strip()
                        if window_id and not any(w["id"] == window_id for w in windows):
                            windows.append({"id": window_id, "pid": pid, "title": ""})

        return windows

    def _find_windows_by_title(self, query_names):
        """Finds open window IDs whose title matches any candidate name (case-insensitive)."""
        clean_queries = [
            str(q).strip().casefold() for q in query_names
            if q and str(q).strip()
        ]
        if not clean_queries:
            return []

        matched_ids = []
        if which("wmctrl"):
            res = self.run_command(["wmctrl", "-l"])
            if res and res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.split(None, 3)
                    if len(parts) < 4:
                        continue
                    win_id, title = parts[0], parts[3].strip()
                    title_cf = title.casefold()
                    for q in clean_queries:
                        if (
                            title_cf == q
                            or title_cf.startswith(q + " ")
                            or title_cf.endswith(" " + q)
                            or f"/{q}" in title_cf
                        ):
                            if win_id not in matched_ids:
                                matched_ids.append(win_id)
        return matched_ids

    def _wait_until_actually_open(self, process_patterns, timeout=8.0):
        """
        Waits until the application process AND its visible window actually appear
        on screen before returning the success message.
        """
        start = time.time()
        process_seen = False

        while time.time() - start < timeout:
            all_pids = []
            for pat in process_patterns:
                all_pids.extend(self._get_process_pids(pat))

            if all_pids:
                process_seen = True
                windows = self._get_process_windows(all_pids)
                if windows:
                    return True
                if os.environ.get("XDG_SESSION_TYPE") == "wayland" and (time.time() - start) >= 0.7:
                    return True

            time.sleep(0.25)

        return process_seen

    # =========================================
    # ADAPTIVE SELF-LEARNING WEBSITE RESOLUTION
    # =========================================

    def _load_learned_sites(self):
        try:
            if self.memory_file.exists():
                return json.loads(self.memory_file.read_text(encoding="utf-8"))
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
        """Fetches the first real website URL for a query so Voxy can learn it for next time."""
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
        key = self.normalize_name(website)
        if not key:
            return None, "Website name is missing."

        # 1. Explicit full URL
        if key.startswith(("https://", "http://")):
            self.learned_sites[key] = {"url": key, "count": 1}
            self._save_learned_sites()
            return key, "explicit_url"

        # 2. Check if Voxy already learned this site from previous usage
        entry = self.learned_sites.get(key)
        if entry and entry.get("url"):
            entry["count"] = entry.get("count", 1) + 1
            self._save_learned_sites()
            return entry["url"], f"learned (used {entry['count']} times)"

        # 3. First time seeing this site: resolve direct domain or top search URL,
        # save it in memory, and open Firefox search on this first run!
        candidate_slug = self.normalize_name(english_phonetic or key)
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
            self.learned_sites[key] = {"url": resolved_url, "count": 1}
            self._save_learned_sites()
            search_url = "https://www.google.com/search?q=" + quote_plus(website)
            return search_url, "first_time_search (saved direct link for next time)"

        return "https://www.google.com/search?q=" + quote_plus(website), "google_search"

    def open_multiple_websites_same_window(self, website_actions):
        """Opens multiple websites together as tabs inside a single Firefox window."""
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
            cmd = [firefox]
            for u in urls:
                cmd.extend(["--new-tab", u])

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            self._wait_until_actually_open(["firefox", "firefox-bin"], timeout=8.0)
            return True, f"Opened {', '.join(notes)} in the same Firefox window."
        except OSError as error:
            return False, f"Could not open Firefox tabs: {error}"

    # =========================================
    # MAIN EXECUTION (PARALLEL + SMART BATCHING)
    # =========================================

    def execute_actions(self, command_data, confirm_callback=None):
        if not isinstance(command_data, dict):
            return {"success": False, "message": "Invalid command data.", "results": []}

        actions = command_data.get("actions")
        if not isinstance(actions, list) or not actions:
            actions = [command_data]

        valid_actions = [a for a in actions if isinstance(a, dict)]
        if not valid_actions:
            return {"success": False, "message": "No valid actions.", "results": []}

        has_dependency = len(valid_actions) > 1 and any(
            a.get("intent") in (
                "create_structure", "move_item", "delete_item",
                "click", "click_element", "type_text", "scroll"
            )
            for a in valid_actions
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
            return {
                "success": success,
                "message": "All actions completed." if success else "One or more actions failed.",
                "results": results
            }

        if has_dependency or len(actions_to_run) == 1:
            for action_data in actions_to_run:
                results.append(self.execute_one(action_data, confirm_callback))
        else:
            with ThreadPoolExecutor(max_workers=min(6, len(actions_to_run))) as pool:
                futures = [
                    pool.submit(self.execute_one, action_data, confirm_callback)
                    for action_data in actions_to_run
                ]
                for future in futures:
                    results.append(future.result())

        # Surface interactive clarification prompts cleanly if any action needs user input
        for r in results:
            if r.get("needs_clarification"):
                return {
                    "success": False,
                    "needs_clarification": True,
                    "message": r.get("message", "Please clarify your choice."),
                    "results": results
                }

        success = all(r.get("success", False) for r in results)
        return {
            "success": success,
            "message": "All actions completed." if success else "One or more actions failed.",
            "results": results
        }

    def execute_one(self, data, confirm_callback=None):
        intent = str(data.get("intent", "unknown")).lower()
        target = data.get("target") or data.get("application") or ""
        query = data.get("query") or target
        action = str(data.get("action") or "").lower()
        phonetic = data.get("english_phonetic")

        handlers = {
            "open_application":
                lambda: self.open_application(target, english_phonetic=phonetic),

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
                    english_phonetic=phonetic
                ),

            "select_search_result":
                lambda: self.select_search_result(
                    selection=data.get("selection"),
                    parent_hint=data.get("parent_folder") or target
                ),

            "list_directory":
                lambda: self.list_directory(target),

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
                lambda: self.scroll(action, data.get("amount", 3)),

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
                    target
                ),

            "delete_item":
                lambda: self.delete_item(
                    data.get("file_name") or data.get("folder_name") or target,
                    confirm_callback
                ),

            "move_item":
                lambda: self.move_item(
                    data.get("source_path"),
                    data.get("destination_path")
                ),

            "conversational_response":
                lambda: (True, data.get("response_text", "Okay."))
        }

        handler = handlers.get(intent)
        if not handler:
            return {"success": False, "intent": intent, "message": f"Unsupported intent: {intent}"}

        try:
            success, message = handler()
            if success == "clarification":
                return {
                    "success": False,
                    "needs_clarification": True,
                    "intent": intent,
                    "message": message
                }
            return {"success": bool(success), "intent": intent, "message": message}
        except Exception as error:
            return {"success": False, "intent": intent, "message": str(error)}

    def list_ui_elements_result(self):
        success, message, elements = self.list_ui_elements()
        if not success:
            return False, message
        return True, json.dumps(elements, ensure_ascii=False)

    # =========================================
    # OPEN & CLOSE APPLICATION / FOLDER (ACCURATE WINDOW + PROCESS CHECK)
    # =========================================

    def open_application(self, name, english_phonetic=None):
        if not name:
            return False, "Application or website name is missing."

        # 1. Check if the target is an installed app on Ubuntu FIRST
        launch_cmd = self._find_installed_desktop_app([name, english_phonetic])

        if launch_cmd:
            bin_name = os.path.basename(launch_cmd[0])
            if bin_name == "ptyxis" and "--new-window" not in launch_cmd:
                launch_cmd.append("--new-window")

            patterns = list(set(
                self.get_process_patterns(name)
                + (self.get_process_patterns(english_phonetic) if english_phonetic else [])
                + [bin_name]
            ))

            try:
                subprocess.Popen(
                    launch_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                # 2. Wait until the window actually opens on screen before sending confirmation
                opened = self._wait_until_actually_open(patterns, timeout=8.0)
                if opened:
                    return True, f"Opened {name}."
                return False, f"Launched {name}, but its window did not appear in time."
            except OSError as error:
                return False, f"Could not launch {name}: {error}"

        # 3. Not found as an installed system app -> check if it's a local folder/file before web search
        exact, _ = self._fast_search_candidates([name, english_phonetic], max_depth=5)
        if len(exact) == 1:
            return self._open_path_with_xdg(exact[0])
        elif len(exact) > 1:
            self.last_search_candidates = exact[:10]
            return self._format_disambiguation_prompt(name, self.last_search_candidates)

        # 4. Not on the system at all -> fall back to self-learning website / Firefox search
        return self.open_website(name, english_phonetic=english_phonetic)

    def close_application(self, name, english_phonetic=None):
        if not name:
            return False, "Application or folder name is missing."

        # 1. First check if there is an open folder/window matching the exact title
        title_candidates = [name]
        if english_phonetic:
            title_candidates.append(english_phonetic)

        matching_windows = self._find_windows_by_title(title_candidates)
        if matching_windows:
            for win_id in matching_windows:
                if which("wmctrl"):
                    self.run_command(["wmctrl", "-ic", win_id])
                elif which("xdotool"):
                    self.run_command(["xdotool", "windowclose", win_id])
            time.sleep(0.6)
            still_open = self._find_windows_by_title(title_candidates)
            if not still_open:
                return True, f"Closed {name}."

        # 2. Otherwise check running application processes
        patterns = set(self.get_process_patterns(name))
        if english_phonetic:
            patterns.update(self.get_process_patterns(english_phonetic))

        all_pids = set()
        for pat in patterns:
            all_pids.update(self._get_process_pids(pat))

        if not all_pids:
            return False, f"Could not find any open folder or application named '{name}'."

        windows = self._get_process_windows(list(all_pids))
        if windows and which("wmctrl"):
            for win in windows:
                self.run_command(["wmctrl", "-ic", win["id"]])
            time.sleep(0.8)
            if not self._get_process_windows(list(all_pids)):
                return True, f"Closed {name}."

        for pid in all_pids:
            self.run_command(["kill", "-TERM", pid])

        time.sleep(0.6)

        remaining = set()
        for pat in patterns:
            remaining.update(self._get_process_pids(pat))

        if remaining:
            for pid in remaining:
                self.run_command(["kill", "-KILL", pid])
            time.sleep(0.3)

        return True, f"Closed {name}."

    # =========================================
    # FIREFOX (CHECKS SYSTEM FIRST IF CALLED DIRECTLY)
    # =========================================

    def open_website(self, website, english_phonetic=None):
        if not website:
            return False, "No website or search term was specified."

        norm_site = self.normalize_name(website)
        if not norm_site.startswith(("http://", "https://")):
            local_app = self._find_installed_desktop_app([website, english_phonetic])
            if local_app:
                return self.open_application(website, english_phonetic=english_phonetic)

        url, resolution = self._resolve_website(website, english_phonetic=english_phonetic)
        if not url:
            return False, "Could not resolve the requested website."

        firefox = which("firefox") or which("firefox-esr")
        if not firefox:
            return False, "Firefox is not installed."

        try:
            subprocess.Popen(
                [firefox, "--new-tab", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            self._wait_until_actually_open(["firefox", "firefox-bin"], timeout=8.0)
            return True, f"Opened {url} in Firefox ({resolution})."
        except OSError as error:
            return False, f"Could not launch Firefox: {error}"

    def browser_navigate(self, url):
        return self.open_website(url)

    # =========================================
    # WEB & VIDEO SEARCH
    # =========================================

    def search_web(self, query, platform=None):
        if not query:
            return False, "Search query is missing."

        platform = str(platform or "").lower()
        if platform in ("youtube", "يوتيوب"):
            url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        elif platform in ("google_images", "images", "صور", "google images"):
            url = "https://www.google.com/search?tbm=isch&q=" + quote_plus(query)
        else:
            url = "https://www.google.com/search?q=" + quote_plus(query)

        return self.browser_navigate(url)

    def search_video(self, query):
        if not query:
            return False, "Video name is missing."

        self.last_video_query = query
        command = ["yt-dlp"] if which("yt-dlp") else [os.sys.executable, "-m", "yt_dlp"]

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

            command = ["yt-dlp"] if which("yt-dlp") else [os.sys.executable, "-m", "yt_dlp"]
            result = self.run_command(
                command + ["--no-warnings", "--skip-download", "--print", "id", f"ytsearch1:{query}"],
                timeout=30
            )
            if not result or result.returncode != 0 or not result.stdout.strip():
                return False, "Could not find the requested video."
            video_id = result.stdout.strip().splitlines()[0]

        return self.browser_navigate("https://www.youtube.com/watch?v=" + video_id)

    # =========================================
    # VOLUME
    # =========================================

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

    # =========================================
    # FAST DUAL-CANDIDATE FILE SEARCH & INTERACTIVE DISAMBIGUATION
    # =========================================

    def _resolve_folder_path(self, folder_name):
        home = Path.home().resolve()
        raw = str(folder_name or "").strip()
        if not raw:
            return home

        mapped = self.FOLDER_ALIASES.get(raw.casefold(), raw)
        if mapped == "":
            return home

        candidate = Path(mapped).expanduser()
        if not candidate.is_absolute():
            candidate = home / candidate
        return Path(os.path.normpath(candidate))

    def _fast_search_candidates(self, query_names, search_root=None, max_depth=5):
        root = search_root or Path.home().resolve()
        clean_queries = [
            str(q).strip() for q in query_names
            if q and str(q).strip()
        ]

        if not clean_queries or not root.exists():
            return [], []

        exact_matches = []
        fuzzy_matches = []
        seen_paths = set()

        norm_targets = {q.casefold() for q in clean_queries}
        compact_targets = {re.sub(r"[\s_\-]+", "", q.casefold()) for q in clean_queries}

        for current, dirs, files in os.walk(root, followlinks=False):
            rel_parts = Path(current).relative_to(root).parts
            if len(rel_parts) >= max_depth:
                dirs[:] = []
            else:
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".") and d not in self.SKIP_DIRS
                ]

            for item in dirs + files:
                full_path = Path(current) / item
                if str(full_path) in seen_paths:
                    continue

                item_lower = item.casefold()
                item_compact = re.sub(r"[\s_\-]+", "", item_lower)
                stem_lower = Path(item).stem.casefold()

                if (
                    item_lower in norm_targets
                    or stem_lower in norm_targets
                    or item_compact in compact_targets
                ):
                    exact_matches.append(full_path)
                    seen_paths.add(str(full_path))
                    continue

                is_similar = False
                for nt in norm_targets:
                    if len(nt) >= 2 and (nt in item_lower or item_lower in nt):
                        is_similar = True
                        break
                    ratio = difflib.SequenceMatcher(None, nt, item_lower).ratio()
                    if ratio >= 0.68:
                        is_similar = True
                        break

                if is_similar:
                    fuzzy_matches.append(full_path)
                    seen_paths.add(str(full_path))

        return exact_matches, fuzzy_matches

    def _open_path_with_xdg(self, path_obj):
        opener = which("xdg-open")
        if not opener:
            return False, "xdg-open is not installed."
        try:
            subprocess.Popen(
                [opener, str(path_obj)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            if path_obj.is_dir():
                self._wait_until_actually_open(["nautilus", "thunar", "dolphin"], timeout=4.0)
            return True, f"Opened {path_obj}"
        except OSError as error:
            return False, str(error)

    def _format_disambiguation_prompt(self, target, candidates):
        """Formats a clear list showing both numbers and parent folder locations."""
        home_path = Path.home().resolve()
        home_str = str(home_path)
        lines = []
        for i, p in enumerate(candidates, 1):
            pretty_path = str(p).replace(home_str, "~")
            parent_name = p.parent.name if p.parent != home_path else "Home"
            kind = "Folder" if p.is_dir() else "File"
            lines.append(f"{i}. {pretty_path}  ({kind} inside {parent_name})")

        msg = (
            f"لقيت أكتر من مسار لـ '{target}'، تحب أفتح أنهي واحد؟\n"
            + "\n".join(lines)
            + "\n(تقدر تقول: 'رقم 1' أو 'اللي في Desktop')"
        )
        return "clarification", msg

    def open_local_file(self, target, parent_folder=None, english_phonetic=None):
        if not target:
            return False, "File or folder name is missing."

        self.last_search_candidates = []

        # Case A: User specified a parent folder (e.g., "open OS inside Home")
        if parent_folder:
            parent_path = self._resolve_folder_path(parent_folder)
            if not parent_path.exists():
                p_exact, _ = self._fast_search_candidates([parent_folder], max_depth=3)
                if p_exact:
                    parent_path = p_exact[0]

            if parent_path.exists() and parent_path.is_dir():
                exact, fuzzy = self._fast_search_candidates(
                    [target, english_phonetic], search_root=parent_path, max_depth=2
                )
                matches = exact or fuzzy
                if len(matches) == 1:
                    return self._open_path_with_xdg(matches[0])
                elif len(matches) > 1:
                    self.last_search_candidates = matches[:10]
                    return self._format_disambiguation_prompt(target, self.last_search_candidates)
                else:
                    self._open_path_with_xdg(parent_path)
                    items = sorted(parent_path.iterdir(), key=lambda x: x.name.lower())
                    contents = "\n".join(
                        f"• {'[Folder]' if it.is_dir() else '[File]'} {it.name}"
                        for it in items[:25]
                    ) or "(Folder is empty)"
                    return True, (
                        f"Could not find '{target}' inside '{parent_path.name}'. "
                        f"Opened '{parent_path.name}' instead. Here is what's inside:\n{contents}"
                    )

        # Case B: Global fast search across Home FIRST so multiple case variants (OS, os, Os, oS) are ALL caught!
        exact, fuzzy = self._fast_search_candidates([target, english_phonetic], max_depth=5)

        if len(exact) == 1:
            return self._open_path_with_xdg(exact[0])

        candidates_to_show = exact if len(exact) > 1 else fuzzy
        if len(candidates_to_show) == 1:
            return self._open_path_with_xdg(candidates_to_show[0])

        if len(candidates_to_show) > 1:
            self.last_search_candidates = candidates_to_show[:10]
            return self._format_disambiguation_prompt(target, self.last_search_candidates)

        return False, f"Could not find any file or folder matching '{target}'."

    def select_search_result(self, selection=None, parent_hint=None):
        if not self.last_search_candidates:
            return False, "There is no active file search list to choose from."

        # 1. Selection by parent folder location (e.g., "اللي في Desktop" or "the one in Documents")
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
                self.last_search_candidates = []
                return self._open_path_with_xdg(parent_matches[0])
            elif len(parent_matches) > 1:
                self.last_search_candidates = parent_matches
                return self._format_disambiguation_prompt(parent_matches[0].name, parent_matches)

        # 2. Selection by number (e.g., "رقم 2" or "التاني")
        if selection is not None:
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(self.last_search_candidates):
                    chosen = self.last_search_candidates[idx]
                    self.last_search_candidates = []
                    return self._open_path_with_xdg(chosen)
            except (TypeError, ValueError):
                pass

        return "clarification", (
            f"اختار رقم من 1 لـ {len(self.last_search_candidates)} "
            "أو قول اسم الفولدر اللي جواه (مثلاً: اللي في Desktop)."
        )

    # =========================================
    # SCROLL & BROWSER NAVIGATION
    # =========================================

    def scroll(self, direction, amount=3):
        if not which("xdotool"):
            return False, "xdotool is not installed."

        try:
            amount = max(1, min(30, int(amount)))
        except (ValueError, TypeError):
            amount = 3

        direction = str(direction).lower()
        button = "4" if direction in ("up", "upward", "أعلى", "فوق") else "5"

        result = self.run_command([
            "xdotool", "click", "--repeat", str(amount), "--delay", "60", button
        ])
        if result and result.returncode == 0:
            return True, "Scrolled up." if button == "4" else "Scrolled down."
        return False, "Scroll failed."

    def browser_key(self, key):
        if not which("xdotool"):
            return False, "xdotool is not installed."

        result = self.run_command(["xdotool", "key", "--clearmodifiers", key])
        if result and result.returncode == 0:
            return True, "Navigation command sent."
        return False, "Navigation failed."

    # =========================================
    # CREATE, DELETE, MOVE, LIST
    # =========================================

    def create_structure(
        self,
        folder_name=None,
        file_name=None,
        content="",
        target=None
    ):
        home = Path.home().resolve()

        try:
            raw_target = str(target or "").strip()
            base_name = self.FOLDER_ALIASES.get(raw_target.casefold(), raw_target)

            base_folder = Path(base_name).expanduser() if base_name else home
            if not base_folder.is_absolute():
                base_folder = home / base_folder

            base_folder = base_folder.resolve()

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
                return True, f"Created file: {file_path}"

            return True, f"Created folder: {folder}"

        except OSError as error:
            return False, str(error)

    def _find_items_in_home(self, name, max_depth=4):
        home = Path.home().resolve()
        requested = str(name).strip().rstrip("/")
        if not requested:
            return []

        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = home / candidate
        candidate = Path(os.path.normpath(candidate))

        if candidate.exists() or candidate.is_symlink():
            return [candidate]

        wanted = Path(requested).name.casefold()
        matches = []

        for current, dirs, files in os.walk(home, followlinks=False):
            for item in dirs + files:
                if item.casefold() == wanted:
                    matches.append(Path(current) / item)

            depth = len(Path(current).relative_to(home).parts)
            if depth >= max_depth - 1:
                dirs[:] = []
            else:
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".") and d not in self.SKIP_DIRS
                ]

        return matches

    def delete_item(self, target, confirm_callback=None):
        if not target:
            return False, "Target is missing."

        home = Path.home().resolve()
        matches = self._find_items_in_home(target)

        if not matches:
            return False, f"Could not find {target} in your home folder."

        if len(matches) > 1:
            shown = ", ".join(str(match) for match in matches[:5])
            return False, (
                f"Found {len(matches)} items named {target}: {shown}. Please say which one."
            )

        path = matches[0]
        parent = path.parent.resolve()

        protected = {home} | {
            home / name for name in (
                "Desktop", "Documents", "Downloads",
                "Pictures", "Music", "Videos"
            )
        }

        if (parent != home and home not in parent.parents) or path in protected:
            return False, "This item cannot be deleted."

        if confirm_callback is None:
            return False, "Deletion requires confirmation."

        try:
            approved = confirm_callback(str(path))
        except Exception:
            approved = False

        if not approved:
            return False, "Deletion cancelled."

        try:
            if which("gio"):
                result = self.run_command(["gio", "trash", str(path)])
                if result and result.returncode == 0:
                    return True, f"Moved {path} to Trash."

            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)

            return True, f"Deleted {path}."

        except OSError as error:
            return False, str(error)

    def move_item(self, source_path, destination_path):
        if not source_path or not destination_path:
            return False, "Source or destination path is missing."

        home = Path.home().resolve()
        source = Path(str(source_path)).expanduser()
        destination = Path(str(destination_path)).expanduser()

        try:
            source_resolved = source.resolve(strict=True)
            destination_resolved = destination.resolve(strict=True)

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

            new_path = destination_resolved / source.name
            if new_path.exists() or new_path.is_symlink():
                return False, "An item with the same name already exists."

            shutil.move(str(source), str(new_path))
            return True, f"Moved {source.name} to {destination_resolved}."

        except FileNotFoundError:
            return False, "Source or destination was not found."
        except ValueError:
            return False, "Moving items outside your Home folder is not allowed."
        except OSError as error:
            return False, str(error)

    def list_directory(self, target):
        if not target:
            return False, "Folder path is missing."

        home = Path.home().resolve()
        folder = self._resolve_folder_path(target)

        try:
            folder = folder.resolve(strict=True)
            folder.relative_to(home)

            if not folder.is_dir():
                return False, "The requested path is not a folder."

            items = sorted(folder.iterdir(), key=lambda item: item.name.lower())
            if not items:
                return True, "The folder is empty."

            lines = [
                f"{'[Folder]' if item.is_dir() else '[File]'} {item.name}"
                for item in items
            ]
            return True, "Contents of " + str(folder) + ":\n" + "\n".join(lines)

        except FileNotFoundError:
            return False, "Folder not found."
        except ValueError:
            return False, "Access outside your Home folder is not allowed."
        except OSError as error:
            return False, str(error)