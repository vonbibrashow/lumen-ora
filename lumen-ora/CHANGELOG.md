# Changelog

All notable changes to Lumen Ora are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [0.2.0] — 2026-05-19

### Added

- **Long-term memory** — `/remember <fact>`, `/memory`, `/forget <n>` persist facts
  across sessions in `~/.lumen/memory.jsonl`; facts are injected into the model's
  system prompt on every turn
- **Fast/smart model switching** — `/model fast` selects the 3B model (~18 tok/s);
  `/model smart` selects the 7B model (~12 tok/s); switchable at runtime without
  restarting the bridge
- **5 new tools** — `edit_file` (in-place string replacement), `clipboard_read`,
  `clipboard_write`, `open_app`, `take_screenshot`; total tool count is now 10
- **One-click launchers** — `start.bat` and `start.ps1` start the policy engine,
  inference bridge, and context shell in the correct order with a single command
- **Policy engine auto-start** — the shell now calls `ensure_policy_engine()` on
  startup; if the TCP port is not bound it starts the Rust binary via WSL2
  automatically and waits up to 5 s for it to become ready
- **Voice health-check** — `/voice check` reports the status of faster-whisper,
  pyttsx3, sounddevice, available microphone, and runs a TTS speaking test
- **Whisper model pre-download** — when `--voice` is passed at startup, the Whisper
  model is downloaded and cached before the REPL opens, so the first push-to-talk
  is not blocked by a network download
- **Camera gestures** — background cv2 + MediaPipe thread detects four hand gestures:
  thumbs-up (confirm pending action), open palm (cancel / clear context), peace sign
  (toggle voice mode), wave (new session)
- **Lip-VAD** — when `LUMEN_LIP_VAD=1`, the camera thread uses the MediaPipe face
  mesh to detect when the user's lips open, auto-starts recording, and transcribes
  when the lips close; no button press needed
- **Model tier flag** — `python shell.py --model fast|smart` sets the tier at launch;
  default is `smart`
- **Camera flag** — `python shell.py --camera` enables camera gesture + lip-VAD at
  launch; can also be toggled with `/camera on|off` at runtime

### Changed

- Tool result display now uses Rich `Panel` with `SIMPLE` box style; policy deny
  decisions render in a distinct red `ROUNDED` panel
- Conversation context is now capped at `MAX_CONTEXT_TURNS` (10) pairs when sent to
  the model, keeping prompt size bounded regardless of session length
- History trimming is now called after every turn (was only called on exit)
- Voice push-to-talk is now capped at 30 seconds via a daemon timeout guard thread
  that programmatically releases the keyboard wait; prevents accidental indefinite
  holds
- `run_command` now uses `Popen` line-by-line iteration rather than `communicate()`,
  enabling real streaming with a configurable `max_output_lines` cap (default 200)

### Fixed

- Policy engine TCP check now uses `socket.connect_ex` so a closed port does not
  raise an exception that blocks startup
- `read_file` and `write_file` now call `.expanduser()` on the path so `~/...` paths
  resolve correctly on all platforms

---

## [0.1.0] — 2026-05-01

### Added

- **Initial prototype** — three-component architecture: Policy Engine (Rust),
  Inference Bridge (FastAPI), Context Shell (Python)
- **Local inference** — Qwen2.5-7B-Instruct via llama.cpp; no API key required;
  model loaded via `llama-server` HTTP API on `http://127.0.0.1:8080`
- **5 core tools** — `read_file`, `write_file`, `run_command`, `search_web`,
  `list_directory`; all defined in `tool_schema.py` with Pydantic models
- **Policy engine** — Rust TCP daemon on port 8766; evaluates `Allow`, `Deny`, and
  `RequireConfirmation` decisions; append-only JSONL audit log
- **Multi-turn conversation** — in-memory context sent with every inference request;
  session ID persisted to `~/.lumen/session_id`
- **Session restore** — conversation history written to `~/.lumen/history.jsonl`;
  `/history` shows the last 10 exchanges; `/session` shows the session ID and stats
- **Real web search** — `search_web` tool uses DuckDuckGo via the `ddgs` library
  (no API key); returns title, URL, and snippet for each result
- **Streaming `run_command`** — subprocess output captured line-by-line via
  `Popen`; hard timeout enforced; output capped at 200 lines with a truncation note
- **Voice I/O** — push-to-talk STT via faster-whisper (hold Space to record, release
  to transcribe); TTS via pyttsx3; guarded imports so the shell works without voice
  deps installed
- **47-test end-to-end suite** — `test_e2e.py` covers tool execution (Layer 2,
  no model needed), bridge health, policy engine connectivity, and integration paths;
  `--skip-bridge` and `--skip-model` flags allow CI without a running llama-server
- **Rich console UI** — startup banner with service status; spinner during inference;
  tool results in panels; colour-coded policy decisions

---

[Unreleased]: https://github.com/vonbibrashow/lumen-ora/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/vonbibrashow/lumen-ora/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vonbibrashow/lumen-ora/releases/tag/v0.1.0
