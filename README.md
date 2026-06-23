# Montazh_Agent — AI-видеомонтажёр через Claude Code

Форк [browser-use/video-use](https://github.com/browser-use/video-use), локализованный на русский и адаптированный под мой стек:
- **Транскрипция** через мой собственный [TeleTranscribe MCP](../TeleTranscribe/) (GigaAM, диаризация, word-timestamps), а не ElevenLabs Scribe.
- **B-roll генерация** через Higgsfield/Fal.ai MCP (Veo 3.1 / Kling 3.0 / Hailuo / Nano Banana Pro).
- **Multi-source режимы:** нарезка из 2-10 разных рилз в один финал, audio-first (голос + видео под него), format-mix (1 source → N форматов вывода).
- **Полный overlay-стек** уже в MVP: Manim, Remotion, HyperFrames, PIL.
- **OTIO export** для дальнейшей работы в DaVinci Resolve / Final Cut Pro.

## Quick start

```bash
# 1. Установи зависимости (один раз)
cd /Users/admin/Documents/Razarabotka/Montazh_Agent
uv sync
brew install ffmpeg yt-dlp
cp .env.example .env
# отредактируй .env: впиши TT_API_KEY (обязательно)

# 2. Зарегистрируй MCP-серверы (один раз)
# TeleTranscribe — обязательно
claude mcp add teletranscribe \
  python3 /Users/admin/Documents/Razarabotka/TeleTranscribe/services/telegram-bot/mcp_server.py \
  -e TT_API_BASE_URL=http://localhost:8000 \
  -e TT_API_KEY=$(grep TT_API_KEY .env | cut -d= -f2)

# Higgsfield — для B-roll генерации (опц.)
claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp

# 3. Зарегистрируй skill в Claude Code
ln -sfn /Users/admin/Documents/Razarabotka/Montazh_Agent ~/.claude/skills/montazh-agent

# 4. Используй из любой папки с видео
cd ~/my_reels_project   # тут лежат clip1.mp4, clip2.mp4, voice.m4a и scenario.md
claude
# > смонтируй один рилз из этих трёх клипов по scenario.md
```

## Поддерживаемые сценарии

| Что у тебя | Что хочешь | Режим |
|---|---|---|
| 1 длинное видео (30 мин talking head) | нарезать highlights под сценарий | **highlight** |
| 2-10 коротких рилз | собрать один финальный с субтитрами | **multi-clip** |
| голосовое аудио + N видеосъёмок | голос как timeline, видео подбирается под фразы | **audio-first** |
| любые видео | 3 разных формата (рилз/квадрат/YT) сразу | **format-mix** |
| только сценарий, видео нет | целиком сгенерировать через MCP | **generative-only** |

Агент сам определит режим по `inventory.py` и предложит 2-3 варианта формата вывода.

## Архитектура

См. [SKILL.md](SKILL.md) — полный системный промпт агента (17 hard rules, mode dispatch, pipeline'ы для каждого режима, anti-patterns).

См. [CLAUDE.md](CLAUDE.md) — контекст для Claude Code: какие skills/MCP подключены, конвенции, запреты.

## Структура папок

```
Montazh_Agent/
├── SKILL.md, CLAUDE.md, AGENTS.md
├── helpers/                       # CLI-скрипты
│   ├── transcribe_mcp.py          # TT MCP → Scribe-format JSON
│   ├── inventory.py               # ffprobe всех источников
│   ├── format_recommender.py      # подсказки по формату вывода
│   ├── scene_detect.py            # PySceneDetect
│   ├── match_video_to_audio.py    # CLIP-матчинг (audio-first)
│   ├── broll_generator.py         # инструкции для MCP B-roll
│   ├── otio_export.py             # → .otio / .fcpxml
│   ├── pack_transcripts.py        # JSON → packed.md (upstream)
│   ├── timeline_view.py           # PNG drill-down (upstream)
│   ├── render.py                  # FFmpeg pipeline (upstream)
│   ├── grade.py                   # color presets (upstream)
│   └── overlays/                  # анимации
│       ├── pil_subs.py
│       ├── manim_runner.py
│       ├── remotion_runner.py
│       └── hyperframes_runner.py
└── skills/manim-video/            # 15 reference-файлов для Manim (upstream)
```

## Зависимости

См. [pyproject.toml](pyproject.toml). Ключевое:
- Python 3.10+
- FFmpeg + ffprobe
- OpenTimelineIO (lossless EDL)
- PySceneDetect (shot detection)
- sentence-transformers (CLIP для audio-first)
- Manim (опц., overlays для математики)
- Node.js 22+ (опц., для Remotion / HyperFrames)

## Лицензия

MIT (наследовано от [browser-use/video-use](https://github.com/browser-use/video-use)).

## Связанные проекты

- [TeleTranscribe](../TeleTranscribe/) — ASR-стек, источник транскрипций.
- [Dev_Architect](../Dev_Architect/) — research tool.
- [Agent_Architect](../Agent_Architect/) — образец структуры агентов в Razarabotka.

## Roadmap

- ✅ MVP: highlight + multi-clip + audio-first + format-mix
- ✅ TeleTranscribe MCP патч (`transcribe_file_json` с word-timestamps) — задеплоен в MCP
- 📋 Streamlit/web UI поверх (когда выйдем в SaaS)
- 📋 Lipsync для сгенерированных talking-heads (LatentSync / Sync.so)
- 📋 C2PA watermarking (compliance EU AI Act)
