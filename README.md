# Montazh Agent 🎬

**A Claude Code video-editing agent running on 10 skills — memes, images, emoji accents, and music included.**

Talk to it like you'd talk to an editor: *"cut a reel out of these clips"* — it inventories your footage, transcribes speech with word-level timestamps, proposes an editing strategy, waits for your approval, then cuts, grades, overlays, subtitles, and renders. Iterate in plain language; nothing is re-transcribed or re-paid twice.

Forked from [browser-use/video-use](https://github.com/browser-use/video-use) and grown into a full production pipeline.

## What it does

| | |
|---|---|
| ✂️ **Speech-aware cutting** | Every cut snaps to word boundaries from a verbatim ASR transcript. Smart asymmetric padding per final phoneme, a thought-boundary guard — no mid-word, no mid-thought cuts. |
| 🎭 **Memes** | `[мем:🤯]` in your script, or just say *"drop a meme here"* — searched on KLIPY (video clips + GIFs), picked by target **emotion**, composited center-screen with a manifest. |
| 😀 **Emoji accents** | Color emoji pop in exactly on the word they illustrate ("lawyer" → ⚖, "link below" → 👇). Payoff-timed from word timestamps, rendered as alpha overlay clips. |
| 🎵 **Music** | Instrumental generation (ElevenLabs / Suno gateways / Fal), best-window selection by energy (ebur128), sidechain ducking under the voice. |
| 🖼️ **Images & B-roll** | Generated B-roll via MCP gateways (Veo / Kling / Hailuo / Nano Banana), manifest-tracked and CLIP-continuity checked; picture memes and image overlays. |
| 📺 **Screen recordings → 9:16** | Wide screen captures cropped to a true vertical window that follows the mouse and action zones; panels too wide to crop become blur-backed cards. |
| 📝 **Subtitles** | Burned-in from a master SRT on the output timeline; bold 2-word UPPERCASE or natural-sentence styles; social safe-zone aware; always composited last. |
| 🧩 **Overlay engines** | PIL PNG-sequences, Manim, Remotion, HyperFrames — built by parallel sub-agents, one per animation slot. |
| ✅ **Quality gates** | Delivery-promise gate, slideshow-risk scorer, post-render sanity review (black frames / silence / duration drift), and a 3-pass self-eval before you ever see a preview. |
| 🔁 **Recoverable state** | Every edit saved as JSON EDL **and** OpenTimelineIO (`.otio`, optional `.fcpxml`) — take the cut into DaVinci Resolve or Final Cut any time. |

## The 10 skills

**7 bundled in this repo:**

| Skill | What it adds |
|---|---|
| [`SKILL.md`](SKILL.md) | The editor itself: mode dispatch, 20 hard production rules, cut craft, per-mode pipelines |
| [`skills/meme-inserter`](skills/meme-inserter/SKILL.md) | Memes and reaction images from KLIPY, emotion-first selection, script cues |
| [`skills/emoji-accents`](skills/emoji-accents/SKILL.md) | Pop-in emoji overlays timed to spoken words |
| [`skills/text-behind`](skills/text-behind/SKILL.md) | A word sitting behind the speaker via a person mask |
| [`skills/reels-breakdown`](skills/reels-breakdown/SKILL.md) | Any reel → a «text \| shot» storyboard with retention metrics |
| [`skills/reels-first-frame`](skills/reels-first-frame/SKILL.md) | First frame as a cover: literal shot + a headline that reads in a second |
| [`skills/video-music`](skills/video-music/SKILL.md) | Background music generation + voice ducking |
| [`skills/manim-video`](skills/manim-video/SKILL.md) | Math / diagram animations via Manim |

**5 companion Claude Code workflow skills it's built to run with** (wired into [CLAUDE.md](CLAUDE.md); the agent works without them, but they raise the floor):

| Skill | Role in the pipeline |
|---|---|
| `verification-before-completion` | Never says "done" before render, duration and self-eval checks pass |
| `systematic-debugging` | Root-cause analysis before any FFmpeg / PIL / Manim fix |
| `writing-plans` | Detailed plan before non-trivial features (e.g. lipsync support) |
| `brainstorming` | Requirements dialogue before big architectural decisions |
| `prompt-caching-playbook` | `cache_control` on 10K+-token transcripts — ~90% off repeat reads |

## Editing modes

| Sources | You say | Mode |
|---|---|---|
| 1 long video | "cut highlights per my script" | **highlight** |
| 2–10 short clips | "make one reel out of these" | **multi-clip montage** |
| voice track + N videos | "voice is the base, match visuals to it" | **audio-first** (CLIP matching) |
| any videos | "I need reels + square + YouTube versions" | **format-mix** |
| script only | "generate the whole thing" | **generative-only** |
| brief + preset name | 8 proven "content-factory" formats | **content-factory** |

## How it works

```
sources (read-only)
  → ffprobe inventory                        inventory.py
  → ASR with word timestamps (MCP)           transcribe_mcp.py
  → phrase-level packed transcript           pack_transcripts.py
  → LLM proposes a strategy → YOU approve
  → JSON EDL (+ .otio twin)                  validate → snap → thought-guard → pad
  → per-segment extract + grade + 30ms fades render.py
  → lossless concat → overlays → subs LAST
  → loudnorm → quality gates → self-eval
  → preview → your feedback → final
```

The LLM reasons over a compact packed transcript (~1/10 the tokens of raw ASR JSON) and drills into actual frames only at decision points. All session artifacts live in `<your_videos_dir>/edit/` — never inside this repo.

## Install

```bash
git clone https://github.com/AgentSmoki/Montazh_Agent && cd Montazh_Agent
uv sync                      # Python 3.10+
brew install ffmpeg yt-dlp   # or apt / winget — see docs/os_profiles.md
cp .env.example .env         # add your keys

python helpers/env_doctor.py # checks ffmpeg, fonts, keys — prints per-OS fixes
```

Register as a Claude Code skill and connect the transcription MCP (see [install.md](install.md)), then open any folder with footage and say what you want:

```bash
ln -sfn "$(pwd)" ~/.claude/skills/montazh-agent
cd ~/my_reels_project        # clip1.mp4, clip2.mp4, voice.m4a, scenario.md
claude
# > cut one reel out of these three clips, follow scenario.md
```

**Requirements:** [Claude Code](https://claude.com/claude-code) · ffmpeg/ffprobe · Python ≥ 3.10 · an ASR MCP with word-level timestamps — connect the TeleTranscribe transcriber via MCP here: **[@TeleTranscribe_bot](https://t.me/TeleTranscribe_bot)** (any other verbatim word-level ASR adapts in `helpers/transcribe_mcp.py`) · optional MCPs for B-roll (Higgsfield / Fal), TTS (ElevenLabs), music.

Runs on **macOS / Windows / Linux** — OS detection, font paths, and shell quirks are abstracted in `helpers/platform_paths.py` (`env_doctor.py` will tell you what's missing and how to install it on your OS).

## Example session

> **You:** here are my sources — cut two reels: one about the product, one "how I edited this"
> **Agent:** *(inventories 6 files, transcribes 3.5 min of speech for ~$0.05, inspects key frames)* Here's what I see in the material and a strategy per reel — durations, cut plan, subtitle style, music. Confirm?
> **You:** go — and add emoji wherever I name things
> **Agent:** *(renders previews, self-evals every cut boundary, fixes a clipped word its own thought-guard caught, delivers both finals)*

Real production example: two vertical reels cut from raw phone footage + screen recordings, with emoji accents, AI music, and a recursive finale — the agent editing the very reel that shows the agent being asked to edit it.

## Production hard rules

20 non-negotiable correctness rules are enforced in the pipeline: subtitles composited last, per-segment extract with lossless concat, 30 ms hanning audio fades on every boundary, word-boundary snapping, smart phoneme-aware padding, uniform frame geometry, manifests for all generated content, C2PA watermarking when generated footage ships, and more. Full list in [SKILL.md](SKILL.md).

## Credits

- [browser-use/video-use](https://github.com/browser-use/video-use) — the upstream this project forked from (MIT).
- [OpenMontage](https://github.com/calesthio/OpenMontage) — inspired the quality-gate ideas (delivery promise, slideshow risk, post-render review); reimplemented from scratch, no AGPL code included.

## Contact

Questions, setup help, ideas — **[@Bogman108](https://t.me/Bogman108)** on Telegram.

## License

MIT — see [LICENSE](LICENSE).
