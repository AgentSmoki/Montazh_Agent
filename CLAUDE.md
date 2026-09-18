# CLAUDE.md — Montazh_Agent

Контекст для Claude Code, когда работаешь внутри проекта `Montazh_Agent` или вызываешь его как skill из любой `videos_dir/`.

---

## ⚠️ ОБЯЗАТЕЛЬНО ПРИ СТАРТЕ СЕССИИ

Выполни в порядке:

1. **Прочитай `SKILL.md` целиком.** Это системный промпт агента — 20 hard rules, mode dispatch, pipeline'ы, anti-patterns. Без него ты не знаешь как работать.

2. **Определи ОС и проверь инструменты (env-doctor).** Запусти один раз за сессию:
   ```bash
   python helpers/env_doctor.py        # на Windows: py helpers\env_doctor.py
   ```
   Доктор сам определит ОС (macOS / Windows / Linux / WSL), проверит ffmpeg,
   ffprobe, python≥3.10, Pillow, шрифты, TT_API_KEY и выдаст команды установки
   **под текущую ОС** для всего, чего не хватает. Если `ok: false` — покажи
   пользователю недостающее и команду установки, и только тогда задай вопрос.
   ОС у пользователя **не спрашивай** — она детектится. Различия ОС (шелл,
   шрифты, экранирование путей в ffmpeg) — в `docs/os_profiles.md`.

3. **Если есть `graphify-out/GRAPH_REPORT.md`** — прочитай его для понимания зависимостей между helpers. (На свежем агенте может ещё не быть — построится через `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"`)

4. **Проверь `.env`:**
   - `TT_API_KEY` должен быть установлен (обязательно).
   - `HIGGSFIELD_API_KEY`, `FAL_KEY`, `ELEVENLABS_API_KEY`, `SUNO_API_KEY` — опционально, по фичам.
   - Если `.env` отсутствует — скопируй из `.env.example` и попроси у пользователя ключи.

5. **Проверь MCP-сервера:** `claude mcp list` должен показать как минимум `teletranscribe`. Идеально — также `higgsfield`, `fal-ai`, `elevenlabs`. Если каких-то нет — см. `install.md`.

6. **Если в текущей `videos_dir` есть `edit/project.md`** — прочитай последнюю сессию и подведи итог одним предложением до того как спрашивать «продолжаем?».

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

## Кроссплатформенность (macOS / Windows / Linux)

Агент работает на любой из трёх ОС. ОС определяется автоматически — **не спрашивай
пользователя**, запусти `helpers/env_doctor.py`.

**Слои:**
- `helpers/platform_paths.py` — единая точка правды: `os_name()`, `font_dirs()`,
  `find_bold_sans()`, `find_mono()`, `libass_font_name()`, `ffmpeg_bin()`. Любой
  ОС-зависимый путь берётся отсюда, не хардкодится.
- `helpers/env_doctor.py` — диагностика инструментов + команды установки под ОС.
- `docs/os_profiles.md` — полная таблица различий и Windows-грабли.

**Правило для агента при работе на Windows:**
- Шелл — PowerShell/cmd: heredoc (`<<EOF`) не работает → файлы создавай через
  `Set-Content` или `py -c`. Python вызывается `py`, не `python3`.
