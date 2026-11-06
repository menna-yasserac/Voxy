import os
import re
import json
from groq import Groq


APP_ALIASES = {
    "facebook": [
        "facebook", "face book", "fizbook", "fasebook",
        "facbook", "fesbook", "فيسبوك", "الفيسبوك",
        "الفيس", "فيس بوك", "فيز بوك", "فيزبوك"
    ],
    "youtube": [
        "youtube", "you tube", "youtub", "utube",
        "يوتيوب", "اليوتيوب", "يو تيوب"
    ],
    "google": [
        "google", "gogle", "googel", "googl",
        "جوجل", "جوجول"
    ],
    "instagram": [
        "instagram", "instgram", "insta gram",
        "انستجرام", "انستغرام", "انستا"
    ],
    "whatsapp": [
        "whatsapp", "whats app", "watsapp",
        "واتساب", "واتس اب", "الواتساب", "واتس"
    ]
}


ALLOWED_INTENTS = {
    "open_app",
    "open_browser",
    "open_terminal",
    "search_web",
    "search_youtube",
    "create_folder",
    "screenshot",
    "unknown"
}


def normalize_text(text):
    text = text.lower().strip()
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def unknown_result():
    return {
        "intent": "unknown",
        "target": None,
        "query": None,
        "folder_name": None
    }


def validate_result(result):
    if not isinstance(result, dict):
        return unknown_result()

    intent = result.get("intent")
    target = result.get("target")
    query = result.get("query")
    folder_name = result.get("folder_name")

    if intent not in ALLOWED_INTENTS:
        return unknown_result()

    if intent == "open_app":
        if target not in APP_ALIASES:
            return unknown_result()

    elif intent in ("search_web", "search_youtube"):
        if not isinstance(query, str) or not query.strip():
            return unknown_result()

        query = query.strip()

    elif intent == "create_folder":
        if not isinstance(folder_name, str):
            return unknown_result()

        folder_name = folder_name.strip()

        if (
            not folder_name
            or folder_name in (".", "..")
            or "/" in folder_name
            or "\\" in folder_name
        ):
            return unknown_result()

    elif intent in (
        "open_browser",
        "open_terminal",
        "screenshot"
    ):
        target = None

    return {
        "intent": intent,
        "target": target,
        "query": query,
        "folder_name": folder_name
    }


def understand_with_ai(command):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return unknown_result()

    try:
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": """
You are Voxy, a Linux voice assistant.

Understand Egyptian Arabic, Modern Arabic and English.
The user may speak naturally or use different expressions.

Classify the request into ONE of these intents:

1. open_app
   For opening one of:
   facebook, youtube, google, instagram, whatsapp.

2. open_browser
   For opening the internet browser.

3. open_terminal
   For opening the Linux terminal.

4. search_web
   For searching Google.
   Put the search words in query.

5. search_youtube
   For searching YouTube.
   Put the search words in query.

6. create_folder
   For creating a folder.
   Put its name in folder_name.

7. screenshot
   For taking a screenshot.

8. unknown
   For unclear or unsupported requests.

Examples:

"افتحلي اليوتيوب"
{"intent":"open_app","target":"youtube"}

"Can you open Facebook?"
{"intent":"open_app","target":"facebook"}

"دورلي على تعلم Python"
{"intent":"search_web","query":"تعلم Python"}

"Search for Python on Google"
{"intent":"search_web","query":"Python"}

"ابحث عن Python على يوتيوب"
{"intent":"search_youtube","query":"Python"}

"افتح يوتيوب وابحث عن Python"
{"intent":"search_youtube","query":"Python"}

"اعملي فولدر اسمه Voxy"
{"intent":"create_folder","folder_name":"Voxy"}

"افتح التيرمينال"
{"intent":"open_terminal"}

"خد سكرين شوت"
{"intent":"screenshot"}

Return JSON only.

Never generate shell commands.
Never invent an intent.
Never execute or suggest unsupported actions.
"""
                },
                {
                    "role": "user",
                    "content": command
                }
            ],
            response_format={"type": "json_object"},
            temperature=0
        )

        result = json.loads(
            response.choices[0].message.content
        )

        return validate_result(result)

    except Exception as error:
        print("AI UNDERSTANDING ERROR:", repr(error))
        return unknown_result()


def understand_command(command):
    if not isinstance(command, str):
        return unknown_result()

    text = normalize_text(command)

    if not text:
        return unknown_result()

    # Direct matching for simple app names.
    for app, aliases in APP_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_text(alias)

            if text == normalized_alias:
                return {
                    "intent": "open_app",
                    "target": app,
                    "query": None,
                    "folder_name": None
                }

    # Use AI for natural language commands.
    return understand_with_ai(command)
