# Voxy voice feedback

Spoken results for Voxy, added without changing how commands are understood or
executed. Everything TTS-specific lives in `voice_feedback.py`.

## Engine: Edge-TTS (cloud)
* Free, no API key, no account, ~nothing installed locally (a small network client).
* Egyptian Arabic voices `ar-EG-SalmaNeural` / `ar-EG-ShakirNeural`; English voices too.
* Limits: it is an **unofficial** use of Microsoft's Edge endpoint (no SLA, could
  change or break); needs internet; custom SSML is not supported.
* **Not yet verified by ear:** mixed Arabic/English pronunciation. Run
  `tts_probe.py` on the VM and pick `VOXY_TTS_MIXED_STRATEGY` (`single` = whole
  sentence with the Arabic voice, `split` = Arabic/English runs each get their
  own voice, so two voices).
* Official backup option: Azure AI Speech free tier (0.5M chars/month, key needed).

## Install (Ubuntu)
    sudo apt install ffmpeg          # provides ffplay (mpv or mpg123 also work)
    pip install -r requirements_voice.txt
    cp .env.example .env             # optional
    python3 voxy_gui_test.py

Without edge-tts / a player / internet Voxy runs exactly as before, silently
(one log line explains why).

## How it behaves
* Spoken only for real outcomes: success, failure, clarification question, and
  one "one moment…" if a command is still running after 6 s.
* Not spoken: microphone/transcription errors (they repeat every few seconds in
  continuous-listening mode and would be annoying).
* Reply language follows the command text (Arabic / English / mixed).
* Speech runs in one background thread via a queue; no overlap; GUI never waits.
* The mic is not reopened while Voxy speaks (+0.5 s tail), and pressing the mic
  button stops speech.
* Repeated phrases come from a disk cache (`~/.cache/voxy_tts`).
* After 3 consecutive failures (e.g. offline) it pauses for 60 s instead of
  retrying every command.
* Disable: `VOXY_VOICE_ENABLED=0`. Speed: `VOXY_TTS_RATE`. Voice: `VOXY_TTS_AR_VOICE`.
  The existing "Sound Feedback" switch is untouched and unrelated.

## Replacing the engine
Subclass `TTSProvider` (implement `synthesize(text, lang, rate) -> mp3 bytes`),
call `voice_feedback.register_provider("name", YourProvider)` and set
`VOXY_TTS_PROVIDER=name`. The GUI code does not change.

## Tests
    python3 -m unittest test_voice_feedback -v     # offline, mocks, no sound
    python3 tts_probe.py                           # real voices, needs internet

## Restore the original
Copy the four files from `backup_original/` over the working ones (only
`voxy_gui_test.py` differs) or apply `patch -R voxy_gui_test.py < voxy_gui_test.diff`.
