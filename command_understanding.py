from difflib import get_close_matches
import re

APP_ALIASES = {
    "facebook": [
        "facebook", "face book", "fizbook", "fasebook",
        "facbook", "fesbook", "فيـسبوك", "فيسبوك",
        "الفيسبوك", "الفيس", "فيس بوك", "فيز بوك",
        "فيزبوك", "الفيس بوك", "الفيز بك",
        "فيس بك", "الفيز بوك", "فيس بوكك",
    ],
    "youtube": [
        "youtube", "you tube", "youtub", "utube",
        "يوتيوب", "اليوتيوب", "يو تيوب",
    ],
    "google": [
        "google", "gogle", "googel", "googl",
        "جوجل", "جوجول",
    ],
    "instagram": [
        "instagram", "instgram", "insta gram",
        "انستجرام", "انستغرام", "انستا", "الانستجرام",
    ],
    "whatsapp": [
        "whatsapp", "whats app", "watsapp",
        "واتساب", "واتس اب", "الواتساب", "واتس",
    ],
}

ACTION_WORDS = {
    "open", "launch", "start", "show", "visit", "access",
    "use", "go", "take", "get",
    "افتح", "افتحي", "افتحلي", "شغل", "شغلي", "شغللي",
    "اعرض", "روح", "روحي", "ادخل", "ادخلني", "يفتح",
    "تفتح", "تفتحلي", "اتفتح", "استخدم", "استخدمي",
    "استخدملي", "شغللي", "عايز", "عايزة", "عاوز", "عاوزة",
    "ممكن", "عايزه", "عاوزه",
}

POLITE_WORDS = {
    "can", "could", "would", "you", "please",
    "i", "want", "to", "me", "for", "the",
    "hey", "voxy", "now", "my", "app", "website", "up",
    "من", "فضلك", "لو", "سمحت", "ممكن", "عايز", "عايزة",
    "عاوز", "عاوزة", "لي", "لى", "الى", "إلى", "على",
    "ال", "بقى", "دلوقتي", "كده",
}


def normalize_text(text):
    text = text.lower().strip()
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def understand_command(command):
    text = normalize_text(command)

    if not text:
        return {"intent": "unknown", "target": None}


    # Handle common Egyptian Arabic requests even when transcription wording varies.
    request_words = {
        "افتح", "افتحي", "افتحلي", "شغل", "شغلي", "شغللي",
        "استخدم", "استخدمي", "استخدملي", "روح", "روحي",
        "عايز", "عايزة", "عاوز", "عاوزة", "ممكن",
        "ورمي", "وريني", "ورينيلي",
    }
    words = text.split()
    for app, aliases in APP_ALIASES.items():
        for alias in sorted(
            (normalize_text(a) for a in aliases),
            key=len,
            reverse=True
        ):
            if alias and (text == alias or f" {alias} " in f" {text} "):
                if any(word in request_words for word in words):
                    return {"intent": "open_app", "target": app}

    # First, match known app names anywhere in the recognized sentence.
    for app, aliases in APP_ALIASES.items():
        normalized_aliases = [normalize_text(alias) for alias in aliases]

        for alias in sorted(normalized_aliases, key=len, reverse=True):
            if text == alias or f" {alias} " in f" {text} ":
                before = text.split(alias, 1)[0].strip().split()
                if any(word in ACTION_WORDS for word in before) or text == alias:
                    return {"intent": "open_app", "target": app}

        # Fuzzy matching on the words after an action, including common
        # transcription variations such as "اتفتح الفيز بوك".
        for i, word in enumerate(words):
            if word in ACTION_WORDS:
                target_text = " ".join(words[i + 1:]).strip()
                target_words = [
                    w for w in target_text.split()
                    if w not in POLITE_WORDS
                ]
                target_text = " ".join(target_words)

                if target_text in normalized_aliases:
                    return {"intent": "open_app", "target": app}

                match = get_close_matches(
                    target_text, normalized_aliases, n=1, cutoff=0.55
                )
                if match:
                    return {"intent": "open_app", "target": app}

    return {"intent": "unknown", "target": None}
