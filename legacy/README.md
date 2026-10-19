# legacy/ — retired code, kept for reference

Nothing in this folder is imported by the live stack. It stays here so
history and hard-won fixes aren't lost, and so it can be resurrected if
the unified brain ever needs a fallback.

| File | Why it is here |
|---|---|
| `voice_loop.py` | The pre-backtalk voice loop. P5's `DuplexSpeech` in `speech_duplex.py` is still loaded by `pillar_bridge.py`, so that one IS live. |
| `speech_duplex.py` | Loaded on demand by `pillar_bridge.make_duplex_speech()` — treat this one as live. |
| `model_router.py` | Superseded: routing now lives in `backtalk/pillars.route()` and `always_online_jarvis._route_to_best_model()`. Had zero import sites. |
| `model_optimizer.py` | Superseded by `always_online_jarvis._optimize_ollama_load()`. Zero import sites. |
| `model_management.py` | Cache/watchdog experiments, never wired in. Zero import sites. |
| `memory_optimizer.py` | Returned `{"rss": "N/A"}` and only touched file timestamps. Zero import sites. |

The primary brain itself, `always_online_jarvis.py`, lives at the repo
root as a **legacy fallback entry point** — the live brain is backtalk
(`backtalk/backtalk/pillars.py`), started by `./jarvis start`.
