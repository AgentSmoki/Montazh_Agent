# CLAUDE.md — Montazh_Agent

Контекст для Claude Code, когда работаешь внутри проекта `Montazh_Agent` или вызываешь его как skill из любой `videos_dir/`.

---

## ⚠️ ОБЯЗАТЕЛЬНО ПРИ СТАРТЕ СЕССИИ

Выполни в порядке:

1. **Прочитай `SKILL.md` целиком.** Это системный промпт агента — 17 hard rules, mode dispatch, pipeline'ы, anti-patterns. Без него ты не знаешь как работать.

2. **Если есть `graphify-out/GRAPH_REPORT.md`** — прочитай его для понимания зависимостей между helpers. (На свежем агенте может ещё не быть — построится через `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"`)

3. **Проверь `.env`:**
   - `TT_API_KEY` должен быть установлен (обязательно).
   - `HIGGSFIELD_API_KEY`, `FAL_KEY`, `ELEVENLABS_API_KEY`, `SUNO_API_KEY` — опционально, по фичам.
   - Если `.env` отсутствует — скопируй из `.env.example` и попроси у пользователя ключи.

4. **Проверь MCP-сервера:** `claude mcp list` должен показать как минимум `teletranscribe`. Идеально — также `higgsfield`, `fal-ai`, `elevenlabs`. Если каких-то нет — см. `install.md`.

5. **Если в текущей `videos_dir` есть `edit/project.md`** — прочитай последнюю сессию и подведи итог одним предложением до того как спрашивать «продолжаем?».

---

## Что это за проект

