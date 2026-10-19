"Great, this note looks very relevant to our current conversation about developer productivity."
# 🦾 Jarvis Frontier Architecture & Unified Upgrade Roadmap
> **Status:** Active Master Specification & Architecture Plan  
> **Environment:** Apple Silicon M3 Pro (18GB Unified Memory, macOS Sonoma/Sequoia)  
> **Agent Core Location:** `/Users/m3/Desktop/softwares/projects/fullstack-agent/`  
> **Target LLM Engines:** Local Ollama (`llama3.2:3b`, `moondream:latest`, `qwen3-embedding:8b`) + Cloud Fallback (OpenAI / Claude / OpenRouter)  

---

## 🎯 Executive Vision
To evolve Jarvis from an ambient voice assistant into an **autonomous, self-evolving, visually-grounded, multi-agent operating system companion** that eliminates all peripheral overhead (keyboard/mouse) while actively augmenting offensive engineering, software architecture, video production, and cognitive performance.

---

## 🏛️ Comprehensive Frontier Architecture Pillars

```
                              ┌─────────────────────────────────────────────────────────┐
                              │            JARVIS EXECUTIVE COGNITIVE CORE              │
                              │             (llama3.2:3b + Kokoro + VAD)                │
                              └────────────────────────────┬────────────────────────────┘
                                                           │
         ┌───────────────────┬───────────────────┬─────────┴─────────┬───────────────────┬───────────────────┐
         ▼                   ▼                   ▼                   ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   PILLAR 1:     │ │   PILLAR 2:     │ │   PILLAR 3:     │ │   PILLAR 4:     │ │   PILLAR 5:     │ │   PILLAR 6:     │
│  Self-Evolving  │ │  Autonomous GUI │ │ Subagent Task   │ │ Episodic Screen │ │ Full-Duplex     │ │ Selected Code   │
│  Skill Engine   │ │  Computer-Use   │ │ Swarm Delegation│ │ Visual Recall   │ │ Barge-In Audio  │ │ Accessibility   │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
         │                                                                                                   │
         └───────────────────────────────────┬───────────────────────────────────────────────────────────────┘
                                             ▼
                              ┌─────────────────────────────┐
                              │         PILLAR 7:           │
                              │  Ambient Guardian & Build   │
                              │      Proactive Watcher      │
                              └─────────────────────────────┘
```

---

### Pillar 1: Continuous Self-Evolving Skill Generation (Self-Writing Plugins)

#### Objective
When the user issues a request for an action Jarvis cannot currently perform, Jarvis automatically drafts, validates, sandboxes, and registers a new tool dynamically in real-time without manual developer intervention.

#### Architectural Mechanism
1. **Capability Gap Detection:**
   - Intent classifier detects an actionable request with no corresponding entry in `jarvis_actions.py` or `skills/`.
2. **Synthesis Loop:**
   - Calls the code-generation model with an explicit tool scaffold:
     ```python
     def execute_skill(args: dict) -> dict:
         """Must be fully typed, idempotent, and include error handling."""
     ```
3. **Safety & Linter Sandbox:**
   - Saves candidate script into `/Users/m3/Desktop/softwares/projects/fullstack-agent/skills/dynamic_<skill_name>.py`.
   - Runs `python3 -m py_compile` and isolated subshell verification.
4. **Dynamic Hot-Reloading:**
   - Re-indexes the tool router dynamically using Python's `importlib.import_module()`.
5. **Obsidian Skill Manifesting:**
   - Commits the new capability note into `/Users/m3/Vault/Memory/jarvis-skills/` with tags `#jarvis/skill #autonomous`.

#### Expected User Experience After Completion
- **Spoken Command:** *"Jarvis, batch convert all WebP images on my Desktop to PNG using Metal acceleration."*
- **Jarvis Action:** Jarvis detects no WebP converter exists. He replies: *"Synthesizing a Metal image conversion routine now."* Within 3 seconds, he compiles the script, runs it, converts the files, and responds: *"Converted 8 images to PNG on your Desktop. Capability permanently saved."*

---

### Pillar 2: Autonomous GUI Computer-Use & Agentic Click/Type Controller

#### Objective
Enable Jarvis to visually observe, navigate, click, drag, and manipulate native macOS applications (DaVinci Resolve, Chrome, Antigravity IDE, Finder) using visual UI grounding rather than relying solely on keyboard shortcuts.

#### Architectural Mechanism
1. **Visual UI Parsing & Grounding:**
   - Combines macOS Accessibility Tree (`AXUIElementCopyAttributeNames`) with fast bounding box visual grounding (via `moondream` or local lightweight OmniParser).
   - Extracts clickable UI elements, coordinates, and button labels in normalized `[x, y]` screen coordinates.
2. **Action Dispatch Engine (`mac_input_driver.py`):**
   - High-precision mouse movement, clicking, and dragging via PyObjC (`Quartz.CGEventCreateMouseEvent`).
   - Smooth human-like cursor interpolation (curved bezier trajectories to avoid jarring UI jumps).
