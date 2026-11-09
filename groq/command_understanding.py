
import os
import json
from groq import Groq


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
Do not replace an unfamiliar name with a different name.

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
click
click_element
type_text
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
conversational_response
unknown

These are execution categories, NOT a list of accepted user commands.

Map any natural-language expression to the correct category.

Do not invent new intent names.

==================================================
4. OPENING AND CLOSING
==================================================

Opening:
- If the user means a desktop application, use open_application.
- If the user means a website or online service, use open_website.
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

For a named screen element:
- use click_element.
- target = the element description exactly as understood.
- Do not invent x/y coordinates.

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

Do not translate, summarize, or alter the text to be typed
unless the user explicitly requests that.

==================================================
8. SCROLLING AND NAVIGATION
==================================================

Use scroll for requests to move the page or scrollable area.

action = up or down.

amount = a reasonable small integer.
Use 3 by default if the user does not specify an amount.

Interpret expressions such as:
- Scroll down/up.
- Go a little lower/higher.
- انزل شوية.
- اطلع لفوق.
- نزّل الصفحة.
- ارجع لفوق.

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
10. FILES AND FOLDERS
==================================================

Use open_local_file when the user asks to open a local file
or folder.

Use create_structure when the user asks to create a file or folder.

Use delete_item when the user asks to delete a file or folder.

Extract the requested name into the appropriate fields:
target, folder_name, file_name, content.

Never invent a filename or file path.

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
            "last_screen_element": None
        }

    # =====================================
    # UNDERSTAND COMMAND
    # =====================================

    def understand(self, command):

        if not command or not str(command).strip():
            return self._clarification(
                "I didn't hear a command. Please repeat it."
            )

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
            self._apply_video_context(result)
            self._update_context(result)

            print("[VOXY UNDERSTANDING]")
            print(json.dumps(result, ensure_ascii=False, indent=2))

            return result

        except Exception as error:
            print("[VOXY UNDERSTANDING ERROR]", error)

            return self._clarification(
                "I couldn't process that command. Please try again."
            )

    # =====================================
    # ACTION DEFAULTS
    # =====================================

    def _empty_action(self):

        return {
            "intent": "unknown",
            "target": None,
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
            "click",
            "click_element",
            "type_text",
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
