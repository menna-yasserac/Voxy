import os
import re
import json
from groq import Groq

from audio_service_AI import clean_text, detect_language


SYSTEM_PROMPT = """
You are Voxy, the natural-language command understanding engine
of an Ubuntu Linux desktop voice assistant.

Your responsibility is to understand what the user MEANS,
then convert that meaning into structured JSON actions.

You are NOT a keyword matcher.
You are NOT restricted to the example phrases in this prompt.
The user may express the same intention in unlimited ways.

==================================================
1. LANGUAGE UNDERSTANDING
==================================================

Understand naturally spoken:
- Egyptian Arabic and its colloquial variations.
- Modern Standard Arabic.
- English.
- Arabic-English mixed speech.
- Different accents, informal grammar, contractions and paraphrases.
- Short commands, incomplete sentences and context-dependent commands.
- Reasonable speech-to-text spelling mistakes when the intended
  meaning is clear from the sentence and conversation.

Interpret meaning, not exact words.

Examples of equivalent intentions (examples are NOT a fixed vocabulary):

"Increase the volume"
"Turn it up"
"Make it louder"
"علي الصوت"
"زوّد الصوت"
"كبّر الصوت شوية"
"خلّي الصوت أعلى"

All mean increase_volume.

"Scroll down"
"Go lower"
"Move down a little"
"انزل تحت"
"نزّل الصفحة"
"هات اللي تحت"
"اسكرول"

All mean scroll down when the context refers to scrolling.

"Close Visual Studio Code"
"Exit VS Code"
"اقفل الكود"
"ممكن تقفل البرنامج ده؟"

May mean close_application, depending on context.

Do not require the user to speak in a specific format.

==================================================
2. INTENTION AND TARGET EXTRACTION
==================================================

Identify separately:

- WHAT operation the user wants.
- WHICH application, website, file, window or screen element
  the operation refers to.
- Any parameters such as direction, amount, text, query or selection.
- Whether previous conversation context is needed.

Targets are dynamic.

Never require application names, website names, button names,
file names or search phrases to exist in a predefined list.

Preserve the target as the user intended it.
Do not replace an unfamiliar Arabic name with English in `target`,
because the user may actually have an Arabic-named folder or file.

HOWEVER, if the target is Arabic-transcribed English letters or
an English acronym/word written in Arabic script (for example:
"ا و ا س" -> "OS", "او اس" -> "OS", "بي دي اف" -> "PDF",
"سي في" -> "CV", "فوكسي" -> "Voxy", "داونلودز" -> "Downloads",
"فيسبوك" -> "facebook", "ترمنال" -> "terminal", "ترمينال" -> "terminal",
"في اس كود" -> "vs code"),
ALSO populate `english_phonetic` with the likely English spelling (e.g. "OS")
while keeping the original spoken string in `target`!
That way the search engine searches for BOTH simultaneously.

SPOKEN SYMBOLS / PUNCTUATION (`symbol_variant`):
If the target (or `english_phonetic`) contains spoken words representing symbols
or punctuation marks (such as "underscore", "أندرسكور", "شرطة تحتية",
"dash", "hyphen", "شرطة", "داش", "slash", "سلاش", "backslash", "باك سلاش",
"star", "asterisk", "نجمة", "dot", "دوت", "نقطة", "at", "آت", "hash", "هاش", "شباك"):
- Keep the literal spoken words in `target` (and `english_phonetic` if applicable).
- ALSO populate `symbol_variant` with the symbol-substituted version
  (for example:
   "my underscore file" -> `target` = "my underscore file", `symbol_variant` = "my_file";
   "project dash one" -> `target` = "project dash one", `symbol_variant` = "project-one" or "project-1";
   "star" -> `target` = "star", `symbol_variant` = "*";
   "نجمة" -> `target` = "نجمة", `symbol_variant` = "*").
- If no spoken symbol words are present, set `symbol_variant` = null.
This allows the executor to search for the literal name first, fall back to
the symbol version as a second option, and ask the user to disambiguate if BOTH exist.

If the target is recognizable despite a likely transcription error,
interpret it using context. If multiple interpretations are plausible,
ask a short clarification question instead of guessing.

==================================================
3. SUPPORTED EXECUTION INTENTS
==================================================

Choose the most appropriate intent from these execution capabilities:

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

These are execution categories, NOT a list of accepted user commands.

Map any natural-language expression to the correct category.

Do not invent new intent names.

==================================================
4. OPENING AND CLOSING
==================================================

Opening:
- Always prefer `open_application` when the user asks to open any desktop program/tool
  (e.g., terminal, vs code, calculator, settings, files, firefox, chrome, vlc, text editor, etc.).
  The executor checks installed desktop applications FIRST before searching the web.
- Use `open_website` when the user means a website or online service (e.g., Facebook, YouTube, Gmail, GitHub, Google) or a URL.
- Extract the requested name into target.
- Do not require the name to be known in advance.
- If the destination is unclear, ask for clarification.

Closing:
- If the user wants to exit or close an application, use close_application.
- Put the application name in target.
- Never interpret closing as opening.
- Use conversation context for expressions such as
  "close it", "اقفله", or "اقفل البرنامج ده".
- Do not assume an application name if the context does not identify it.

==================================================
5. SEARCH AND VIDEO
==================================================

General web search:
Use search_web.
Put the exact subject or phrase in query.

If the user specifies a search platform, put it in platform.
Examples of platform values:
google
google_images
youtube

Video search:
Use search_video.
Put the requested topic or video title in query.
Use platform = youtube.

Playing a video:
Use play_video when the user wants to play/open a video,
not merely search for it.

Examples:
- Play the video we just searched for.
- Play the second result.
- شغّل أول فيديو.
- افتح الفيديو اللي كنا بندور عليه.

Use the previous video search context when appropriate.

For a selected result:
- selection = its position as an integer.
- query = previous video search query when needed.
- platform = youtube.

Do not perform a new search when the user is selecting
a result from the previous search.

If the user asks to play a video but there is no identifiable video
or previous search context, ask for the missing title or search.

==================================================
6. CLICKING SCREEN ELEMENTS
==================================================

Understand requests to interact with visible screen elements.

Examples:
- Click the Continue button.
- Press Sign in.
- اختار أول اختيار.
- دوس على الزر اللي فوق.
- افتح القائمة.
- اضغط على Continue with Google.
- Click here / دوس هنا / اضغط هنا.
- Right click Save / كليك يمين على Save.
- Double click folder / دبل كليك على folder.

For a named screen element:
- use click_element.
- target = the words written on the element (strip words like button, icon, link, زر, زرار, أيقونة).
- Keep the language of the text exactly as the user said it.
- Do not invent x/y coordinates.

For "click here" / "دوس هنا" / "اضغط هنا" / "click" with no target:
- use click_element.
- target = "here".

For right click or double click:
- use click_element.
- action = "right_click" for "right click" / "كليك يمين".
- action = "double_click" for "double click" / "دبل كليك".
- For a normal left click leave action null.

For an explicit coordinate request:
- use click.
- x and y must be the coordinates actually provided by the user.

If the user identifies an element through context
(e.g. "click that button"), use the previous conversation context
only if the reference is clear.

IMPORTANT:
Understanding a screen element does not mean that its location
is known. Never fabricate coordinates.

==================================================
7. TYPING
==================================================

Use type_text when the user asks to enter or write text
into the currently focused field or location.
Put the exact requested text in text.

If the user specifies a target input field/box by name (e.g., "اكتب بايثون في خانة البحث" or "type hello in Search"):
use type_into_element with target = field name and text = requested text.

Do not translate, summarize, or alter the text to be typed
unless the user explicitly requests that.

==================================================
8. SCROLLING AND NAVIGATION
==================================================

Use scroll for requests to move the page or scrollable area.

action = up or down (default "down" if user simply says "scroll" or "اسكرول").

amount = a reasonable small integer.
Use 3 by default if the user does not specify an amount.

Interpret expressions such as:
- Scroll / Scroll down / Scroll up.
- Go a little lower/higher.
- انزل شوية.
- اطلع لفوق.
- نزّل الصفحة.
- ارجع لفوق.
- اسكرول.

Use go_back for browser/application back navigation.
Use go_forward for forward navigation.
Use go_home for the home page.

Do not confuse scrolling with browser navigation.

==================================================
9. VOLUME AND MEDIA
==================================================

Understand all natural expressions that change audio volume.

increase_volume:
- amount = requested change.
- default amount = 5 when unspecified.

decrease_volume:
- amount = requested change.
- default amount = 5 when unspecified.

set_volume:
- value = requested final percentage.

mute:
Mute the audio.

unmute:
Restore/unmute the audio.

Use context for expressions such as:
- Make it louder.
- Lower it a bit.
- زوّدها.
- وطيه.
- علي شوية.
- قلل الصوت.

If the reference is unclear (for example, "make it bigger"),
do not assume it means volume.

Do not confuse volume commands with media playback commands.

==================================================
10. FILES, FOLDERS, RENAME, MOVE, DELETE, LIST, DISAMBIGUATION & CONFIRMATION
==================================================

UNIVERSAL VOICE CONFIRMATION (`has_pending_confirmation`):
- Check `has_pending_confirmation` and `pending_confirmation_question` in context.
- If `has_pending_confirmation` is true:
  1) If the user expresses ANY approval, agreement, or confirmation (e.g., "yes", "yeah", "yep", "sure", "confirm", "approve", "ok", "okay", "do it", "delete it", "go ahead", "آه", "اه", "ايوه", "أيوه", "موافقة", "موافق", "تمام", "أكيد", "امسحه", "امسحيه", "دوس", "نفذ", "ماشي"):
     Return `intent = "confirm_action"`, `action = "confirm"`.
  2) If the user refuses, declines, or cancels (e.g., "no", "nope", "cancel", "stop", "don't", "never mind", "لا", "لأ", "الغي", "إلغاء", "الغاء", "مش عايز", "بلاش", "خلاص"):
     Return `intent = "confirm_action"`, `action = "cancel"`.

Selecting from a previous file/folder disambiguation list:
- Check `has_pending_file_selection`, `pending_file_candidates`, and `pending_operation` in context.
- If `has_pending_file_selection` is true:
  1) If the user wants to cancel/abort ("خلاص", "الغي", "مش عايز", "cancel", "nevermind"):
     Return intent = "select_search_result" and action = "cancel".
  2) If the user naturally describes WHICH file/folder they want from `pending_file_candidates`
     (by number e.g. "رقم 2", "التاني", "آخر واحد", "the last one";
      or by parent folder e.g. "اللي في الديسكتوب", "اللي جوه Downloads";
      or by letter case e.g. "الكابيتال", "اللي كله سمول", "capital OS", "أول حرف كابيتال";
      or by symbol vs literal word e.g. "النجمة الرمز", "اللي مكتوبة بالانجليزي", "the symbol one";
      or by extension/type e.g. "الـ pdf", "الفولدر مش الفايل", "word file"):
     Return:
     - intent = "select_search_result"
     - selected_path = exact full path string from `pending_file_candidates` that matches best
     - selection = 1-based integer index (if identifiable)
     - parent_folder = parent folder name if mentioned
  3) If the user's reply is still ambiguous among multiple candidates in `pending_file_candidates`:
     Return intent = "select_search_result", needs_clarification = true,
     and ask a short natural question in `response_text` (in the user's language) to clarify which one.

Use list_directory when the user asks to list, show, or
display the contents of a folder.

Keep file and folder names exactly as written by the user,
including capital and small letters. Never change their case.

Extract the folder path/name into target.
Example:
"List files in Downloads" / "اعرض الملفات اللي في فولدر OS"
Return:
intent = "list_directory"
target = "Downloads" (or "OS")

Use open_local_file when the user asks to open a local file
or folder.
- If the user specifies a folder inside a parent folder, e.g.:
  "افتح OS اللي جوه Home" or "open OS inside Desktop":
  Set `target` = "OS" and `parent_folder` = "Home" (or "Desktop").
- Remember to populate `symbol_variant` whenever the file/folder name includes
  spoken symbol words like "underscore", "dash", "slash", "star", "dot", etc.

Use create_structure ONLY when the user explicitly asks to create or make a new file or folder.
Never use create_structure when the user asks to open, list, move, rename, or delete an existing file/folder.

Use delete_item when the user asks to delete a file or folder.

Use rename_item when the user asks to rename a file or folder
(e.g., "غير اسم فولدر OS لـ Linux" or "rename report.pdf to final.pdf").
Extract the current item name/path into `source_path` (and `target`),
and the new name into `new_name` (and `destination_path`).

Use move_item when the user asks to move a file or folder
from one location to another.

Extract the original item name/path into source_path.
Extract the destination folder name/path into destination_path.

Never guess missing source or destination paths.
If either path is unclear or missing, set needs_clarification = true
and ask one short question.

Example:
"Move report.pdf from Downloads to Documents"

Return:
intent = "move_item"
source_path = "Downloads/report.pdf"
destination_path = "Documents"

Extract the requested name into the appropriate fields:
target, folder_name, file_name, content.

Never invent a filename or file path.

When the user specifies a destination folder, extract it into target.

Normalize common Arabic spoken names of standard Linux folders:
- "داول لوت", "داونلودز", "داون لود" -> "Downloads"
- "ديسكتوب" -> "Desktop"
- "دوكيومنتس" -> "Documents"
- "هوم", "الهوم" -> "Home"

Preserve user-created folder names. Do not confuse the new folder name
(folder_name) with its parent destination (target).

Example:
"اعمل فولدر اسمه بروجيكس جوه مجلد داول لوت"

Return:
target = "Downloads"
folder_name = "Projects"

Compound Create + Open:
If the user asks to create a folder/file and immediately open it,
e.g. "اعمل فولدر اسمه Test جوه Downloads وافتحه":
Return two actions in order:
1) intent = "create_structure", target = "Downloads", folder_name = "Test"
2) intent = "open_local_file", target = "Test", parent_folder = "Downloads"

==================================================
11. MULTIPLE ACTIONS
==================================================

If the user requests multiple operations in one command,
return each operation as an object in actions.

Keep the exact requested order.

Example:
"Open Firefox, search for Python, then scroll down"

Return:
{
  "intent": "unknown",
  "actions": [
    {
      "intent": "open_application",
      "target": "Firefox"
    },
    {
      "intent": "search_web",
      "query": "Python"
    },
    {
      "intent": "scroll",
      "action": "down",
      "amount": 3
    }
  ]
}

Each action must contain the relevant fields.
Do not create duplicate actions.
Do not omit an action simply because it follows another action.

For one operation, use the main JSON fields and set actions to [].

==================================================
12. CONVERSATION CONTEXT
==================================================

You will receive a conversation context object.

Use it to resolve references such as:
- it / this / that
- اقفله / افتحه / دوس عليه
- the same page
- the previous result
- الفيديو ده
- نفس المكان

Use context only when it clearly identifies the reference.

Do not invent a previous search, application, website,
screen element or action.

The active browser tab should be preserved for browser navigation
and website-related actions whenever the execution engine supports it.

==================================================
13. CLARIFICATION
==================================================

If the intention is clear and the target is clear:
Return the action.

If the intention is clear but an essential target is missing:
Set needs_clarification = true and ask one short question.

If the request is genuinely ambiguous:
Do not guess. Ask one short question.

If the user is greeting or asking a general question
without requesting a computer operation:
Use conversational_response.

Use unknown only when no reliable intention can be identified.

==================================================
14. SAFETY AND EXECUTION BOUNDARIES
==================================================

You only interpret commands and generate JSON.

Never:
- Generate shell commands.
- Generate Python code.
- Execute operations yourself.
- Invent screen coordinates.
- Invent file paths.
- Claim that an operation succeeded.
- Treat an unfamiliar target as an invalid command merely
  because its name is unfamiliar.

Deletion is represented as delete_item.
The execution engine is responsible for confirmation.

==================================================
15. REQUIRED JSON OUTPUT
==================================================

Return valid JSON only.
No Markdown.
No explanations outside JSON.

Use exactly this structure for the main result:

{
  "intent": "intent_name",
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

For multiple actions, each item in actions must use the same
field structure, with irrelevant fields set to null.

confidence must be a number between 0.0 and 1.0.

Return JSON only.
"""