3. **Application-Specific Workflows:**
   - **DaVinci Resolve:** Switch between Cut, Edit, Fusion, Color, and Deliver pages; trigger renders; apply grade presets.
   - **Browser:** Click links, interact with complex SPAs, navigate login flows.
   - **Antigravity IDE:** Focus editor panels, split screens, trigger extension commands from the command palette.

#### Expected User Experience After Completion
- **Spoken Command:** *"Jarvis, export my active timeline in DaVinci Resolve as a YouTube 4K master."*
- **Jarvis Action:** Jarvis brings DaVinci Resolve to the front, clicks the 'Deliver' tab at the bottom, selects the 'YouTube 4K' preset on the left rail, sets the export path, clicks 'Add to Render Queue', and clicks 'Render All', confirming via voice when the render has initiated.

---

### Pillar 3: Autonomous Hierarchical Subagent Swarm (Delegated Workers)

#### Objective
Transform Jarvis from a single sequential loop into an **Executive Orchestrator** capable of delegating heavy, long-running research, code analysis, and refactoring tasks to parallel background worker subagents while keeping conversational speech completely lag-free.

#### Architectural Mechanism
1. **Supervisor-Worker Topology:**
   - **Executive Jarvis (Voice Master):** Maintains continuous VAD, speech listening, and conversational responsiveness (<1.2s latency). Never gets blocked by long tasks.
   - **Worker Swarm (`subagent_pool.py`):**
     - `CodeAuditor`: Reads Swift files in `hacktivate`, runs AST analysis, detects security flaws or performance bugs.
     - `WebScout`: Headless browser agent that navigates security bulletins, GitHub releases, or technical papers.
     - `SecondBrainSynthesizer`: Formulates structured knowledge notes in `/Users/m3/Vault` with bidirectional wikilinks.
2. **Inter-Agent Message Bus:**
   - Lightweight local SQLite queue (`agent_bus.sqlite3`) for task status, progress updates, and results.
3. **Asynchronous Voice Notifications:**
   - When a subagent finishes a task, Jarvis speaks a concise summary: *"Vish, the security audit of your challenge scoring logic is complete. I found two unvalidated integer conversions and logged the remediation in your vault."*

---

### Pillar 4: Episodic Visual Screen Recall (Temporal Memory Engine)

#### Objective
Give Jarvis an associative visual-temporal memory of everything that appeared on your screen throughout the day, allowing instant contextual recall of code, documentation, URLs, or diagrams you looked at earlier.

#### Architectural Mechanism
1. **Low-Overhead Screen Ingestion Daemon (`screen_recorder.py`):**
   - Captures low-framerate frame hashes (1 capture every 10–20 seconds).
   - Skips identical/idle frames to minimize CPU and storage overhead.
   - Extracts OCR text via native macOS Vision Framework (`VNRecognizeTextRequest` running at 0% CPU on Apple Neural Engine).
2. **Temporal Vector Indexing:**
   - Embeds extracted text and visual summaries using local `qwen3-embedding:8b`.
   - Stores timestamps, active app bundle IDs, window titles, and visual embeddings in a local SQLite temporal database.
3. **Temporal Retrieval Engine:**
   - Allows natural language temporal queries (*"two hours ago"*, *"this morning"*, *"before lunch"*).

#### Expected User Experience After Completion
- **Spoken Command:** *"Jarvis, what was that Swift compiler flag I was looking at in Chrome about an hour ago?"*
- **Jarvis Action:** Jarvis queries his temporal recall index, identifies the exact webpage from 62 minutes ago, and speaks: *"At 3:45 PM, you were viewing the Apple Developer Documentation on `-Ounchecked` optimization flags in Chrome. Would you like me to open that page again?"*

---

### Pillar 5: Full-Duplex Audio & Instant Acoustic Barge-In

#### Objective
Enable natural, human-like fluid conversation by allowing the user to interrupt or correct Jarvis mid-sentence, causing Jarvis to immediately cease speaking and re-listen without stutter or audio overlap.

#### Architectural Mechanism
1. **Full-Duplex Dual Stream Buffer:**
   - Audio output (TTS playback) and microphone input (VAD listener) run concurrently on independent non-blocking threads.
2. **Real-Time Acoustic Echo Suppression (AEC):**
   - Cross-correlates the active Kokoro playback buffer against the incoming microphone stream.
   - If incoming mic RMS exceeds the dynamic threshold *with novel user voice frequencies* (barge-in detected), `sd.stop()` is triggered immediately (<80ms latency).
3. **State Resynchronization:**
   - The LLM stream is aborted, conversation buffer truncated to the point of interruption, and the agent enters `listening` state instantly.

#### Expected User Experience After Completion
- **Scenario:** Jarvis begins explaining a multi-sentence architecture overview.
- **User Intervention:** User says: *"Wait, skip that—just open Chrome."*
- **Jarvis Action:** Jarvis stops speaking immediately at the word *"Wait"*, cuts audio output, and instantly responds: *"Opening Chrome."*

