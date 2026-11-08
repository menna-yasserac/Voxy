"""Security checks for Voxy actions.

Call validate_action() before performing any side effect.
"""
import re

ALLOWED_INTENTS = {
    "open_app",
    "open_browser",
    "open_terminal",
    "search_web",
    "search_youtube",
    "create_folder",
    "screenshot",
}

ALLOWED_APPS = {
    "facebook",
    "youtube",
    "google",
    "instagram",
    "whatsapp",
}

MAX_QUERY_LENGTH = 160
MAX_FOLDER_LENGTH = 48

FOLDER_PATTERN = re.compile(r"^[A-Za-z0-9_\-\u0600-\u06FF ]+$")


def validate_action(action):
    """Return (allowed, reason); reject malformed or unsupported actions."""
    if not isinstance(action, dict):
        return False, "Invalid command data."

    intent = action.get("intent")

    if intent not in ALLOWED_INTENTS:
        return False, "This command is not allowed."

    if intent == "open_app":
        target = action.get("target")
        if not isinstance(target, str) or target not in ALLOWED_APPS:
            return False, "Unsupported application."
        return True, "Allowed"

    if intent in {"search_web", "search_youtube"}:
        query = action.get("query")
        if not isinstance(query, str):
            return False, "Search text must be text."

        query = query.strip()
        if not query or len(query) > MAX_QUERY_LENGTH:
            return False, "Search text is empty or too long."

        if any(ord(ch) < 32 for ch in query):
            return False, "Search text contains invalid characters."

        return True, "Allowed"

    if intent == "create_folder":
        name = action.get("folder_name")
        if not isinstance(name, str):
            return False, "Folder name must be text."

        name = name.strip()
        if (
            not name
            or name in {".", ".."}
            or len(name) > MAX_FOLDER_LENGTH
            or not FOLDER_PATTERN.fullmatch(name)
            or "/" in name
            or "\\" in name
            or ".." in name
        ):
            return False, "Invalid folder name."

        return True, "Allowed"

    # These are fixed actions with no user-supplied command string.
    # app_AI.py requires confirmation for terminal and screenshot actions.
    return True, "Allowed"
