"""
Voxy SecurityManager (v2)

Drop-in replacement: same public API as before
    SecurityManager(home=None)
    validate_actions(command_data)   -> (ok, message)
    validate_delete_target(path)     -> (ok, resolved_path, message)
plus optional extra final-checks you can call from the executor:
    validate_move_target(src, dst)   -> (ok, src_resolved, dst_resolved, message)
    validate_write_target(path)      -> (ok, resolved_path, message)

Design rules
- The AI output is untrusted: whitelist intents, bound every field.
- Spoken names (e.g. "report") are NOT paths. They are only checked for
  tricks (.., hidden names). Explicit paths must resolve inside Home.
- Hidden / system locations (~/.ssh, ~/.bashrc, ~/.config ...) are off limits
  for create / delete / move / rename.
- The real protection for delete/move happens on the FINAL resolved path
  (after the file search), via the validate_*_target helpers.
"""

import logging
import math
import re
from pathlib import Path

log = logging.getLogger("voxy.security")


class SecurityManager:
    # Keep this list aligned with the handlers in LinuxExecutor.execute_one.
    ALLOWED_INTENTS = {
        "open_application", "close_application", "open_website",
        "search_web", "search_video", "play_video", "open_local_file",
        "list_directory", "click", "click_element", "type_text",
        "type_into_element", "list_ui_elements", "scroll", "go_back",
        "go_forward", "go_home", "increase_volume", "decrease_volume",
        "set_volume", "mute", "unmute", "create_structure",
        "delete_item", "move_item", "rename_item", "confirm_action",
        "select_search_result", "conversational_response",
    }

    MAX_TEXT_LENGTH = 5000
    MAX_NAME_LENGTH = 255

    # Every string field the AI may fill. Anything here must be a bounded str.
    TEXT_FIELDS = (
        "target", "application", "query", "text", "content",
        "folder_name", "file_name", "source_path", "destination_path",
        "response_text", "new_name", "element_name", "element",
        "english_phonetic", "symbol_variant", "action", "url",
        "selected_path", "parent_hint",
    )

    # Top-level Home folders that must never be deleted / moved / renamed.
    PROTECTED_NAMES = (
        "Desktop", "Documents", "Downloads", "Pictures", "Music",
        "Videos", "Public", "Templates",
    )

    # File types that can auto-run code or persist; never create/rename to these.
    BLOCKED_EXTENSIONS = {
        ".desktop", ".service", ".timer", ".socket", ".so", ".exe",
        ".dll", ".bat", ".cmd", ".scr", ".msi", ".appimage",
    }

    # Opening a terminal is allowed by default. Dangerous commands typed into
    # it are still blocked by _DANGEROUS_TEXT. Set to False to forbid terminals.
    ALLOW_TERMINALS = True
    _TERMINAL_SUBSTRINGS = (
        "terminal", "konsole", "xterm", "alacritty", "kitty", "tilix",
        "terminator", "urxvt", "wezterm", "ptyxis", "powershell", "tmux",
        "تيرمنال", "ترمنال", "تيرمينال", "ترمينال", "الطرفية", "طرفية",
    )
    _SHELL_EXACT = {"sh", "bash", "zsh", "fish", "dash", "cmd", "python",
                    "python3", "foot", "st"}

    # URL schemes that must never be opened.
    _BAD_URL_SCHEME = re.compile(
        r"^\s*(javascript|file|data|vbscript|blob|about|view-source|chrome|ftp)\s*:",
        re.IGNORECASE,
    )

    # Obviously destructive shell text typed into any window.
    _DANGEROUS_TEXT = [re.compile(p, re.IGNORECASE) for p in (
        r"\brm\s+-[a-z]*[rf]",
        r"\bsudo\b",
        r"\bpkexec\b",
        r"\bmkfs",
        r"\bdd\s+if=",
        r":\(\)\s*\{",
        r"\bchmod\s+-r",
        r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z)?sh\b",
        r">\s*/dev/sd",
        r"\b(shutdown|reboot|poweroff)\b",
    )]

    def __init__(self, home=None, allow_terminals=None):
        if allow_terminals is not None:
            self.ALLOW_TERMINALS = bool(allow_terminals)
        self.home = Path(home or Path.home()).expanduser().resolve()
        self._protected = {self.home}
        for name in self.PROTECTED_NAMES:
            p = self.home / name
            self._protected.add(p)
            try:
                self._protected.add(p.resolve())
            except (OSError, RuntimeError):
                pass
        self._protected_lower = {n.casefold() for n in self.PROTECTED_NAMES}

    # ------------------------------------------------------------------
    # path helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _looks_like_path(value):
        return "/" in value or "\\" in value or value.startswith("~")

    def _inside_home(self, path, must_exist=False):
        """Return (allowed, resolved_path); reject paths outside Home."""
        try:
            candidate = Path(str(path)).expanduser()
            if not candidate.is_absolute():
                candidate = self.home / candidate
            resolved = candidate.resolve(strict=must_exist)
            resolved.relative_to(self.home)
            return True, resolved
        except (OSError, RuntimeError, ValueError):
            return False, None

    def _is_hidden(self, resolved):
        try:
            rel = resolved.relative_to(self.home)
        except ValueError:
            return True
        return any(part.startswith(".") for part in rel.parts)

    def _is_protected(self, resolved):
        return resolved in self._protected

    def _check_user_path(self, value, label, *, protect=False, allow_hidden=False,
                         protect_by_name=True):
        """Check a spoken name OR explicit path. Return error text or None.

        protect_by_name=False: a plain spoken name (e.g. "downloads") is NOT
        rejected just because it matches a system folder name. The user may
        own a folder called "downloads" somewhere else. The real protection
        is then done on the final resolved path (validate_delete_target).
        """
        value = value.strip()
        if not value:
            return f"{label} is empty."

        if self._looks_like_path(value):
            ok, resolved = self._inside_home(value)
            if not ok:
                return f"{label} must be inside your Home folder."
            if not allow_hidden and self._is_hidden(resolved):
                return f"{label} points to a hidden/system location."
            if protect and self._is_protected(resolved):
                return f"{label} is a protected folder."
            return None

        # Plain spoken name: only reject tricks.
        if value.startswith(".") and not allow_hidden:
            return f"{label} is a hidden/system name."
        if protect and protect_by_name and value.casefold() in self._protected_lower:
            return f"{label} is a protected folder."
        return None

    def _check_relative_part(self, value, label):
        """For folder_name / file_name: must stay relative, no tricks."""
        value = value.strip()
        if not value:
            return None
        if value.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:", value):
            return f"{label} must be a relative name."
        parts = [p for p in re.split(r"[\\/]+", value) if p]
        for part in parts:
            if part in (".", "..") or part.startswith("."):
                return f"{label} contains a hidden or invalid part."
            if len(part) > self.MAX_NAME_LENGTH:
                return f"{label} is too long."
        return self._check_extension(value, label)

    def _check_extension(self, name, label):
        suffix = Path(name.strip()).suffix.lower()
        if suffix in self.BLOCKED_EXTENSIONS:
            return f"{label}: files of type {suffix} are not allowed."
        return None

    # ------------------------------------------------------------------
    # main validation
    # ------------------------------------------------------------------
    def validate_actions(self, command_data):
        """Validate the whole AI response before any action is executed.

        Note: the intent of every action is normalised in place
        (strip + lowercase) so the executor runs exactly what was validated.
        """
        ok, msg = self._validate(command_data)
        if not ok:
            log.warning("Security blocked request: %s", msg)
        return ok, msg

    def _block(self, index, reason):
        return False, f"Security blocked action {index}: {reason}"

    def _validate(self, command_data):
        if not isinstance(command_data, dict):
            return False, "Security blocked the request: invalid command data."

        actions = command_data.get("actions")
        if not isinstance(actions, list) or not actions:
            actions = [command_data]


        for index, item in enumerate(actions, start=1):
            if not isinstance(item, dict):
                return self._block(index, "invalid action format.")

            raw_intent = item.get("intent")
            if not isinstance(raw_intent, str):
                return self._block(index, "unsupported operation.")
            intent = raw_intent.strip().lower()
            if intent not in self.ALLOWED_INTENTS:
                return self._block(index, "unsupported operation.")
            item["intent"] = intent  # executor now sees the validated value

            # Bound every untrusted text field.
            for field in self.TEXT_FIELDS:
                value = item.get(field)
                if value is None:
                    continue
                if (not isinstance(value, str)
                        or len(value) > self.MAX_TEXT_LENGTH
                        or "\x00" in value):
                    return self._block(index, f"invalid or oversized {field}.")

            err = self._validate_intent(intent, item)
            if err:
                return self._block(index, err)

        return True, "Security validation passed."

    def _validate_intent(self, intent, item):
        """Return an error string, or None when the action is fine."""
        s = lambda k: (item.get(k) or "").strip() if isinstance(item.get(k), str) else ""

        if intent == "delete_item":
            names = [v for v in (s("file_name"), s("folder_name"), s("target")) if v]
            if not names:
                return "deletion target is missing."
            # The executor uses file_name -> folder_name -> target, so check all.
            for value in names:
                err = self._check_user_path(value, "deletion target",
                                            protect=True, protect_by_name=False)
                if err:
                    return err

        elif intent == "move_item":
            source = s("source_path") or s("target")
            dest = s("destination_path")
            if not source or not dest:
                return "source and destination are required."
            for value, label in ((source, "source"), (dest, "destination")):
                err = self._check_user_path(value, label, protect=(label == "source"))
                if err:
                    return err

        elif intent == "rename_item":
            source = s("source_path") or s("target")
            new_name = s("new_name") or s("destination_path")
            if not source or not new_name:
                return "current name and new name are required."
            err = self._check_user_path(source, "source", protect=True)
            if err:
                return err
            if re.search(r"[\\/]", new_name) or new_name.startswith("."):
                return "new name must be a simple, non-hidden name."
            if len(new_name) > self.MAX_NAME_LENGTH:
                return "new name is too long."
            err = self._check_extension(new_name, "new name")
            if err:
                return err

        elif intent == "create_structure":
            if s("target"):
                err = self._check_user_path(s("target"), "target")
                if err:
                    return err
            for field in ("folder_name", "file_name"):
                err = self._check_relative_part(s(field), field)
                if err:
                    return err

        elif intent == "select_search_result":
            # Picking one of the numbered candidates. The final delete/move
            # checks still run on the chosen path; here we only bound inputs.
            chosen = s("selected_path")
            if chosen:
                ok, _ = self._inside_home(chosen)
                if not ok:
                    return "selected path must be inside your Home folder."
            raw = item.get("selection")
            if raw is not None:
                if isinstance(raw, bool):
                    return "invalid selection."
                try:
                    if not 1 <= int(raw) <= 1000:
                        return "invalid selection."
                except (TypeError, ValueError):
                    return "invalid selection."

        elif intent in ("open_local_file", "list_directory"):
            value = s("target")
            if value and self._looks_like_path(value):
                ok, _ = self._inside_home(value)
                if not ok:
                    return "path must be inside your Home folder."

        elif intent in ("open_website", "search_video", "play_video"):
            for field in ("target", "url"):
                if self._BAD_URL_SCHEME.match(s(field)):
                    return "this kind of link is not allowed."

        elif intent == "open_application":
            if not self.ALLOW_TERMINALS:
                for field in ("target", "application"):
                    if self._is_terminal_app(s(field)):
                        return "opening a terminal or shell is not allowed."

        elif intent in ("type_text", "type_into_element"):
            text = s("text")
            for pattern in self._DANGEROUS_TEXT:
                if pattern.search(text):
                    return "this text looks like a dangerous shell command."

        elif intent == "set_volume":
            raw = item.get("value")
            if isinstance(raw, bool):
                return "invalid volume value."
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return "invalid volume value."
            if not math.isfinite(value) or not 0 <= value <= 100:
                return "volume must be between 0 and 100."

        elif intent in ("increase_volume", "decrease_volume", "scroll"):
            default = 5 if "volume" in intent else 3
            raw = item.get("amount", default)
            if isinstance(raw, bool):
                return "invalid amount."
            try:
                amount = int(raw)
            except (TypeError, ValueError):
                return "invalid amount."
            if not 1 <= amount <= 30:
                return "amount must be between 1 and 30."

        return None

    def _is_terminal_app(self, name):
        if not name:
            return False
        norm = re.sub(r"[\s\-_.]+", "", name.casefold())
        if norm in self._SHELL_EXACT:
            return True
        return any(sub in norm for sub in self._TERMINAL_SUBSTRINGS)

    # ------------------------------------------------------------------
    # final checks, called by the executor on the REAL resolved path
    # ------------------------------------------------------------------
    def validate_delete_target(self, path):
        """Re-check the final resolved path immediately before deletion."""
        allowed, resolved = self._inside_home(path, must_exist=True)
        if not allowed:
            return False, None, "Deletion is limited to items inside your Home folder."
        if self._is_hidden(resolved):
            return False, None, "Hidden or system items cannot be deleted."
        if self._is_protected(resolved):
            return False, None, "This folder is protected and cannot be deleted."
        return True, resolved, "Delete target is allowed."

    def validate_move_target(self, source, destination):
        """Optional final check for moves: (ok, src, dst, message)."""
        ok, src = self._inside_home(source, must_exist=True)
        if not ok:
            return False, None, None, "Source must be inside your Home folder."
        ok, dst = self._inside_home(destination, must_exist=True)
        if not ok:
            return False, None, None, "Destination must be inside your Home folder."
        if self._is_hidden(src) or self._is_hidden(dst):
            return False, None, None, "Hidden or system locations are not allowed."
        if self._is_protected(src):
            return False, None, None, "This folder is protected and cannot be moved."
        if not dst.is_dir():
            return False, None, None, "Destination must be an existing folder."
        if src == dst:
            return False, None, None, "Source and destination are the same."
        if src.is_dir():
            try:
                dst.relative_to(src)
                return False, None, None, "Cannot move a folder into itself."
            except ValueError:
                pass
        return True, src, dst, "Move target is allowed."

    def validate_write_target(self, path, overwrite=False):
        """Optional final check before creating a file: (ok, resolved, message).

        Refuses hidden locations, risky extensions, and (by default)
        silently overwriting an existing file.
        """
        ok, resolved = self._inside_home(path)
        if not ok:
            return False, None, "Files can only be created inside your Home folder."
        if self._is_hidden(resolved):
            return False, None, "Creating files in hidden/system locations is not allowed."
        err = self._check_extension(resolved.name, "file")
        if err:
            return False, None, err
        if not overwrite and (resolved.exists() or resolved.is_symlink()):
            return False, None, "A file with this name already exists."
        return True, resolved, "Write target is allowed."


