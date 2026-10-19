# backtalk

> **Your agent's voice.** A voice system that talks through your speakers, with barge-in detection, wake word, and natural TTS/ASR.

This is the voice layer of your agent. It holds a key, talks out loud, and answers through your speakers about a second later, with all its tools and its whole personality.

> **Never used Claude Code?** Start at https://github.com/anthropics/claude-code: pick your situation and the wizard routes you to the right path.

## What it does

- **Voice input:** records you, detects speech, and sends it to your agent.
- **Voice output:** speaks back with natural sounding TTS.
- **Barge-in:** interrupts itself when you talk over it.
- **Wake word:** optional wake word detection to start listening without pressing a key.
- **Duplex:** full-duplex conversation — you talk while it listens, and it talks while you listen.

## Install

You need [Claude Code](https://github.com/anthropics/claude-code) with a Claude subscription. Mac and Linux also use git. Windows needs nothing else: the installer sets up git for you during setup.

Mac and Linux:

```bash
mkdir -p ~/my-agent && cd ~/my-agent && git clone https://github.com/oscpbunny/backtalk.git && cd backtalk && bash install.sh
```

Windows (PowerShell):

```powershell
$d="$env:USERPROFILE\.local\bin"; if (Test-Path "$d\claude.exe") { $env:Path="$d;$env:Path" }; New-Item -ItemType Directory -Force -Path $HOME\my-agent | Out-Null; cd $HOME\my-agent; if (-not (Test-Path backtalk\backtalk.md)) { Invoke-WebRequest https://github.com/oscpbunny/backtalk/archive/refs/heads/main.zip -OutFile bt.zip; Expand-Archive bt.zip . -Force; New-Item -ItemType Directory -Force -Path backtalk | Out-Null; Get-ChildItem backtalk-main -Force | Copy-Item -Destination backtalk -Recurse -Force; Remove-Item backtalk-main -Recurse -Force; Remove-Item bt.zip }; cd backtalk; if (Get-Command claude -ErrorAction SilentlyContinue) { claude "set me up" } else { Write-Output "Claude Code is not installed yet. Install it first at https://github.com/anthropics/claude-code then paste this again." }
```

*(The Windows command downloads the toolbox as a zip on purpose, so it works on a machine with no git installed. The installer sets up git for you during setup. Safe to paste as many times as you like: it skips the download when the toolbox is already there, and if an earlier attempt died partway and left a half-finished folder, it downloads again and finishes the job rather than assuming it was already done.)*

## After install

- **Start talking:** run `bash run.sh`.
- **Make it talk:** ask your agent to start the voice.
- **Check the status:** run `bash run.sh status`.

## License

Copyright (c) 2026 oscpbunny.

Licensed under the GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later). See the LICENSE file.