- Пути в ffmpeg-фильтрах (`subtitles`, `drawtext`): экранируй диск `C:\` →
  `C\:/`, либо запускай ffmpeg из папки `edit/` с относительными путями, либо
  строй путь через `Path(...).as_posix()`.
- Шрифты подставляются автоматически (Arial вместо Helvetica) — ничего руками
  прописывать не нужно.
- `videos_dir` держи неглубоко (`C:\mz\<проект>`) — лимит пути 260 символов.

**Правило при правке кода:** новый ОС-зависимый код добавляй ТОЛЬКО в
`platform_paths.py`. В helpers запрещены хардкод-пути вида `/System/Library/...`
или `C:\Windows\...`.

## 20 Hard Rules (повтор из SKILL.md — полные формулировки там)

1. Субтитры — ПОСЛЕДНИМИ в filter-цепочке.
2. Per-segment extract + lossless `-c copy` concat. Сегменты `.mov` + PCM, длительность = целое число кадров (иначе AAC-priming и округление кадров дают дрейф звука/субтитров до 1 с к концу ролика).
3. 30ms аудио-fades (`curve=hsin`) на каждой границе.
4. Оверлеи через `setpts=PTS-STARTPTS+T/TB`.
5. Master SRT с output-timeline offsets.
6. Рез ставится в тишину по звуку (`silencedetect`), транскрипт — индекс слов и субтитров; такие EDL рендерятся с `--no-snap --no-pad`. Торцы HOOK/CTA/`_clean.mov` получают `transcript`-override.
7. Запасной путь, когда чистых тишин нет, — snap к словам + smart padding по последней фонеме (30/50/120 мс). 7b — без резов внутри синтагмы. 7c — thought-guard: рез только на завершённой мысли.
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
18. `beat_type` определяет тайминг: `talk` (аудио ведёт) / `screen_read` (dwell по чтению, `effect: pushin`, голос называет экран) / `stat`.
19. Единый размер кадра для всех сегментов через cover-crop; кадр берётся из `EDL.resolution` (1080×1920, 1080×1350, 1080×1080).
20. Кроссплатформенность через `platform_paths.py` — без хардкод-путей ОС.

## MCP-зависимости

| MCP | Обязателен? | Зачем |
|---|---|---|
| **teletranscribe** | ✅ да | Транскрипция всех речевых треков. Без него pipeline не запустится. |
| **higgsfield** | если нужен B-roll | Generation Veo/Kling/Hailuo/Nano Banana через одну OAuth-сессию |
| **fal-ai** | опционально | 1000+ моделей; fallback и альтернатива Higgsfield |
| **elevenlabs** | только для generative-only режима | TTS-озвучка когда нет голосового исходника |
| **suno** | опционально | Музыкальный бэкграунд |

См. `install.md` для команд регистрации.

## Мемы и музыка (skills проекта)

- **`skills/meme-inserter/`** — вставка видео/картинок-мемов в кадр. В сценарии `[мем:🤯]` или `[мем: текст]`, или голосом «вставь мем про X». Источник KLIPY (`helpers/meme_fetch.py`, `helpers/parse_meme_cues.py`). Мем кладётся **по центру экрана** (не в угол). Кэш + manifest в `<edit>/memes/`.
- **`skills/video-music/`** — фоновая музыка: генерация инструментала (`helpers/music_gen.py generate`) + ducking под голос (`music_gen.py duck`, sidechaincompress). Провайдеры в `music_gen.py:PROVIDERS`: sunoapi.org (проверенный рабочий путь: ключ + формальный `SUNO_CALLBACK_URL`, результат поллингом), ElevenLabs Music, apiframe. Актуальный статус ключей — в `skills/video-music/SKILL.md`. Для клиентских роликов альтернатива AI-музыке — записи CC0 (Musopen на archive.org), см. сессию BMW.
- **`skills/emoji-accents/`** — эмодзи-акценты на словах-обозначениях («юрист» → ⚖, «внизу» → 👇): pop-in alpha-клипы через `helpers/emoji_overlay.py`, payoff-тайминг по word-timestamps. Шрифт — через `platform_paths.find_emoji_font()`.
- **`skills/reels-breakdown/`** — разбор рилса (своего или чужого) в раскадровку «Текст | Кадр» с метриками удержания: длина хука, смены планов в минуту, где сказано без показа. Хелпер `helpers/reel_breakdown.py`, описания кадров — через `mcp__teletranscribe__describe_image_batch`.
- **`skills/reels-first-frame/`** — первый кадр как обложка: кадр показывает тему буквально, поверх короткий заголовок; проверка читаемости и единства серии.
- **`skills/reels-cover/`** — сгенерированная тематическая обложка ролика: `helpers/cover_gen.py` (polza.ai Media API, GPT Image 2.5 по умолчанию, ключ `POLZA_API_KEY` в `.env` или `~/.claude/env_secrets/polza.env`) + заголовок-хук поверх в safe-zone; стиль серии в `cover_gen.py:STYLES` и в профиле клиента; файлы `<edit>/covers/cover_NN_XXXX.png` + `.raw.png` + manifest.

### Материалы рилс-методики
`materials_private/` — чужие исходники (конспекты, раскадровки, чужие скиллы), на которые опираются рилс-скиллы. Папка закрыта от git: репозиторий публичный, чужой контент в него не идёт. В инструкции пишем своими словами со ссылкой на источник.

### ⚠️ API-ключи — ТОЛЬКО в `.env` (никогда в git-файлах)
Ключи для KLIPY/Suno-gateways/ElevenLabs/Fal лежат в `.env` (он в `.gitignore`) + дубль в `~/.claude/env_secrets/montazh_agent.env`. **В CLAUDE.md/SKILL.md/EDL — только имена переменных**, не значения. `helpers/*` читают их из окружения/`.env` через `_load_env()`. Имена: `KLIPY_API_KEY`, `SUNOAPI_ORG_KEY`, `SUNO_CALLBACK_URL`, `ACEDATA_SUNO_KEY`, `APIFRAME_KEY`, `ELEVENLABS_API_KEY`, `FAL_KEY`. Новый ключ — добавлять в `.env` и в `.env.example` (только имя), не в инструкции.

## Профили стиля (per-client)

Стиль монтажа конкретного человека живёт в `docs/style_profiles/<имя>.md` и **перекрывает дефолты SKILL.md** (стиль субтитров, шрифты, позиции, темп, наложения). Перед монтажом роликов клиента — прочитать его профиль; если профиля нет — собрать по первому ролику и согласовать.

**NeuroBRO (Богдан)** — `docs/style_profiles/neurobro.md`. Ядро: субтитры естественными фразами, мелкий прямой гротеск без обводки, тёмным на белой футболке (или белым в свободной зоне у головы), одно слово во фразе акцентным цветом; хук-слова «за спиной» через `skills/text-behind/`; паузы ужимать, у каждого наложения вход/выход; мемы и врезки — из вариантов на выбор; без музыки; мат остаётся; CTA-карточка со словом только там, где он сам зовёт.

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
├── pyproject.toml
├── .env.example
├── .gitignore
├── LICENSE                        # MIT (upstream)
├── docs/                          # доп. документация (не точки входа)
│   ├── os_profiles.md             # различия macOS/Windows/Linux + Windows-грабли
│   ├── PATCH_TT_DESCRIBE_IMAGE_PROMPT.md  # спека патча describe_image для TT MCP (задеплоен)
│   └── vlipsy_partnership_request.md      # черновик письма на API-доступ Vlipsy
├── research/                      # исследовательские заметки по стеку
│   ├── 03_research_stack.md       # обоснование lean-стека (Gemini Deep Research)
│   ├── 04_vps_telegram_takopi.md
│   └── 05_word_boundary_methodology_findings.md
├── helpers/                       # ВЕСЬ исполняемый код (только .py)
│   ├── platform_paths.py          # кроссплатформенные пути/шрифты/бинари (ОС-абстракция)
│   ├── env_doctor.py              # диагностика инструментов под ОС (Шаг 0)
│   ├── transcribe_mcp.py          # обёртка TT MCP → Scribe-format JSON
│   ├── inventory.py               # ffprobe всех источников
│   ├── format_recommender.py      # 2-3 варианта формата вывода
│   ├── pack_transcripts.py        # transcripts/*.json → packed.md (upstream)
│   ├── scene_detect.py            # PySceneDetect
│   ├── match_video_to_audio.py    # CLIP-матчинг для audio-first
│   ├── clip_onnx.py               # ONNX-инференс CLIP (audio-first match)
│   ├── analyze_reels.py           # эвристики анализа коротких видео
│   ├── content_factory_presets.py # 8 пресетов форматов (контент-завод)
│   ├── broll_generator.py         # инструкции для MCP B-roll
│   ├── otio_export.py             # JSON-EDL → .otio / .fcpxml
│   ├── timeline_view.py           # filmstrip + waveform PNG (upstream)
│   ├── render.py                  # FFmpeg pipeline (upstream)
│   ├── grade.py                   # color presets (upstream)
│   │   # — word-boundary / editable-transcript стек:
│   ├── build_editable_transcript.py   # JSON → редактируемый markdown-транскрипт
│   ├── parse_editable_transcript.py   # обратно: правки → EDL-cuts
│   ├── snap_to_word.py            # привязка cut'ов к границам слов (запасной путь, Hard Rule #7)
│   ├── apply_padding.py           # padding 30-200ms на cut-edge (Hard Rule #7)
│   ├── check_thought_boundaries.py    # проверка цельности мысли на стыке
│   ├── detect_audio_spikes.py    # детект аудио-всплесков для чистых cut'ов
│   ├── validate_edl.py           # валидатор EDL перед рендером
│   ├── editor_sub_agent_brief.py # генератор brief'а для editor sub-agent
│   │   # — quality-gates (заимствовано из OpenMontage, реализовано с нуля):
│   ├── delivery_promise.py       # гейт «обещали motion-led → не отдать статику»
│   ├── slideshow_risk.py         # скорер монотонности/«анимированного PowerPoint»
│   ├── post_render_review.py     # авто-санити финала (чёрные кадры/тишина/длительность)
│   │   # — мемы и музыка:
│   ├── meme_fetch.py             # фетч мемов (KLIPY/Vlipsy)
│   ├── parse_meme_cues.py        # парсинг [мем:...] cue'ов из сценария
│   ├── music_gen.py              # генерация инструментала + ducking
│   └── overlays/
│       ├── pil_subs.py            # PIL-overlays (TikTok/YouTube/Reels)
│       ├── manim_runner.py        # Manim CLI обёртка
│       ├── remotion_runner.py     # Remotion CLI обёртка
│       └── hyperframes_runner.py  # HyperFrames CLI обёртка
├── skills/                        # под-скиллы проекта
│   ├── manim-video/               # references для Manim (upstream)
│   ├── meme-inserter/             # вставка мемов в кадр
│   ├── emoji-accents/             # эмодзи-акценты на словах
│   ├── text-behind/               # текст за спиной (маска MediaPipe)
│   ├── reels-breakdown/           # разбор рилса в раскадровку + метрики
│   ├── reels-first-frame/         # первый кадр-обложка с заголовком
│   ├── reels-cover/               # сгенерированная обложка серии (polza.ai + хук)
│   └── video-music/               # фоновая музыка + ducking
├── materials_private/             # чужие исходники методик (вне git)
├── test_sessions/                 # тестовые монтажи (gitignored, кроме README+шаблона)
├── videos_dir/                    # личные монтажи пользователя (gitignored целиком)
└── static/                        # banner + svg (upstream)
```

## Связь с другими проектами

- **TeleTranscribe** (`~/Documents/Razarabotka/TeleTranscribe/`) — мой собственный ASR-стек. Транскрипция всех речевых треков идёт через его MCP (`mcp_server.py`). MCP уже отдаёт word-timestamps через `transcribe_file_json` / `transcribe_url_json` (патч задеплоен). `docs/PATCH_TT_DESCRIBE_IMAGE_PROMPT.md` — спека отдельного патча `describe_image` для vision-кадров.
- **Dev_Architect** (`~/Documents/Razarabotka/Dev_Architect/`) — research tool (когда нужно сравнить новые модели или цены): CLI `research_tool/research.py "<задача> <технология> <год>?" --engine perplexity|gemini|deep` и глобальный MCP `research` (`mcp__research__web_research`, `mcp__research__quick_search`). Работает с 2026-06-28. Факты о моделях и ценах проверяй двумя источниками: Gemini отвечает без веба, Perplexity ходит в веб.
- **Agent_Architect** (`~/Documents/Razarabotka/Agent_Architect/`) — образец структуры агента (CLAUDE.md + AGENTS.md symlink).
- **`browser-use/video-use`** — upstream, от которого форкнулись. Обновления:
  - `git remote add upstream https://github.com/browser-use/video-use` (не сделано по умолчанию — отдельный repo)
  - merge через cherry-pick конкретных коммитов helpers/render.py / helpers/grade.py.

## Quality-gates (заимствовано из OpenMontage)

Из [OpenMontage](https://github.com/calesthio/OpenMontage) (лицензия **AGPLv3**) взяты 5 идей и реализованы **с нуля по описанию** (код их репозитория не копировался — AGPL не загрязняет нашу базу):

1. **MMR-диверсификация** в `match_video_to_audio.py` (`--diversity`, default 0.3) — соседние фразы не липнут к одному shot'у.
2. **`delivery_promise.py`** — гейт соответствия режима результату (motion-led не падает молча в статику). Вшит в `render.py` (`--mode`, мягкое предупреждение).
3. **`slideshow_risk.py`** — скорер монотонности по 6 измерениям + детект generic/AI-фраз. Вшит в `render.py`.
4. **`post_render_review.py`** — авто-санити финала (чёрные кадры / тишина / клиппинг / длительность). Вшит в конец `render.py` (`--no-post-review`).
5. **Мелочи:** `music_gen.py bestwindow` (energy-offset по ebur128) + `pil_subs.py --corrections` (словарь ASR-правок субтитров).

Новые флаги `render.py`: `--mode <режим>`, `--no-quality-gates`, `--no-post-review`. Гейты мягкие — предупреждают, не блокируют рендер.

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