# ----------------------------------------------------------------------
# quick self-test:  python security.py
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "Documents").mkdir()
        (home / "Documents" / "a.txt").write_text("x")
        sm = SecurityManager(home)

        def case(label, data, expect):
            ok, msg = sm.validate_actions(data)
            status = "PASS" if ok == expect else "FAIL"
            print(f"[{status}] {label}: {msg}")

        case("open app", {"intent": "open_application", "target": "firefox"}, True)
        case("terminal allowed", {"intent": "open_application", "target": "Gnome Terminal"}, True)
        case("arabic terminal allowed", {"intent": "open_application", "target": "تيرمنال"}, True)
        locked = SecurityManager(home, allow_terminals=False)
        print("[PASS]" if not locked.validate_actions(
            {"intent": "open_application", "target": "terminal"})[0] else "[FAIL]",
            "terminal blocked when allow_terminals=False")
        case("choose number 2", {"intent": "select_search_result", "selection": 2}, True)
        case("choose by path", {"intent": "select_search_result",
                                "selected_path": str(home / "Projects" / "x")}, True)
        case("choose outside home", {"intent": "select_search_result",
                                     "selected_path": "/etc"}, False)
        case("rename allowed", {"intent": "rename_item", "target": "a.txt", "new_name": "b.txt"}, True)
        case("confirm allowed", {"intent": "confirm_action", "action": "confirm"}, True)
        case("move by spoken name", {"intent": "move_item", "source_path": "report",
                                     "destination_path": "Documents"}, True)
        case("move outside home", {"intent": "move_item", "source_path": "/etc/passwd",
                                   "destination_path": "Documents"}, False)
        case("delete by name", {"intent": "delete_item", "file_name": "a.txt"}, True)
        case("delete via file_name trick", {"intent": "delete_item", "target": "a.txt",
                                            "file_name": "/etc/passwd"}, False)
        case("delete protected by path", {"intent": "delete_item", "target": str(home / "Documents")}, False)
        case("delete hidden", {"intent": "delete_item", "target": ".ssh"}, False)
        case("two deletes", {"actions": [{"intent": "delete_item", "target": "a"},
                                         {"intent": "delete_item", "target": "b"}]}, True)
        case("five deletes", {"actions": [{"intent": "delete_item", "target": str(i)}
                                          for i in range(5)]}, True)
        case("six deletes", {"actions": [{"intent": "delete_item", "target": str(i)}
                                         for i in range(6)]}, True)
        case("twenty deletes", {"actions": [{"intent": "delete_item", "target": str(i)}
                                            for i in range(20)]}, True)
        case("sixty deletes", {"actions": [{"intent": "delete_item", "target": str(i)}
                                           for i in range(60)]}, True)
        (home / "Projects" / "downloads").mkdir(parents=True)
        (home / "Downloads").mkdir()
        case("delete user folder named downloads", {"intent": "delete_item",
                                                    "folder_name": "downloads"}, True)
        print("[PASS]" if sm.validate_delete_target(home / "Projects" / "downloads")[0]
              else "[FAIL]", "final check allows Projects/downloads")
        print("[PASS]" if not sm.validate_delete_target(home / "Downloads")[0]
              else "[FAIL]", "final check still blocks real ~/Downloads")
        case("create bashrc", {"intent": "create_structure", "file_name": ".bashrc"}, False)
        case("create autostart", {"intent": "create_structure",
                                  "folder_name": "x", "file_name": "evil.desktop"}, False)
        case("create traversal", {"intent": "create_structure", "folder_name": "../x"}, False)
        case("create normal", {"intent": "create_structure", "folder_name": "Notes",
                               "file_name": "todo.txt", "content": "hi"}, True)
        case("js url", {"intent": "open_website", "target": "javascript:alert(1)"}, False)
        case("normal url", {"intent": "open_website", "target": "https://example.com"}, True)
        case("rm -rf typed", {"intent": "type_text", "text": "rm -rf ~"}, False)
        case("normal typing", {"intent": "type_text", "text": "hello world"}, True)
        case("volume 150", {"intent": "set_volume", "value": 150}, False)
        case("volume nan", {"intent": "set_volume", "value": "nan"}, False)
        case("6 actions", {"actions": [{"intent": "mute"}] * 6}, True)
        case("intent case", {"intent": " MUTE "}, True)

        print(sm.validate_delete_target(home / "Documents" / "a.txt"))
        print(sm.validate_delete_target(home / "Documents"))
        print(sm.validate_write_target(home / "Documents" / "a.txt"))
        print(sm.validate_write_target(home / "Documents" / "new.txt"))