**Montazh_Agent** — AI-видеомонтажёр через диалог с Claude Code. Форк [browser-use/video-use](https://github.com/browser-use/video-use), полностью локализованный на русский, с заменой ElevenLabs Scribe → TeleTranscribe MCP (мой собственный GigaAM-стек) и добавлением:

- **Multi-source режимов:** multi-clip montage (2-10 рилз → 1 финал), audio-first (голос + видео под него), format-mix (1 source → N форматов).
- **B-roll генерации** через Higgsfield/Fal.ai MCP (Veo 3.1 / Kling 3.0 / Hailuo / Wan).
- **Полного overlay-стека:** Manim, Remotion, HyperFrames, PIL.
- **OTIO export** для совместимости с DaVinci Resolve / Final Cut Pro.

Используется как **Claude Code skill** (симлинк `~/.claude/skills/montazh-agent/`). Пользователь работает в любой `videos_dir/`, говорит «смонтируй мне рилз из этих клипов» — агент делает.

## Стек

- **Python 3.10+**, uv для деп. (см. `pyproject.toml`)
- **FFmpeg + ffprobe** — основной render engine
- **TeleTranscribe MCP** (`~/Documents/Razarabotka/TeleTranscribe/`) — транскрипция (GigaAM, диаризация, word-timestamps)
- **PySceneDetect** — shot-detection
- **sentence-transformers (CLIP)** — для audio-first match phrase → shot
- **OpenTimelineIO** — lossless EDL формат, экспорт в FCPXML / Resolve XML
- **Higgsfield MCP** — gateway к Veo 3.1 / Kling 3.0 / Hailuo / Nano Banana Pro / Flux 2 (B-roll генерация)
- **Fal.ai MCP** — альтернативный gateway (1000+ моделей)
- **ElevenLabs MCP** — TTS (для generative-only режима, не транскрипция)
- **Suno MCP** — музыкальный бэкграунд
- **Manim** (опционально) — диаграммы и математика
- **Remotion** (опционально) — React-композиции
- **HyperFrames** (опционально) — HTML/CSS/GSAP web-style анимации

## Архитектурные слои

```
┌─────────────────────────────────────────────────┐
│ Layer 0: Sources (read-only)                    │ ← пользовательские mp4/mov/m4a
├─────────────────────────────────────────────────┤
│ Layer 1: Inventory (ffprobe)                    │ ← inventory.py
├─────────────────────────────────────────────────┤
│ Layer 2: Transcript (TeleTranscribe MCP)        │ ← transcribe_mcp.py + конвертация
│         + Shots (PySceneDetect)                 │ ← scene_detect.py
├─────────────────────────────────────────────────┤
│ Layer 3: Reading view (packed.md, format-rec)   │ ← pack_transcripts.py, format_recommender.py
├─────────────────────────────────────────────────┤
│ Layer 4: EDL (JSON + OTIO)                      │ ← LLM edits, otio_export.py
├─────────────────────────────────────────────────┤
│ Layer 5a: Overlays (parallel sub-agents)        │ ← overlays/*_runner.py
│ Layer 5b: Generated B-roll (MCP)                │ ← broll_generator.py + manifest.json
│ Layer 5c: Color grade (per-segment)             │ ← grade.py
├─────────────────────────────────────────────────┤
│ Layer 6: Render (per-segment → concat → final)  │ ← render.py
├─────────────────────────────────────────────────┤
│ Layer 7: Self-eval + Memory                     │ ← timeline_view.py, project.md
└─────────────────────────────────────────────────┘
```

LLM работает в основном на Layer 3-4 (читает packed.md, пишет EDL). Layer 5-6 — механика. Layer 7 — обратная связь.

## Mode dispatch (повтор из SKILL.md)

| Исходники | Запрос | Режим |
|---|---|---|
| 1 длинный видео | «нарежь по сценарию» | **highlight-mode** |
| 2-10 коротких видео | «собери один ролик» | **multi-clip montage** |
| 1+ аудио + N видео | «голос как основа» | **audio-first** |
| Любые видео | «нужны разные форматы» | **format-mix** |
| Только сценарий | «сгенери целиком» | **generative-only** |

## 17 Hard Rules (повтор из SKILL.md)

1. Субтитры — ПОСЛЕДНИМИ в filter-цепочке.
2. Per-segment extract + lossless `-c copy` concat.
3. 30ms аудио-fades на каждой границе.
4. Оверлеи через `setpts=PTS-STARTPTS+T/TB`.
5. Master SRT с output-timeline offsets.
6. Никогда не резать внутри слова.
7. Padding 30-200ms на каждом cut-edge.
8. Word-level verbatim ASR только.
9. Кеш транскриптов per-source.
10. Parallel sub-agents для оверлеев.
11. Подтверждение стратегии до выполнения.
12. Все outputs в `<videos_dir>/edit/`.
13. Generated B-roll имеет `manifest.json`.
14. CLIP-continuity score > 0.7 между соседями.
15. C2PA watermark при наличии generated-контента.
16. OTIO + JSON-EDL — двойное сохранение state.
17. Русский + диаризация по умолчанию.

## MCP-зависимости

| MCP | Обязателен? | Зачем |
|---|---|---|
| **teletranscribe** | ✅ да | Транскрипция всех речевых треков. Без него pipeline не запустится. |
| **higgsfield** | если нужен B-roll | Generation Veo/Kling/Hailuo/Nano Banana через одну OAuth-сессию |
| **fal-ai** | опционально | 1000+ моделей; fallback и альтернатива Higgsfield |
| **elevenlabs** | только для generative-only режима | TTS-озвучка когда нет голосового исходника |
| **suno** | опционально | Музыкальный бэкграунд |

См. `install.md` для команд регистрации.

## Skills (используем глобальные)

- **`prompt-caching-playbook`** — для оптимизации токенов: транскрипты ≥10K токенов идут с `cache_control` (90% off на читы; Claude Code в апреле 2026 переключил default TTL 1h → 5min, помни про это).
- **`verification-before-completion`** — обязательная проверка перед «готово»: рендер прошёл, ffprobe длительность совпадает с EDL, self-eval ≤3 passes пройдены.
- **`systematic-debugging`** — root-cause перед фиксом FFmpeg/PIL/Manim проблем.
- **`brainstorming`** — для крупных архитектурных решений (новый режим, новый overlay engine, переезд на другой ASR).
- **`writing-plans`** — для нетривиальных задач (тип «добавь поддержку lipsync через LatentSync»).

## Конвенции

### Naming
- Helper-скрипты — snake_case Python.
- EDL поля — snake_case JSON.
- Sources — как пользователь назвал (не переименовывать).
- Сгенерированные файлы — по хешу или по `slot_NN`.

### Пути
- **Read-only:** `<videos_dir>/sources/` (или корень `videos_dir`).
- **Write:** ВСЁ в `<videos_dir>/edit/`. Никогда не пиши в `Montazh_Agent/`.
- **Cache:** `edit/transcripts/`, `edit/shots/`, `edit/clip_cache/`, `edit/generated/`.

### Error handling
- Каждый helper падает с ясным русским сообщением (`sys.exit("..."`) — без скрытых traceback'ов в normal flow.
- MCP-ошибки — флагуй пользователю с конкретикой («TT MCP вернул 402 — проверь баланс через `mcp__teletranscribe__check_balance`»).
- FFmpeg-ошибки логируй полностью (stderr), не глотай.

### Prompt caching для транскриптов
Когда передаёшь packed.md (>4K токенов) в LLM-промпт для editor sub-agent — оборачивай в `cache_control: {type: "ephemeral"}`. Это сохранит 90% стоимости при повторных итерациях с тем же транскриптом.

## Запреты (не делать)

- ❌ **Worktree** — никогда не использовать `git worktree`. Работать только в основной директории. (Глобальное правило из ~/.claude/CLAUDE.md.)
- ❌ **Автокоммиты** — не коммитить пока пользователь явно не попросил.
- ❌ **Трогать `sources/`** — read-only. Если нужна модификация (resize, преконвертация) — делать в `edit/preprocessed/`.
- ❌ **Записывать в `Montazh_Agent/`** — все session outputs идут в `<videos_dir>/edit/`. Исключение — обновление кода самого скилла.
- ❌ **Re-транскрипция кешированных source'ов** — Hard Rule #9.
- ❌ **Whisper локально** — используем TeleTranscribe MCP (GigaAM). Whisper медленный + нормализует filler-слова.
- ❌ **Sora 2 как primary t2v** — EOL 2026-09-24. Используем Kling 3.0 / Veo 3.1.

## Где что лежит

```
Montazh_Agent/
├── CLAUDE.md                      # этот файл
├── AGENTS.md → CLAUDE.md          # symlink для Codex CLI
├── SKILL.md                       # системный промпт агента (читай FIRST)
├── README.md                      # quick-start
├── install.md                     # детали установки
├── PATCH_TELETRANSCRIBE_PROMPT.md # инструкции для патча TT MCP (если ещё не задеплоен)
├── pyproject.toml
├── .env.example
├── .gitignore
├── LICENSE                        # MIT (upstream)
├── helpers/
│   ├── transcribe_mcp.py          # обёртка TT MCP → Scribe-format JSON
│   ├── inventory.py               # ffprobe всех источников
│   ├── format_recommender.py      # 2-3 варианта формата вывода
│   ├── pack_transcripts.py        # transcripts/*.json → packed.md (upstream)
│   ├── scene_detect.py            # PySceneDetect
│   ├── match_video_to_audio.py    # CLIP-матчинг для audio-first
│   ├── broll_generator.py         # инструкции для MCP B-roll
│   ├── otio_export.py             # JSON-EDL → .otio / .fcpxml
│   ├── timeline_view.py           # filmstrip + waveform PNG (upstream)
│   ├── render.py                  # FFmpeg pipeline (upstream, 660 строк)
│   ├── grade.py                   # color presets (upstream)
│   └── overlays/
│       ├── pil_subs.py            # PIL-overlays (TikTok/YouTube/Reels)
│       ├── manim_runner.py        # Manim CLI обёртка
│       ├── remotion_runner.py     # Remotion CLI обёртка
│       └── hyperframes_runner.py  # HyperFrames CLI обёртка
├── skills/
│   └── manim-video/               # references для Manim (upstream, 15 файлов)
└── static/                        # banner + svg (upstream)
```

## Связь с другими проектами

- **TeleTranscribe** (`~/Documents/Razarabotka/TeleTranscribe/`) — мой собственный ASR-стек. Транскрипция всех речевых треков идёт через его MCP (`mcp_server.py`). См. `PATCH_TELETRANSCRIBE_PROMPT.md` если MCP ещё не умеет возвращать word-timestamps в JSON.
- **Dev_Architect** (`~/Documents/Razarabotka/Dev_Architect/`) — research tool (когда нужно сравнить новые модели). Сейчас сломан, см. memory `project_research_tool_outdated`.
- **Agent_Architect** (`~/Documents/Razarabotka/Agent_Architect/`) — образец структуры агента (CLAUDE.md, .clinerules, AGENTS.md).
- **`browser-use/video-use`** — upstream, от которого форкнулись. Обновления:
  - `git remote add upstream https://github.com/browser-use/video-use` (не сделано по умолчанию — отдельный repo)
  - merge через cherry-pick конкретных коммитов helpers/render.py / helpers/grade.py.

## graphify

Этот проект подпадает под глобальное правило ~/.claude/CLAUDE.md: при изменении кода `Montazh_Agent/` запускай:
```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```
для актуализации `graphify-out/`. На первом запуске graphify-out/ ещё не существует — построится автоматически в первой сессии где код менялся.

## Принципы коммитов

- Один commit = одна фича/фикс.
- Сообщение на русском, краткое (≤72 char заголовок).
- Тело — почему, а не что.
- Если изменения трогают upstream-helpers (render.py, grade.py, pack_transcripts.py, timeline_view.py) — отметь в commit-message `[upstream-touch]` для будущего merge'а.
