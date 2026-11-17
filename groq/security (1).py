

from pathlib import Path


class SecurityManager:
    # Keep this list aligned with the handlers in LinuxExecutor.execute_one.
    ALLOWED_INTENTS = {
        "open_application", "close_application", "open_website",
        "search_web", "search_video", "play_video", "open_local_file",
        "list_directory", "click", "click_element", "type_text",
        "type_into_element", "list_ui_elements", "scroll", "go_back",
        "go_forward", "go_home", "increase_volume", "decrease_volume",
        "set_volume", "mute", "unmute", "create_structure",
        "delete_item", "move_item", "conversational_response",
    }

    MAX_ACTIONS = 5
    MAX_TEXT_LENGTH = 5000

    def __init__(self, home=None):
        self.home = Path(home or Path.home()).expanduser().resolve()

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

    def validate_actions(self, command_data):
        """Validate the whole AI response before any action is executed."""
        if not isinstance(command_data, dict):
            return False, "Security blocked the request: invalid command data."

        actions = command_data.get("actions")
        if not isinstance(actions, list) or not actions:
            actions = [command_data]

        if len(actions) > self.MAX_ACTIONS:
            return False, f"Security blocked the request: at most {self.MAX_ACTIONS} actions are allowed at once."

        for index, item in enumerate(actions, start=1):
            if not isinstance(item, dict):
                return False, f"Security blocked action {index}: invalid action format."

            intent = str(item.get("intent") or "").strip().lower()
            if intent not in self.ALLOWED_INTENTS:
                return False, f"Security blocked action {index}: unsupported operation."

            # Bound untrusted text fields to avoid oversized payloads.
            for field in ("target", "application", "query", "text", "content",
                          "folder_name", "file_name", "source_path",
                          "destination_path", "response_text"):
                value = item.get(field)
                if value is not None and (not isinstance(value, str) or len(value) > self.MAX_TEXT_LENGTH):
                    return False, f"Security blocked action {index}: invalid or oversized {field}."

            if intent == "delete_item":
                target = item.get("target") or item.get("application")
                if not target:
                    return False, "Security blocked deletion: target is missing."
                allowed, _ = self._inside_home(target)
                if not allowed:
                    return False, "Security blocked deletion: only items inside your Home folder can be deleted."

            if intent == "move_item":
                for field in ("source_path", "destination_path"):
                    if not item.get(field):
                        return False, "Security blocked move: source and destination are required."
                    allowed, _ = self._inside_home(item[field], must_exist=True)
                    if not allowed:
                        return False, "Security blocked move: both paths must be inside your Home folder."

            if intent == "create_structure":
                target = item.get("target")
                if target:
                    allowed, _ = self._inside_home(target)
                    if not allowed:
                        return False, "Security blocked creation: target must be inside your Home folder."

            if intent == "set_volume":
                try:
                    value = float(item.get("value"))
                except (TypeError, ValueError):
                    return False, "Security blocked volume change: invalid value."
                if not 0 <= value <= 100:
                    return False, "Security blocked volume change: value must be between 0 and 100."

            if intent in ("increase_volume", "decrease_volume", "scroll"):
                try:
                    amount = int(item.get("amount", 5 if "volume" in intent else 3))
                except (TypeError, ValueError):
                    return False, f"Security blocked action {index}: invalid amount."
                if not 1 <= amount <= 30:
                    return False, f"Security blocked action {index}: amount must be between 1 and 30."

        return True, "Security validation passed."

    def validate_delete_target(self, path):
        """Re-check the final resolved path immediately before deletion.

        This second check is important because Voxy's file search can resolve a
        spoken filename to a different location than the user typed.
        """
        allowed, resolved = self._inside_home(path, must_exist=True)
        if not allowed:
            return False, None, "Deletion is limited to items inside your Home folder."
        return True, resolved, "Delete target is allowed."