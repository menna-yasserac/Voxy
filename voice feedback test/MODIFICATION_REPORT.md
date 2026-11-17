# Modification report

**Provided to me:** only 4 files (`voxy_gui_test.py`, `audio_service_AI.py`,
`command_understanding.py`, `execution.py`). Assets and `atspi_controller` were
not provided; copy the new files and apply the diff in your full project.

| | Files |
|---|---|
| Added | `voice_feedback.py`, `test_voice_feedback.py`, `tts_probe.py`, `.env.example`, `requirements_voice.txt`, `README_voice.md`, `voxy_gui_test.diff`, `backup_original/` |
| Modified | `voxy_gui_test.py` (+52 lines, 0 removed) |
| Unchanged (byte-identical, verified with cmp) | `execution.py`, `command_understanding.py`, `audio_service_AI.py` |
| Deleted | none |

## Changes in voxy_gui_test.py
1. Guarded `import voice_feedback` (falls back to None).
2. Three state attributes in `__init__`.
3. Helper methods `_vf`, `_voice_announce_result`, `_voice_schedule_processing_hint`,
   `_voice_processing_hint`; `_on_close` also calls `shutdown`.
4. `start_listening`: stops speech before the mic opens.
5. `_resume_listening`: if speaking, re-check in 300 ms (prevents Voxy hearing itself).
6. `_processing_screen`: remember command + schedule the 6 s "one moment" hint.
7. `_execute_real_pipeline`: one line publishing the real `status`.
8. `_result_screen`: one call announcing success / failure / clarification.

## Testing
| Kind | What |
|---|---|
| Executed, real | 27 unit tests pass: language detection, text cleaning, queue order/no overlap, stop (real subprocess terminated), cache, dedup, queue limit, back-off after failures, missing dependency/player, 10 concurrent callers |
| Executed, mocked | GUI hooks against a stub `tkinter`: result routing, mic-resume guard, processing hint, missing module. Provider is a fake. |
| **Not done** | Real Edge-TTS call, real audio, voice quality/latency, Egyptian/mixed pronunciation, real Tk window, real mic echo, Ubuntu VM run. Use `tts_probe.py` and a manual run. |

## Known risks
* Edge-TTS is unofficial; keep the provider interface ready for Azure.
* The "one moment" hint can also fire while the delete-confirmation dialog is open.
* A partial success (some actions failed) is announced as an error.
