import os
import re
import json
from groq import Groq

from audio_service_AI import clean_text, detect_language


SYSTEM_PROMPT = """
You are Voxy, the natural-language command understanding engine
of an Ubuntu Linux desktop voice assistant.

Understand the user's meaning, not exact keywords.

LANGUAGES:
- Egyptian Arabic and Modern Standard Arabic.
- English and mixed Arabic-English.
- Different accents, informal grammar and reasonable STT mistakes.
- When asking a clarification question (needs_clarification=true), reply in the
  same language as the user (Egyptian/Modern Arabic for Arabic input, English for English input).

TARGETS:
Extract the requested operation and its target separately.
Targets are dynamic and must not be restricted to predefined names.
Preserve Arabic names exactly when they are actual file/folder names.
For Arabic-transcribed English words, also populate english_phonetic.
Examples:
"فيسبوك" -> target="فيسبوك", english_phonetic="facebook"
"ترمنال" -> target="ترمنال", english_phonetic="terminal"
"بي دي اف" -> target="بي دي اف", english_phonetic="PDF"

For spoken symbols, preserve the spoken name in target and also
populate symbol_variant with the symbol form.
Examples:
"my underscore file" -> symbol_variant="my_file"
"نجمة" -> symbol_variant="*"
"project dash one" -> symbol_variant="project-one"

SUPPORTED INTENTS:
open_application
close_application
open_website
search_web
search_video
play_video
open_local_file
select_search_result
list_directory
click
click_element
type_text
type_into_element
list_ui_elements
scroll
go_back
go_forward
go_home
increase_volume
decrease_volume
set_volume
mute
unmute
create_structure
delete_item
move_item
rename_item
confirm_action
conversational_response
unknown

OPENING AND CLOSING:
- Desktop programs -> open_application.
- Local files and local folders (unless explicitly asking to list contents) -> open_local_file.
- Websites and online services -> open_website.
- Closing an application or window -> close_application.
- Never guess an unclear target.

SEARCH AND VIDEO:
- General search -> search_web.
- Video search -> search_video, platform="youtube".
- Playing a video -> play_video.
- Selecting a previous search result must not trigger a new search.
- Use previous video search context when available.
- If the requested video cannot be identified, ask a clarification question.

SCREEN INTERACTION:
- Named visible element -> click_element, target is its visible label.
- "click here" / "دوس هنا" / "اضغط هنا" -> click_element, target="here".
- Right click -> action="right_click".
- Double click -> action="double_click".
- Explicit coordinates -> click, using only coordinates supplied by the user.
- Never invent coordinates.

TYPING:
- Text into the currently focused field -> type_text (text = exact text to type).
- Named input field -> type_into_element (text = exact text to type, target or element_name = field label).
- Preserve the exact text requested.

SCROLLING:
- Scroll -> scroll.
- action="up" or "down".
- Default amount=3.
- Do not confuse scrolling with browser back/forward navigation.

VOLUME:
- increase_volume / decrease_volume: default amount=5.
- set_volume: value is the requested final percentage (0-100).
- mute / unmute for audio muting.

FILES AND FOLDERS:
- list_directory: show folder contents.
- open_local_file: open an existing file or folder.
- create_structure: only when explicitly creating a new file/folder (supports folder_name, file_name, content, target).
- delete_item: delete an existing item.
- move_item: move an existing item (source_path and destination_path).
- rename_item: rename an existing item (source_path and new_name).

For file operations:
- Preserve exact file and folder names.
- Never invent paths or filenames.
- Use parent_folder when the user specifies a parent.
- If an essential path or name is missing, ask one short clarification question.
- Never guess between similar files or folders.

Normalize common spoken Linux folder names:
"داول لوت", "داونلودز", "داون لود" -> "Downloads"
"ديسكتوب" -> "Desktop"
"دوكيومنتس" -> "Documents"
"هوم", "الهوم" -> "Home"

PENDING CONFIRMATION:
The context may contain has_pending_confirmation.
If true:
- Approval -> intent="confirm_action", action="confirm".
- Refusal/cancellation -> intent="confirm_action", action="cancel".
Do not interpret an unrelated answer as approval.

PENDING FILE SELECTION:
The context may contain:
has_pending_file_selection
pending_file_candidates
pending_operation

If true:
- Identify the selected candidate by number, position, parent folder,
  capitalization, symbol, extension or file type.
- selected_path must be copied exactly from pending_file_candidates.
- selection is a 1-based index when identifiable.
- If ambiguous, ask a short clarification question.
- If cancelled, use intent="select_search_result", action="cancel".

MULTIPLE ACTIONS:
If the user requests multiple operations, return them in actions
in the exact requested order.
For one operation, actions must be [].
Do not omit or duplicate operations.

CONTEXT:
Use previous context only when it clearly identifies references
such as "it", "this", "that", "اقفله", "افتحه".
Never invent previous searches, applications or screen elements.
Persisted context from the execution engine (like a recently clicked element or opened file)
should be utilized to resolve referring terms.

CLARIFICATION:
If the intention or essential target is unclear, ask one short question.
Greetings and general questions -> conversational_response.
Use unknown only when no reliable intention can be identified.

SAFETY:
You only interpret commands and generate JSON.
Never generate shell commands or Python code.
Never execute operations.
Never claim an operation succeeded.
Never invent file paths or coordinates.
The execution engine is responsible for security and confirmation.

Return valid JSON only, using this structure:

{
  "intent": "unknown",
  "target": null,
  "parent_folder": null,
  "selected_path": null,
  "english_phonetic": null,
  "symbol_variant": null,
  "application": null,
  "platform": null,
  "query": null,
  "selection": null,
  "action": null,
  "amount": null,
  "value": null,
  "text": null,
  "x": null,
  "y": null,
  "folder_name": null,
  "file_name": null,
  "content": null,
  "source_path": null,
  "destination_path": null,
  "new_name": null,
  "response_text": null,
  "confidence": 0.0,
  "needs_clarification": false,
  "actions": []
}

For each item inside actions, use the same action fields,
with irrelevant fields set to null and actions=[].

confidence must be between 0.0 and 1.0.
"""