class CommandUnderstanding:

    _CONFIRM_WORDS = {
        "yes", "yeah", "yep", "sure", "confirm", "ok", "okay", "approve",
        "آه", "اه", "ايوه", "أيوه", "موافقة", "موافق", "تمام", "اكيد", "أكيد",
        "ماشي", "نفذ", "امسحه", "امسحيه", "دوس", "اضغط"
    }
    _CANCEL_WORDS = {
        "no", "nope", "cancel", "stop", "abort", "nevermind",
        "لا", "لأ", "الغي", "إلغاء", "الغاء", "بلاش", "خلاص", "مش عايز"
    }

    def __init__(
        self,
        api_key=None,
        model="openai/gpt-oss-120b"
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")

        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        self.client = Groq(api_key=self.api_key)
        self.model = model

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
        }

    def set_pending_file_selection(self, pending: bool, candidates=None, operation=None, extra=None):
        self.conversation_context["has_pending_file_selection"] = bool(pending)
        if pending and candidates:
            self.conversation_context["pending_file_candidates"] = [
                str(c) for c in candidates
            ]
            self.conversation_context["pending_operation"] = operation
            self.conversation_context["pending_extra"] = extra or {}
        elif not pending:
            self.conversation_context["pending_file_candidates"] = []
            self.conversation_context["pending_operation"] = None
            self.conversation_context["pending_extra"] = {}

    def set_pending_confirmation(self, pending: bool, question=None):
        self.conversation_context["has_pending_confirmation"] = bool(pending)
        self.conversation_context["pending_confirmation_question"] = (
            str(question) if (pending and question) else None
        )

    # =====================================
    # FAST-PATH LOCAL ROUTER (< 2ms)
    # =====================================

    def _try_fast_path(self, raw_command):
        text = str(raw_command or "").strip()
        cleaned = re.sub(r"[.!؟?،,]+$", "", text).strip().casefold()
        if not cleaned:
            return None

        # 1. استجابة فورية لأي سؤال تأكيد صوتي معلق
        if self.conversation_context.get("has_pending_confirmation"):
            tokens = set(cleaned.split())
            if cleaned in self._CONFIRM_WORDS or (tokens & self._CONFIRM_WORDS and not (tokens & self._CANCEL_WORDS)):
                res = self._empty_action()
                res["intent"] = "confirm_action"
                res["action"] = "confirm"
                res["confidence"] = 1.0
                return res
            if cleaned in self._CANCEL_WORDS or (tokens & self._CANCEL_WORDS):
                res = self._empty_action()
                res["intent"] = "confirm_action"
                res["action"] = "cancel"
                res["confidence"] = 1.0
                return res

        # 2. أوامر مباشرة سريعة بدون انتظار API
        fast_map = [
            (r"^(increase volume|volume up|علي الصوت|عليه الصوت|زود الصوت|ارفع الصوت)$",
             {"intent": "increase_volume", "amount": 5}),
            (r"^(decrease volume|volume down|وطي الصوت|قلل الصوت|اخفض الصوت)$",
             {"intent": "decrease_volume", "amount": 5}),
            (r"^(mute|mute volume|اكتم الصوت|كتم الصوت|اسكت)$",
             {"intent": "mute"}),
            (r"^(unmute|unmute volume|شغل الصوت|الغي كتم الصوت|فك الكتم)$",
             {"intent": "unmute"}),
            (r"^(scroll down|انزل تحت|نزل الصفحة|انزل لتحت)$",
             {"intent": "scroll", "action": "down", "amount": 4}),
            (r"^(scroll up|اطلع فوق|طلع الصفحة|اطلع لفوق)$",
             {"intent": "scroll", "action": "up", "amount": 4}),
            (r"^(click here|دوس هنا|اضغط هنا)$",
             {"intent": "click_element", "target": "here"}),
            (r"^(go back|ارجع|رجوع)$",
             {"intent": "go_back"}),
        ]

        for pattern, spec in fast_map:
            if re.match(pattern, cleaned):
                res = self._empty_action()
                res.update(spec)
                res["confidence"] = 0.99
                return res

        return None

    # =====================================
    # UNDERSTAND COMMAND
    # =====================================

    def understand(self, command):

        if not command or not str(command).strip():
            return self._clarification(
                "I didn't hear a command. Please repeat it."
            )

        fast_result = self._try_fast_path(command)
        if fast_result is not None:
            self._prepare_voice_metadata(fast_result, command)
            self._update_context(fast_result)
            print("[VOXY FAST-PATH UNDERSTANDING]")
            print(json.dumps(fast_result, ensure_ascii=False, indent=2))
            return fast_result

        context = json.dumps(
            self.conversation_context,
            ensure_ascii=False
        )

        user_prompt = f"""
Previous conversation and execution context:
{context}

New user command:
{str(command).strip()}

Interpret the command based on its meaning and context.
Extract dynamic targets and parameters.
Return the required JSON structure only.
"""

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )

            raw_response = completion.choices[0].message.content
            result = json.loads(raw_response)

            result = self._normalize_result(result)
            self._restore_name_case(result, command)
            self._apply_video_context(result)
            self._prepare_voice_metadata(result, command)
            self._update_context(result)

            print("[VOXY UNDERSTANDING]")
            print(json.dumps(result, ensure_ascii=False, indent=2))

            return result

        except Exception as error:
            print("[VOXY UNDERSTANDING ERROR]", error)

            return self._clarification(
                "I couldn't process that command. Please try again."
            )

    def _prepare_voice_metadata(self, result, command):
        """Attach detected language and speakable response_text for TTS feedback."""
        result["detected_language"] = detect_language(str(command)) or "en"
        if result.get("response_text"):
            result["spoken_feedback"] = clean_text(result["response_text"])
        else:
            result["spoken_feedback"] = None

    # =====================================
    # ACTION DEFAULTS
    # =====================================

    def _restore_name_case(self, result, command):
        """Keep file/folder names exactly as the user wrote them."""
        text = str(command)
        actions = result.get("actions") or [result]

        for action in actions:
            if action.get("intent") not in (
                "create_structure", "delete_item", "open_local_file",
                "list_directory", "move_item", "rename_item"
            ):
                continue

            for field in ("folder_name", "file_name", "target", "parent_folder", "source_path", "new_name"):
                value = action.get(field)

                if isinstance(value, str) and value:
                    index = text.casefold().find(value.casefold())

                    if index != -1:
                        action[field] = text[index:index + len(value)]

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
            "needs_clarification": False
        }

    # =====================================
    # NORMALIZE RESULT
    # =====================================

    def _normalize_action(self, action):

        if not isinstance(action, dict):
            action = {}

        normalized = self._empty_action()
        normalized.update(action)

        allowed_intents = {
            "open_application",
            "close_application",
            "open_website",
            "search_web",
            "search_video",
            "play_video",
            "open_local_file",
            "select_search_result",
            "list_directory",
            "click",
            "click_element",
            "type_text",
            "type_into_element",
            "list_ui_elements",
            "scroll",
            "go_back",
            "go_forward",
            "go_home",
            "increase_volume",
            "decrease_volume",
            "set_volume",
            "mute",
            "unmute",
            "create_structure",
            "delete_item",
            "move_item",
            "rename_item",
            "confirm_action",
            "conversational_response",
            "unknown"
        }

        if normalized["intent"] not in allowed_intents:
            normalized["intent"] = "unknown"

        try:
            normalized["confidence"] = float(
                normalized.get("confidence") or 0.0
            )
        except (TypeError, ValueError):
            normalized["confidence"] = 0.0

        normalized["confidence"] = max(
            0.0,
            min(1.0, normalized["confidence"])
        )

        normalized["needs_clarification"] = bool(
            normalized.get("needs_clarification", False)
        )

        return normalized

    def _normalize_result(self, result):

        if not isinstance(result, dict):
            return self._clarification(
                "I couldn't understand that command."
            )

        normalized = self._normalize_action(result)

        raw_actions = result.get("actions", [])

        if not isinstance(raw_actions, list):
            raw_actions = []

        normalized["actions"] = [
            self._normalize_action(action)
            for action in raw_actions
            if isinstance(action, dict)
        ]

        return normalized

    # =====================================
    # VIDEO CONTEXT
    # =====================================

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
                    action["platform"] = action.get("platform") or "youtube"
                else:
                    result["needs_clarification"] = True
                    result["response_text"] = (
                        "Which video would you like me to play?"
                    )

    # =====================================
    # UPDATE CONTEXT
    # =====================================

    def _update_context(self, result):

        actions = result.get("actions") or [result]

        for action in actions:

            intent = action.get("intent")
            target = action.get("target")
            query = action.get("query")
            platform = action.get("platform")

            if intent in ("search_video", "search_web"):
                if query and (
                    intent == "search_video"
                    or str(platform or "").lower() in ("youtube", "يوتيوب")
                ):
                    self.conversation_context[
                        "last_video_search_query"
                    ] = query

            if intent in ("open_application", "close_application"):
                if target:
                    self.conversation_context[
                        "last_application"
                    ] = target

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

    # =====================================
    # CLARIFICATION
    # =====================================

    def _clarification(self, message):

        result = self._empty_action()
        result["intent"] = "unknown"
        result["confidence"] = 0.0
        result["needs_clarification"] = True
        result["response_text"] = message
        result["spoken_feedback"] = clean_text(message)
        result["detected_language"] = detect_language(message) or "en"
        result["actions"] = []

        return result


# =========================================
# OPTIONAL COMPATIBILITY FUNCTION
# =========================================

_default_engine = None


def understand_command(command, api_key=None):

    global _default_engine

    if _default_engine is None:
        _default_engine = CommandUnderstanding(
            api_key=api_key
        )

    return _default_engine.understand(command)