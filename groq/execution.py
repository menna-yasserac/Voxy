import os
import re
import json
import time
import shutil
import subprocess
import urllib.request
import urllib.error

from pathlib import Path
from urllib.parse import quote_plus

try:
    from atspi_controller import ATSPIController
    ATSPI_AVAILABLE = True
except (ImportError, OSError):
    ATSPIController = None
    ATSPI_AVAILABLE = False


def which(name):
    return shutil.which(name)


class LinuxExecutor:

    APP_ALIASES = {
        "firefox": ["firefox", "firefox-esr"],
        "فايرفوكس": ["firefox", "firefox-esr"],
        "chrome": [
            "google-chrome", "google-chrome-stable",
            "chromium", "chromium-browser"
        ],
        "كروم": [
            "google-chrome", "google-chrome-stable",
            "chromium", "chromium-browser"
        ],
        "terminal": [
            "gnome-terminal", "xfce4-terminal",
            "x-terminal-emulator"
        ],
        "ترمينال": ["gnome-terminal", "xfce4-terminal"],
        "files": ["nautilus", "thunar", "dolphin"],
        "file manager": ["nautilus", "thunar", "dolphin"],
        "الملفات": ["nautilus", "thunar", "dolphin"],
        "calculator": ["gnome-calculator", "kcalc"],
        "الحاسبة": ["gnome-calculator", "kcalc"],
        "settings": ["gnome-control-center"],
        "الإعدادات": ["gnome-control-center"],
        "text editor": ["gedit", "gnome-text-editor", "mousepad"],
        "المفكرة": ["gedit", "gnome-text-editor", "mousepad"],
    }

    WEBSITE_ALIASES = {
        "google": "https://www.google.com",
        "جوجل": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "يوتيوب": "https://www.youtube.com",
        "facebook": "https://www.facebook.com",
        "فيسبوك": "https://www.facebook.com",
        "فيس بوك": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "انستغرام": "https://www.instagram.com",
        "إنستغرام": "https://www.instagram.com",
        "انستجرام": "https://www.instagram.com",
        "إنستجرام": "https://www.instagram.com",
        "twitter": "https://www.x.com",
        "تويتر": "https://www.x.com",
        "x": "https://www.x.com",
        "gemini": "https://gemini.google.com",
        "جيميناي": "https://gemini.google.com",
        "جيميني": "https://gemini.google.com",
        "chatgpt": "https://chatgpt.com",
        "chat gpt": "https://chatgpt.com",
        "تشات جي بي تي": "https://chatgpt.com",
        "شات جي بي تي": "https://chatgpt.com",
        "whatsapp": "https://web.whatsapp.com",
        "واتساب": "https://web.whatsapp.com",
        "واتس اب": "https://web.whatsapp.com",
        "linkedin": "https://www.linkedin.com",
        "لينكدان": "https://www.linkedin.com",
        "pinterest": "https://www.pinterest.com",
        "بينترست": "https://www.pinterest.com",
        "telegram": "https://web.telegram.org",
        "تليجرام": "https://web.telegram.org",
        "gmail": "https://mail.google.com",
        "جيميل": "https://mail.google.com",
        "drive": "https://drive.google.com",
        "google drive": "https://drive.google.com",
        "جوجل درايف": "https://drive.google.com",
        "github": "https://github.com",
        "جيت هاب": "https://github.com",
        "netflix": "https://www.netflix.com",
        "نتفلكس": "https://www.netflix.com",
        "spotify": "https://open.spotify.com",
        "سبوتيفاي": "https://open.spotify.com",
    }

    SKIP_DIRS = {
        "proc", "sys", "dev", "run", "snap",
        "node_modules", "__pycache__", ".cache",
        "Trash", ".Trash-1000",
    }

    def __init__(self):
        self.last_video_query = None
        self.last_video_ids = []
        self.last_video_titles = []

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

    # =========================================
    # AT-SPI HELPERS
    # =========================================

    def _normalize_atspi_result(self, result, operation):
        """
        Converts the AT-SPI controller result into
        the (success, message) format used by LinuxExecutor.
        """

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
        """
        Click by accessible element name first.
        Coordinate clicking is supported only when x and y
        are explicitly provided.
        """

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
                success, message = self._normalize_atspi_result(
                    result, "click"
                )

                if success:
                    return True, message

                print(f"[AT-SPI] Click failed: {message}")

            except Exception as error:
                print(f"[AT-SPI] Click error: {error}")

        # Coordinates are an explicit fallback only.
        x = data.get("x")
        y = data.get("y")

        if x is not None and y is not None:
            if not which("xdotool"):
                return False, "xdotool is not installed."

            result = self.run_command([
                "xdotool",
                "mousemove",
                str(int(x)),
                str(int(y)),
                "click",
                "1"
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
        """
        If an element name is provided, use AT-SPI.
        Otherwise type into the currently focused element using xdotool.
        """

        if text is None:
            return False, "No text provided."

        if element_name:
            if not self.atspi:
                return False, "AT-SPI is not available."

            try:
                result = self.atspi.type_text(
                    str(element_name),
                    str(text)
                )

                success, message = self._normalize_atspi_result(
                    result, "typing"
                )

                if success:
                    return True, message

                return False, message

            except Exception as error:
                return False, f"AT-SPI typing failed: {error}"

        if not which("xdotool"):
            return False, "xdotool is not installed."

        result = self.run_command([
            "xdotool",
            "type",
            "--clearmodifiers",
            "--delay",
            "2",
            str(text)
        ], timeout=20)

        if result and result.returncode == 0:
            return True, "Text typed into the focused element."

        return False, "Typing failed."

    # =========================================
    # PROCESS AND WINDOW DISCOVERY
    # =========================================

    def _get_process_pids(self, process_name):
        result = self.run_command([
            "pgrep", "-x", os.path.basename(process_name)
        ])

        if not result or result.returncode != 0:
            return []

        return [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]

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

                    window_id = parts[0]
                    pid = parts[2]
                    title = parts[4] if len(parts) > 4 else ""

                    if pid in pids:
                        windows.append({
                            "id": window_id,
                            "pid": pid,
                            "title": title
                        })

        if which("xdotool"):
            for pid in pids:
                result = self.run_command([
                    "xdotool",
                    "search",
                    "--onlyvisible",
                    "--pid",
                    pid
                ])

                if result and result.returncode == 0:
                    for window_id in result.stdout.splitlines():
                        window_id = window_id.strip()

                        if not window_id:
                            continue

                        if not any(w["id"] == window_id for w in windows):
                            windows.append({
                                "id": window_id,
                                "pid": pid,
                                "title": ""
                            })

        return windows

    def _wait_for_app_window(self, process_names, timeout=12):
        start = time.time()

        while time.time() - start < timeout:
            for process_name in process_names:
                pids = self._get_process_pids(process_name)
                windows = self._get_process_windows(pids)

                if windows:
                    return windows[0]

            time.sleep(0.4)

        return None

    # =========================================
    # WEBSITE RESOLUTION
    # =========================================

    def _verify_website(self, url, timeout=5):
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

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError
        ):
            return None

    def _resolve_website(self, website):
        website = self.normalize_name(website)

        if not website:
            return None, "Website name is missing."

        known_url = self.WEBSITE_ALIASES.get(website)

        if known_url:
            return known_url, "known"

        if website.startswith(("https://", "http://")):
            return website, "explicit_url"

        if re.match(
            r"^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(/.*)?$",
            website
        ):
            url = "https://" + website
            verified = self._verify_website(url)

            if verified:
                return verified, "verified_domain"

            return (
                "https://www.google.com/search?q=" + quote_plus(website),
                "google_fallback"
            )

        if re.fullmatch(r"[a-zA-Z0-9-]+", website):
            slug = website.lower()

            for candidate in (
                f"https://www.{slug}.com",
                f"https://{slug}.com"
            ):
                verified = self._verify_website(candidate)

                if verified:
                    return verified, "dynamic_domain"

        return (
            "https://www.google.com/search?q=" + quote_plus(website),
            "google_fallback"
        )

    # =========================================
    # MAIN EXECUTION
    # =========================================

    def execute_actions(self, command_data, confirm_callback=None):
        if not isinstance(command_data, dict):
            return {
                "success": False,
                "message": "Invalid command data.",
                "results": []
            }

        actions = command_data.get("actions")

        if not isinstance(actions, list) or not actions:
            actions = [command_data]

        results = []

        for action_data in actions:
            if not isinstance(action_data, dict):
                results.append({
                    "success": False,
                    "message": "Invalid action."
                })
                continue

            results.append(
                self.execute_one(action_data, confirm_callback)
            )

        success = all(
            result.get("success", False)
            for result in results
        )

        return {
            "success": success,
            "message": (
                "All actions completed."
                if success else "One or more actions failed."
            ),
            "results": results
        }

    def execute_one(self, data, confirm_callback=None):
        intent = str(data.get("intent", "unknown")).lower()

        target = (
            data.get("target")
            or data.get("application")
            or ""
        )

        query = data.get("query") or target
        action = str(data.get("action") or "").lower()

        handlers = {
            "open_application":
                lambda: self.open_application(target),

            "close_application":
                lambda: self.close_application(target),

            "open_website":
                lambda: self.open_website(
                    target or data.get("platform")
                ),

            "search_web":
                lambda: self.search_web(
                    query, data.get("platform")
                ),

            "search_video":
                lambda: self.search_video(query),

            "play_video":
                lambda: self.play_video(
                    query,
                    data.get("platform") or "youtube",
                    data.get("selection")
                ),

            "open_local_file":
                lambda: self.open_local_file(target or query),

            "click":
                lambda: self.click_element(data),

            "click_element":
                lambda: self.click_element(data),

            "type_text":
                lambda: self.type_text(
                    data.get("text") or target,
                    data.get("element_name")
                    or data.get("element")
                ),

            "type_into_element":
                lambda: self.type_text(
                    data.get("text"),
                    data.get("element_name")
                    or data.get("element")
                    or target
                ),

            "list_ui_elements":
                lambda: self.list_ui_elements_result(),

            "scroll":
                lambda: self.scroll(
                    action, data.get("amount", 3)
                ),

            "go_back":
                lambda: self.browser_key("Alt+Left"),

            "go_forward":
                lambda: self.browser_key("Alt+Right"),

            "go_home":
                lambda: self.browser_key("Alt+Home"),

            "increase_volume":
                lambda: self.change_volume(
                    "up", data.get("amount", 5)
                ),

            "decrease_volume":
                lambda: self.change_volume(
                    "down", data.get("amount", 5)
                ),

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
                    data.get("content", "")
                ),

            "delete_item":
                lambda: self.delete_item(
                    target, confirm_callback
                ),

            "conversational_response":
                lambda: (
                    True,
                    data.get("response_text", "Okay.")
                )
        }

        handler = handlers.get(intent)

        if not handler:
            return {
                "success": False,
                "intent": intent,
                "message": f"Unsupported intent: {intent}"
            }

        try:
            success, message = handler()

            return {
                "success": bool(success),
                "intent": intent,
                "message": message
            }

        except Exception as error:
            return {
                "success": False,
                "intent": intent,
                "message": str(error)
            }

    def list_ui_elements_result(self):
        success, message, elements = self.list_ui_elements()

        if not success:
            return False, message

        return True, json.dumps(
            elements,
            ensure_ascii=False
        )

    # =========================================
    # OPEN APPLICATION
    # =========================================

    def open_application(self, name):
        if not name:
            return False, "Application or website name is missing."

        normalized = self.normalize_name(name)

        if normalized in self.APP_ALIASES:
            candidates = self.get_app_candidates(normalized)
            available = []

            for candidate in candidates:
                executable = which(candidate)

                if executable:
                    available.append((candidate, executable))

            if not available:
                return self.open_website(name)

            for candidate, executable in available:
                pids = self._get_process_pids(candidate)
                windows = self._get_process_windows(pids)

                if windows:
                    return True, f"{name} is already open."

            launch_errors = []

            for candidate, executable in available:
                try:
                    subprocess.Popen(
                        [executable],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                except OSError as error:
                    launch_errors.append(str(error))
                    continue

                window = self._wait_for_app_window(
                    [candidate], timeout=12
                )

                if window:
                    return True, f"Opened {name}."

                if self._get_process_pids(candidate):
                    return False, (
                        f"{name} process is running, but no visible "
                        "application window was detected."
                    )

            if launch_errors:
                return False, (
                    f"Could not launch {name}: "
                    + "; ".join(launch_errors)
                )

            return False, f"Could not open {name}."

        return self.open_website(name)

    # =========================================
    # CLOSE APPLICATION
    # =========================================

    def close_application(self, name):
        if not name:
            return False, "Application name is missing."

        candidates = list(set(self.get_app_candidates(name)))
        running = []

        for candidate in candidates:
            pids = self._get_process_pids(candidate)

            if pids:
                running.append({
                    "process": os.path.basename(candidate),
                    "pids": pids
                })

        if not running:
            return False, f"{name} is not running."

        all_pids = [
            pid for item in running for pid in item["pids"]
        ]

        windows = self._get_process_windows(all_pids)

        if windows and which("wmctrl"):
            for window in windows:
                self.run_command([
                    "wmctrl", "-ic", window["id"]
                ])

            time.sleep(1.5)

            if not self._get_process_windows(all_pids):
                return True, f"Closed {name}."

        for item in running:
            self.run_command([
                "pkill", "-TERM", "-x", item["process"]
            ])

        time.sleep(1)

        still_running = []

        for item in running:
            still_running.extend(
                self._get_process_pids(item["process"])
            )

        if still_running:
            return False, (
                f"Could not completely close {name}. "
                f"Remaining process IDs: {still_running}"
            )

        return True, f"Closed {name}."

    # =========================================
    # FIREFOX
    # =========================================

    def _get_firefox_window(self):
        if not which("xdotool"):
            return None

        searches = [
            [
                "xdotool", "search", "--onlyvisible",
                "--class", "firefox"
            ],
            [
                "xdotool", "search", "--onlyvisible",
                "--name", "Mozilla Firefox"
            ]
        ]

        for command in searches:
            result = self.run_command(command, timeout=3)

            if result and result.returncode == 0:
                windows = result.stdout.strip().splitlines()

                if windows:
                    return windows[-1]

        return None

    def _wait_for_firefox_window(self, timeout=20):
        start = time.time()

        while time.time() - start < timeout:
            window_id = self._get_firefox_window()

            if window_id:
                return window_id

            time.sleep(0.5)

        return None

    def open_website(self, website):
        if not website:
            return False, "No website or search term was specified."

        url, resolution = self._resolve_website(website)

        if not url:
            return False, "Could not resolve the requested website."

        firefox = which("firefox") or which("firefox-esr")

        if not firefox:
            return False, "Firefox is not installed."

        window_id = self._get_firefox_window()

        if not window_id:
            try:
                subprocess.Popen(
                    [firefox, "--new-window", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )

                window_id = self._wait_for_firefox_window()

                if not window_id:
                    return False, "Firefox window was not detected."

                return True, (
                    f"Firefox opened with {url} "
                    f"(resolution: {resolution})."
                )

            except OSError as error:
                return False, f"Could not launch Firefox: {error}"

        if not which("xdotool"):
            return False, "xdotool is required for Firefox navigation."

        try:
            activate = self.run_command([
                "xdotool", "windowactivate",
                "--sync", window_id
            ])

            if not activate or activate.returncode != 0:
                return False, "Could not activate Firefox."

            time.sleep(0.5)

            focused = self.run_command([
                "xdotool", "getwindowfocus"
            ])

            if not focused or focused.returncode != 0:
                return False, "Could not verify Firefox focus."

            focused_id = focused.stdout.strip()

            if focused_id != window_id:
                parent = self.run_command([
                    "xdotool", "getwindowpid", focused_id
                ])

                expected = self.run_command([
                    "xdotool", "getwindowpid", window_id
                ])

                if (
                    not parent or not expected
                    or parent.returncode != 0
                    or expected.returncode != 0
                    or parent.stdout.strip() != expected.stdout.strip()
                ):
                    return False, "Firefox could not be focused."

            result = self.run_command([
                "xdotool", "key", "--clearmodifiers", "ctrl+l"
            ])

            if not result or result.returncode != 0:
                return False, "Could not focus Firefox address bar."

            result = self.run_command([
                "xdotool", "type",
                "--clearmodifiers",
                "--delay", "2",
                "--", url
            ], timeout=10)

            if not result or result.returncode != 0:
                return False, "Could not type website URL."

            result = self.run_command([
                "xdotool", "key", "Return"
            ])

            if not result or result.returncode != 0:
                return False, "Could not submit website URL."

            return True, (
                f"Navigating Firefox current tab to {url} "
                f"(resolution: {resolution})."
            )

        except Exception as error:
            return False, f"Firefox navigation failed: {error}"

    def browser_navigate(self, url):
        return self.open_website(url)

    # =========================================
    # WEB SEARCH
    # =========================================

    def search_web(self, query, platform=None):
        if not query:
            return False, "Search query is missing."

        platform = str(platform or "").lower()

        if platform in ("youtube", "يوتيوب"):
            url = (
                "https://www.youtube.com/results?search_query="
                + quote_plus(query)
            )
        elif platform in (
            "google_images", "images", "صور", "google images"
        ):
            url = (
                "https://www.google.com/search?tbm=isch&q="
                + quote_plus(query)
            )
        else:
            url = (
                "https://www.google.com/search?q="
                + quote_plus(query)
            )

        return self.browser_navigate(url)

    # =========================================
    # YOUTUBE
    # =========================================

    def search_video(self, query):
        if not query:
            return False, "Video name is missing."

        self.last_video_query = query

        command = (
            ["yt-dlp"] if which("yt-dlp")
            else [os.sys.executable, "-m", "yt_dlp"]
        )

        result = self.run_command(
            command + [
                "--flat-playlist",
                "--dump-single-json",
                f"ytsearch10:{query}"
            ],
            timeout=40
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
                        self.last_video_titles.append(
                            entry.get("title", "")
                        )

            except (json.JSONDecodeError, AttributeError):
                pass

        url = (
            "https://www.youtube.com/results?search_query="
            + quote_plus(query)
        )

        success, message = self.browser_navigate(url)

        if success:
            return True, f"Showing YouTube results for {query}."

        return False, message

    def play_video(
        self,
        query=None,
        platform="youtube",
        selection=None
    ):
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

            command = (
                ["yt-dlp"] if which("yt-dlp")
                else [os.sys.executable, "-m", "yt_dlp"]
            )

            result = self.run_command(
                command + [
                    "--no-warnings",
                    "--skip-download",
                    "--print",
                    "id",
                    f"ytsearch1:{query}"
                ],
                timeout=40
            )

            if (
                not result
                or result.returncode != 0
                or not result.stdout.strip()
            ):
                return False, "Could not find the requested video."

            video_id = result.stdout.strip().splitlines()[0]

        url = "https://www.youtube.com/watch?v=" + video_id

        return self.browser_navigate(url)

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

        if direction == "up":
            wpctl_value = f"{amount}%+"
            pactl_value = f"+{amount}%"
        else:
            wpctl_value = f"{amount}%-"
            pactl_value = f"-{amount}%"

        if backend == "wpctl":
            result = self.run_command([
                "wpctl", "set-volume",
                "@DEFAULT_AUDIO_SINK@", wpctl_value
            ])
        else:
            result = self.run_command([
                "pactl", "set-sink-volume",
                "@DEFAULT_SINK@", pactl_value
            ])

        if result and result.returncode == 0:
            return True, (
                f"Volume {'increased' if direction == 'up' else 'decreased'} "
                f"by {amount}%."
            )

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
            result = self.run_command([
                "wpctl", "set-volume",
                "@DEFAULT_AUDIO_SINK@", f"{value}%"
            ])
        else:
            result = self.run_command([
                "pactl", "set-sink-volume",
                "@DEFAULT_SINK@", f"{value}%"
            ])

        if result and result.returncode == 0:
            return True, f"Volume set to {value}%."

        return False, "Could not set volume."

    def mute(self, enabled=True):
        backend = self.volume_backend()

        if not backend:
            return False, "No supported volume controller found."

        value = "1" if enabled else "0"

        if backend == "wpctl":
            result = self.run_command([
                "wpctl", "set-mute",
                "@DEFAULT_AUDIO_SINK@", value
            ])
        else:
            result = self.run_command([
                "pactl", "set-sink-mute",
                "@DEFAULT_SINK@", value
            ])

        if result and result.returncode == 0:
            return True, (
                "Volume muted." if enabled else "Volume unmuted."
            )

        return False, "Could not change mute state."

    # =========================================
    # FILE SEARCH
    # =========================================

    def search_file(self, requested):
        requested = str(requested).strip().casefold()

        if not requested:
            return None

        if which("locate"):
            result = self.run_command([
                "locate", "-i", "-l", "50", "--", requested
            ], timeout=20)

            if result and result.returncode == 0:
                for line in result.stdout.splitlines():
                    path = Path(line)

                    if path.exists():
                        return path

        checked = 0

        for current, dirs, files in os.walk(
            "/",
            topdown=True,
            followlinks=False,
            onerror=lambda error: None
        ):
            dirs[:] = [
                directory for directory in dirs
                if directory not in self.SKIP_DIRS
            ]

            checked += 1

            if checked > 100000:
                break

            for name in dirs + files:
                if requested in name.casefold():
                    candidate = Path(current) / name

                    if candidate.exists():
                        return candidate

        return None

    def open_local_file(self, target):
        if not target:
            return False, "File or folder name is missing."

        path = Path(str(target)).expanduser()

        found = path if path.exists() else self.search_file(target)

        if not found:
            return False, f"Could not find {target}."

        opener = which("xdg-open")

        if not opener:
            return False, "xdg-open is not installed."

        try:
            subprocess.Popen(
                [opener, str(found)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            return True, f"Opening {found}."

        except OSError as error:
            return False, str(error)

    # =========================================
    # SCROLL
    # =========================================

    def scroll(self, direction, amount=3):
        if not which("xdotool"):
            return False, "xdotool is not installed."

        try:
            amount = max(1, min(30, int(amount)))
        except (ValueError, TypeError):
            amount = 3

        direction = str(direction).lower()

        button = (
            "4" if direction in (
                "up", "upward", "أعلى", "فوق"
            ) else "5"
        )

        result = self.run_command([
            "xdotool", "click",
            "--repeat", str(amount),
            "--delay", "60",
            button
        ])

        if result and result.returncode == 0:
            return True, (
                "Scrolled up." if button == "4"
                else "Scrolled down."
            )

        return False, "Scroll failed."

    # =========================================
    # BROWSER NAVIGATION
    # =========================================

    def browser_key(self, key):
        if not which("xdotool"):
            return False, "xdotool is not installed."

        window_id = self._get_firefox_window()

        if not window_id:
            return False, "Firefox is not open."

        activate = self.run_command([
            "xdotool", "windowactivate",
            "--sync", window_id
        ])

        if not activate or activate.returncode != 0:
            return False, "Could not activate Firefox."

        result = self.run_command([
            "xdotool", "key",
            "--clearmodifiers", key
        ])

        if result and result.returncode == 0:
            return True, "Navigation command sent."

        return False, "Navigation failed."

    # =========================================
    # CREATE FILE / FOLDER
    # =========================================

    def create_structure(
        self,
        folder_name=None,
        file_name=None,
        content=""
    ):
        home = Path.home().resolve()

        try:
            folder = (
                home / folder_name if folder_name else home
            ).resolve()

            if home not in (folder, *folder.parents):
                return False, "Folder must be inside home directory."

            folder.mkdir(parents=True, exist_ok=True)

            if file_name:
                file_path = (folder / file_name).resolve()

                if folder not in file_path.parents:
                    return False, "Invalid file path."

                file_path.parent.mkdir(
                    parents=True, exist_ok=True
                )

                file_path.write_text(
                    str(content or ""),
                    encoding="utf-8"
                )

                return True, f"Created file: {file_path}"

            return True, f"Created folder: {folder}"

        except OSError as error:
            return False, str(error)

    # =========================================
    # DELETE
    # =========================================

    def delete_item(self, target, confirm_callback=None):
        if not target:
            return False, "Target is missing."

        path = Path(str(target)).expanduser()

        if not path.exists():
            found = self.search_file(target)

            if found:
                path = found

        if not path.exists():
            return False, "Item not found."

        if confirm_callback is None:
            return False, "Deletion requires confirmation."

        try:
            approved = confirm_callback(str(path))
        except Exception:
            approved = False

        if not approved:
            return False, "Deletion cancelled."

        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

            return True, f"Deleted {path}."

        except OSError as error:
            return False, str(error)