---

### Pillar 6: Native macOS Accessibility & Selected Code Inspector

#### Objective
Allow Jarvis to read, analyze, and refactor any highlighted code, terminal stack trace, or text selection across Antigravity IDE, Xcode, or browser tabs without requiring manual copy-pasting.

#### Architectural Mechanism
1. **`AXUIElement` Focused Element Query:**
   - Queries `kAXFocusedUIElementAttribute` to retrieve the active focused control.
   - Extracts `kAXSelectedTextAttribute` directly from the focused text area via PyObjC.
2. **Clipboard Fallback Tap:**
   - If `AXSelectedText` is protected or unexposed by an Electron webview, fires a microsecond simulated keystroke (`Cmd+C`), reads the system pasteboard (`NSPasteboard`), and restores the prior pasteboard state seamlessly.
3. **Contextual Action Dispatch:**
   - Injects the selected text into the prompt context for instant explanation, syntax review, or vulnerability auditing.

#### Expected User Experience After Completion
- **Spoken Command:** User highlights 15 lines of Swift challenge scoring code and says: *"Jarvis, what's the time complexity of this block?"*
- **Jarvis Action:** Jarvis grabs the highlighted lines directly and speaks: *"That block runs in O(N log N) time due to the sorting step on line 34. You can optimize it to O(N) using a hash map."*

---

### Pillar 7: Proactive Ambient Guardian & Background Build Watcher

#### Objective
Provide Jarvis with persistent background vigilance that watches your build outputs, git worktrees, and system resource health, proactively speaking up only when critical events occur.

#### Architectural Mechanism
1. **FSEvents File System Watcher:**
   - Monitors build artifact directories (`.build/`, `DerivedData/`, `.git/index`) for change events.
2. **Build Error Interception:**
   - Watches compiler error logs from `swift build` or terminal tasks.
   - Automatically parses stack traces into actionable plain-English summaries.
3. **Proactive Spoken Notification Gate:**
   - Does not interrupt if user is typing rapidly.
   - Waits for a natural cognitive pause (>3s keyboard idle), then alerts:
     *"Your CampaignTests build just failed with an unresolved type on line 42."*

#### Expected User Experience After Completion
- **Scenario:** You run a test suite in the background and switch over to read documentation.
- **Jarvis Action:** As soon as the tests terminate, Jarvis softly informs you: *"All 14 campaign tests passed successfully."*

---

## 📋 Complete Implementation Milestones & Roadmap

| Milestone | Phase | Priority | Primary Dependencies | Status |
|:---|:---|:---:|:---|:---:|
| **M1: Core Daemon Grounding** | App controls, noise calibration, native window perception | P0 | `kokoro`, `faster-whisper`, AppleScript | ✅ **COMPLETE** |
| **M2: Full-Duplex Barge-In** | Concurrent audio streaming, instant interruption stop | P0 | `sounddevice`, PyAudio, AEC | ⏳ **READY TO IMPLEMENT** |
| **M3: Subagent Worker Swarm** | Supervisor/worker queue, non-blocking background tasks | P1 | `asyncio`, SQLite queue | ⏳ **READY TO IMPLEMENT** |
| **M4: Self-Evolving Skill Engine** | Dynamic tool generator, sandbox validator, hot-reloader | P1 | `importlib`, AST, Python sandbox | ⏳ **READY TO IMPLEMENT** |
| **M5: Selected Code Accessibility** | Highlighted code inspector, `AXUIElement`, clipboard tap | P1 | PyObjC, `ApplicationServices` | ⏳ **READY TO IMPLEMENT** |
| **M6: Native Screen Temporal Recall** | macOS Vision ANE OCR, temporal embedding store | P2 | `Quartz`, `Vision.framework`, `qwen3-embedding` | ⏳ **READY TO IMPLEMENT** |
| **M7: Autonomous GUI Computer-Use** | Visual grounding, bezier mouse driver, DaVinci automation | P2 | `PyObjC`, `Quartz`, UI-TARS / OmniParser | ⏳ **READY TO IMPLEMENT** |
| **M8: Proactive Ambient Guardian** | FSEvents build monitor, background compiler error listener | P2 | `watchdog`, macOS FSEvents | ⏳ **READY TO IMPLEMENT** |

---

## 🛠️ Development & Execution Runbook

### To Start Jarvis Daemon in Current State:
```bash
cd /Users/m3/Desktop/softwares/projects/fullstack-agent
./venv/bin/python3 always_online_jarvis.py
```

### To Monitor Daemon Output Live:
```bash
tail -f /Users/m3/Desktop/softwares/projects/fullstack-agent/jarvis_daemon.log
```

### Project Directory Invariant:
- All agent code, tools, skills, and logs **MUST strictly remain** inside:
  `/Users/m3/Desktop/softwares/projects/fullstack-agent/`
- All project notes and persistent architectural decisions **MUST sync** with:
  `/Users/m3/Vault/Memory/`