class CommandUnderstanding:

    _CONFIRM_WORDS = {
        "yes", "yeah", "yep", "sure", "confirm", "ok", "okay",
        "approve", "do it", "go ahead",
        "آه", "اه", "ايوه", "أيوه", "موافقة", "موافق",
        "تمام", "اكيد", "أكيد", "ماشي", "نفذ",
        "امسحه", "امسحيه", "دوس", "اضغط"
    }

    _CANCEL_WORDS = {
        "no", "nope", "cancel", "stop", "abort", "nevermind",
        "لا", "لأ", "الغي", "إلغاء", "الغاء",
        "بلاش", "خلاص", "مش عايز", "مش عايزة"
    }

    ALLOWED_INTENTS = {
        "open_application", "close_application",
        "open_website", "search_web", "search_video",
        "play_video", "open_local_file", "select_search_result",
        "list_directory", "click", "click_element",
        "type_text", "type_into_element", "list_ui_elements",
        "scroll", "go_back", "go_forward", "go_home",
        "increase_volume", "decrease_volume", "set_volume",
        "mute", "unmute", "create_structure", "delete_item",
        "move_item", "rename_item", "confirm_action",
        "conversational_response", "unknown"
    }

    FILE_INTENTS = {
        "create_structure", "delete_item", "open_local_file",
        "list_directory", "move_item", "rename_item"
    }

    def __init__(
        self,
        api_key=None,
        model="openai/gpt-oss-120b",
        debug=False
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")

        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        self.client = Groq(api_key=self.api_key)
        self.model = model
        self.debug = bool(debug)

        self.conversation_context = {
            "last_intent": None,
            "last_target": None,
            "last_query": None,
            "last_platform": None,
            "last_video_search_query": None,
            "last_application": None,
            "last_website": None,
            "last_screen_element": None,
            "has_pending_file_selection": False,
            "pending_file_candidates": [],
            "pending_operation": None,
            "pending_extra": {},
            "has_pending_confirmation": False,
            "pending_confirmation_question": None,
            "persisted_execution_target": None,
        }

    def set_pending_file_selection(
        self, pending, candidates=None, operation=None, extra=None
    ):
        self.conversation_context["has_pending_file_selection"] = bool(
            pending
        )

        if pending and candidates:
            self.conversation_context["pending_file_candidates"] = [
                str(candidate) for candidate in candidates
            ]
            self.conversation_context["pending_operation"] = operation
            self.conversation_context["pending_extra"] = extra or {}

        elif not pending:
            self.conversation_context["pending_file_candidates"] = []
            self.conversation_context["pending_operation"] = None
            self.conversation_context["pending_extra"] = {}

    def set_pending_confirmation(self, pending, question=None):
        self.conversation_context["has_pending_confirmation"] = bool(
            pending
        )
        self.conversation_context["pending_confirmation_question"] = (
            str(question) if pending and question else None
        )

    def sync_persisted_context(self, executor_instance):
        if executor_instance and hasattr(executor_instance, "get_persisted_target"):
            self.conversation_context["persisted_execution_target"] = executor_instance.get_persisted_target()

    def _empty_action(self):
        return {
            "intent": "unknown",
            "target": None,
            "parent_folder": None,
            "selected_path": None,
            "english_phonetic": None,
            "symbol_variant": None,
            "application": None,
            "platform": None,
            "query": None,
            "selection": None,
            "action": None,
            "amount": None,
            "value": None,
            "text": None,
            "x": None,
            "y": None,
            "folder_name": None,
            "file_name": None,
            "content": None,
            "source_path": None,
            "destination_path": None,
            "new_name": None,
            "response_text": None,
            "confidence": 0.0,
            "needs_clarification": False,
            "actions": []
        }

    def _clarification(self, message):
        result = self._empty_action()
        result["intent"] = "unknown"
        result["needs_clarification"] = True
        result["response_text"] = message
        result["confidence"] = 0.0
        self._prepare_voice_metadata(result, message)
        return result

    def _try_fast_path(self, raw_command):
        text = str(raw_command or "").strip()
        cleaned = re.sub(r"[.!؟?،,]+$", "", text).strip().casefold()

        if not cleaned:
            return None

        words = cleaned.split()

        if self.conversation_context.get("has_pending_confirmation") and len(words) <= 4:
            tokens = set(words)

            if cleaned in self._CANCEL_WORDS or (tokens & self._CANCEL_WORDS):
                result = self._empty_action()
                result.update({
                    "intent": "confirm_action",
                    "action": "cancel",
                    "confidence": 1.0
                })
                return result

            if cleaned in self._CONFIRM_WORDS or (tokens & self._CONFIRM_WORDS):
                result = self._empty_action()
                result.update({
                    "intent": "confirm_action",
                    "action": "confirm",
                    "confidence": 1.0
                })
                return result

        fast_map = [
            (
                r"^(increase volume|volume up|علي الصوت|عليه الصوت|زود الصوت|ارفع الصوت)$",
                {"intent": "increase_volume", "amount": 5}
            ),
            (
                r"^(decrease volume|volume down|وطي الصوت|قلل الصوت|اخفض الصوت)$",
                {"intent": "decrease_volume", "amount": 5}
            ),
            (
                r"^(mute|mute volume|اكتم الصوت|كتم الصوت|اسكت)$",
                {"intent": "mute"}
            ),
            (
                r"^(unmute|unmute volume|شغل الصوت|الغي كتم الصوت|فك الكتم)$",
                {"intent": "unmute"}
            ),
            (
                r"^(scroll down|انزل تحت|نزل الصفحة|انزل لتحت)$",
                {"intent": "scroll", "action": "down", "amount": 3}
            ),
            (
                r"^(scroll up|اطلع فوق|طلع الصفحة|اطلع لفوق)$",
                {"intent": "scroll", "action": "up", "amount": 3}
            ),
            (
                r"^(click here|دوس هنا|اضغط هنا)$",
                {"intent": "click_element", "target": "here"}
            ),
            (
                r"^(go back|ارجع|رجوع)$",
                {"intent": "go_back"}
            )
        ]

        for pattern, specification in fast_map:
            if re.fullmatch(pattern, cleaned):
                result = self._empty_action()
                result.update(specification)
                result["confidence"] = 0.99
                return result

        return None

    def understand(self, command):
        if not command or not str(command).strip():
            return self._clarification(
                "I didn't hear a command. Please repeat it."
            )

        command = str(command).strip()

        fast_result = self._try_fast_path(command)

        if fast_result is not None:
            self._validate_action(fast_result)
            self._prepare_voice_metadata(fast_result, command)
            self._update_context(fast_result)
            if self.debug:
                self._print_result("VOXY FAST-PATH UNDERSTANDING", fast_result)
            return fast_result

        context = json.dumps(
            self.conversation_context,
            ensure_ascii=False
        )

        user_prompt = f"""
Previous conversation and execution context:
{context}

New user command:
{command}

Interpret the command based on its meaning and context.
Extract dynamic targets and parameters.
Return the required JSON structure only.
"""

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )

            raw_response = completion.choices[0].message.content

            if not raw_response:
                raise ValueError("The model returned an empty response.")

            result = json.loads(raw_response)

            result = self._normalize_result(result)
            self._restore_name_case(result, command)
            self._apply_video_context(result)
            self._validate_result(result)

            self._prepare_voice_metadata(result, command)
            self._update_context(result)

            if self.debug:
                self._print_result("VOXY UNDERSTANDING", result)
            return result

        except Exception as error:
            if self.debug:
                print("[VOXY UNDERSTANDING ERROR]", error)
            return self._clarification(
                "I couldn't process that command. Please try again."
            )

    def _normalize_action(self, action):
        if not isinstance(action, dict):
            action = {}

        normalized = self._empty_action()
        normalized.update(action)

        if normalized.get("intent") not in self.ALLOWED_INTENTS:
            normalized["intent"] = "unknown"

        intent = normalized.get("intent")

        if intent in ("type_text", "type_into_element"):
            if not normalized.get("text"):
                normalized["text"] = normalized.get("query") or normalized.get("target")

        try:
            confidence = float(normalized.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        normalized["confidence"] = max(0.0, min(1.0, confidence))
        normalized["needs_clarification"] = bool(
            normalized.get("needs_clarification", False)
        )

        normalized["actions"] = []

        return normalized

    def _normalize_result(self, result):
        if not isinstance(result, dict):
            return self._clarification(
                "I couldn't understand that command."
            )

        raw_actions = result.get("actions", [])

        normalized = self._normalize_action(result)

        if not isinstance(raw_actions, list):
            raw_actions = []

        normalized["actions"] = [
            self._normalize_action(action)
            for action in raw_actions
            if isinstance(action, dict)
        ]

        return normalized

    def _restore_name_case(self, result, command):
        original = str(command)

        actions = result.get("actions") or [result]

        fields = (
            "folder_name",
            "file_name",
            "target",
            "parent_folder",
            "source_path",
            "destination_path",
            "new_name",
            "selected_path"
        )

        for action in actions:
            if action.get("intent") not in self.FILE_INTENTS:
                continue

            for field in fields:
                value = action.get(field)

                if not isinstance(value, str) or not value:
                    continue

                index = original.casefold().find(value.casefold())

                if index >= 0:
                    action[field] = original[index:index + len(value)]

    def _validate_action(self, action):
        intent = action.get("intent")
        missing_message = None

        if intent == "open_local_file" and not action.get("target"):
            missing_message = "Which file or folder would you like me to open?"

        elif intent == "list_directory" and not action.get("target"):
            missing_message = "Which folder would you like me to display?"

        elif intent == "delete_item" and not action.get("target"):
            missing_message = "Which file or folder would you like me to delete?"

        elif intent == "create_structure":
            if not action.get("folder_name") and not action.get("file_name"):
                missing_message = "What should I create?"

        elif intent == "move_item":
            if not action.get("source_path") and not action.get("target"):
                missing_message = "Which file or folder should I move?"
            elif not action.get("destination_path"):
                missing_message = "Where should I move it?"

        elif intent == "rename_item":
            if not action.get("source_path") and not action.get("target"):
                missing_message = "Which file or folder should I rename?"
            elif not action.get("new_name"):
                missing_message = "What is the new name?"

        if missing_message:
            action["needs_clarification"] = True
            action["response_text"] = missing_message

        return action

    def _validate_result(self, result):
        actions = result.get("actions") or [result]

        for action in actions:
            self._validate_action(action)

        clarification_action = next(
            (
                action for action in actions
                if action.get("needs_clarification")
            ),
            None
        )

        if clarification_action:
            result["needs_clarification"] = True
            result["response_text"] = (
                clarification_action.get("response_text")
                or "I need a little more information."
            )

        return result

    def _apply_video_context(self, result):
        actions = result.get("actions") or [result]

        previous_search = self.conversation_context.get(
            "last_video_search_query"
        )

        for action in actions:
            if action.get("intent") != "play_video":
                continue

            if action.get("selection") is not None and not action.get("query"):
                if previous_search:
                    action["query"] = previous_search
                    action["platform"] = (
                        action.get("platform") or "youtube"
                    )
                else:
                    action["needs_clarification"] = True
                    action["response_text"] = (
                        "Which video would you like me to play?"
                    )

            elif not action.get("query") and not action.get("target"):
                action["needs_clarification"] = True
                action["response_text"] = (
                    "Which video would you like me to play?"
                )

        if result.get("actions"):
            clarification = next(
                (
                    action for action in result["actions"]
                    if action.get("needs_clarification")
                ),
                None
            )

            if clarification:
                result["needs_clarification"] = True
                result["response_text"] = clarification["response_text"]

    def _prepare_voice_metadata(self, result, command):
        try:
            result["detected_language"] = (
                detect_language(str(command)) or "en"
            )
        except Exception:
            result["detected_language"] = "en"

        response = result.get("response_text")

        try:
            result["spoken_feedback"] = (
                clean_text(response) if response else None
            )
        except Exception:
            result["spoken_feedback"] = response

        for action in result.get("actions", []):
            action_response = action.get("response_text")

            if action_response:
                try:
                    action["spoken_feedback"] = clean_text(action_response)
                except Exception:
                    action["spoken_feedback"] = action_response

    def _update_context(self, result):
        actions = result.get("actions") or [result]

        for action in actions:
            intent = action.get("intent")
            if intent == "unknown" or action.get("needs_clarification"):
                continue

            target = action.get("target")
            query = action.get("query")
            platform = action.get("platform")

            if intent in ("search_video", "search_web"):
                if query and (
                    intent == "search_video"
                    or str(platform or "").lower() in (
                        "youtube", "يوتيوب"
                    )
                ):
                    self.conversation_context[
                        "last_video_search_query"
                    ] = query

            if intent in ("open_application", "close_application"):
                if target:
                    self.conversation_context["last_application"] = target

            if intent == "open_website" and target:
                self.conversation_context["last_website"] = target

            if intent in ("click", "click_element") and target:
                self.conversation_context[
                    "last_screen_element"
                ] = target

            self.conversation_context["last_intent"] = intent

            if target is not None:
                self.conversation_context["last_target"] = target

            if query is not None:
                self.conversation_context["last_query"] = query

            if platform is not None:
                self.conversation_context["last_platform"] = platform

    @staticmethod
    def _print_result(label, result):
        print(f"[{label}]")
        print(json.dumps(result, ensure_ascii=False, indent=2))


_default_engine = None


def understand_command(command, api_key=None, debug=False):
    global _default_engine

    if _default_engine is None:
        _default_engine = CommandUnderstanding(api_key=api_key, debug=debug)

    return _default_engine.understand(command)
