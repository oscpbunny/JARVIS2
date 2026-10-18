# JARVIS2

> **A 7-pillar voice & agent system.** Your AI assistant with memory, voice, and a living face — built on open-source pieces, assembled into one guided experience.

This repo assembles your own agent setup on your machine: memory, voice, face, and optional hands — all wired together and ready to run.

> **Requires:** Claude Code with a Claude subscription. Mac and Linux also use git. No paid plans or accounts required.

---

## What you get

Five pieces, each its own open repo, assembled here into one agent:

- **The mind:** [memory vault](https://github.com/oscpbunny/JARVIS2) — A real, persistent memory built on plain text files your AI reads and writes. It remembers you, your work, and every lesson, across every session, with no size ceiling.
- **The mouth:** [backtalk](https://github.com/oscpbunny/backtalk) — Hold a key, talk out loud, and your agent answers through your speakers about a second later, with all its tools and its whole personality.
- **The face:** [ai-visualizer](https://github.com/oscpbunny/ai-visualizer) — Full-screen visualizers that idle, listen, think, and speak in sync with the real conversation. Four faces ship, including the living circuit board from our recordings.
- **The hands, the optional extra:** [barehands](https://github.com/oscpbunny/barehands) — Move notes and images around your screen with your bare hands through your webcam. No headset, no controllers. Opens in its own window instead of the face.
- **The voice:** [jarvis-voice](https://github.com/oscpbunny/jarvis-voice) — Voice pipeline with barge-in detection, wake word, and natural TTS/ASR.

Every piece is optional. The installer asks which ones you want and explains each in plain English before you decide.

---

## Install

You need [Claude Code](https://github.com/anthropics/claude-code) with a Claude subscription. Mac and Linux also use git. Windows needs nothing else: the installer sets up git for you during setup.

**Mac and Linux:**

```bash
mkdir -p ~/my-agent && cd ~/my-agent && git clone https://github.com/oscpbunny/JARVIS2.git && cd JARVIS2 && claude "set me up"
```

**Windows (PowerShell):**

```powershell
$d="$env:USERPROFILE\.local\bin"; if (Test-Path "$d\claude.exe") { $env:Path="$d;$env:Path" }; New-Item -ItemType Directory -Force -Path $HOME\my-agent | Out-Null; cd $HOME\my-agent; if (-not (Test-Path JARVIS2\JARVIS2.md)) { Invoke-WebRequest https://github.com/oscpbunny/JARVIS2/archive/refs/heads/main.zip -OutFile fsa.zip; Expand-Archive fsa.zip . -Force; New-Item -ItemType Directory -Force -Path JARVIS2 | Out-Null; Get-ChildItem JARVIS2-main -Force | Copy-Item -Destination JARVIS2 -Recurse -Force; Remove-Item JARVIS2-main -Recurse -Force; Remove-Item fsa.zip }; cd JARVIS2; if (Get-Command claude -ErrorAction SilentlyContinue) { claude "set me up" } else { Write-Output "Claude Code is not installed yet. Install it first at https://github.com/anthropics/claude-code then paste this again." }
```

> The Windows command downloads the toolbox as a zip on purpose, so it works on a machine with no git installed. The installer sets up git for you during setup. Safe to paste as many times as you like: it skips the download when the toolbox is already there, and if an earlier attempt died partway and left a half-finished folder, it downloads again and finishes the job rather than assuming it was already done.

---

## After setup

- **Use your agent:** the installer leaves three shortcuts on your Desktop, named after your agent. **Chat** opens a typed session, terminal only. **Talk** starts the voice and the face. **Barehands** starts the voice and the hands board (the board is the screen in that mode). Double-click the mood you want; Ctrl-C in the window stops it. (They just run `start.sh`, or `start.bat` on Windows, if you ever prefer the terminal.)
- **Something broken or confusing? Ask your agent to fix it.** Seriously. Open the chat and describe the problem. Every repo here ships a troubleshooting guide written for your agent to read, and your agent is instructed during setup to do the fixing itself. You never have to debug this stack yourself.
- **Update everything:** `./update.sh` on macOS. On Windows, ask your agent: "update everything and tell me what changed." Your files live outside the repos, so updates never touch who your agent is or what it remembers.
- **Daily habit:** open Claude Code in your agent's folder. That's where it lives.

---

## The fine print that matters

- The installer never deletes, overwrites, or moves anything you built. Replacements retire the old thing in place and say so.
- Your vault stays wherever it already lives. Pieces connect by configuration paths, not by relocation.
- Requirements per piece: the voice needs a mic and about 1 GB of local models on first run; the hands need a webcam and Chrome; the mind and face need nothing but Python 3, which ships with macOS and most Linux distributions. **Windows ships none**, and the name `python` there is a Microsoft Store placeholder that passes a check and then exits without running, so the face and the hands each carry a `run.bat` that finds a working interpreter or says plainly that there is not one. Windows notes live in each piece's own README.
- Cross-piece problems: `TROUBLESHOOTING.md` here. Everything else: each piece's own guide.

---

## The rest of it

Everything here is free and open, and there is a whole community using it.

- **The videos.** Free series on all of it: https://youtube.com/@oscpbunny
- **The Discord.** Thousands of builders, and the fastest place to get unstuck: https://discord.gg/YSdsqMv3V8
- **Everything else,** free and open: https://github.com/oscpbunny

---

## Support

Free to use, and always will be. If this helped you out, you can buy me a coffee:

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/oscpbunny)

---

## License

Copyright (c) 2026 oscpbunny.

Licensed under the GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later). **Use it in your business, commercially, for free.** Run it, change it, build your workflow on top of it, and charge for the work you do with it. The one rule is that it stays open: if you hand it to someone else, or run a modified version as a service other people use, your version ships under this same license with source available. Credit the original author when you build on it. Want it inside a closed-source commercial product? Email the maintainer. Full terms are at https://www.gnu.org/licenses/agpl-3.0.html
