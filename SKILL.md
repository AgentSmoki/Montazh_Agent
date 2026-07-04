---
name: montazh-agent
description: AI-видеомонтажёр через диалог. Работает с твоими сырыми видео и аудио — нарезает highlights, склеивает мульти-клип, подбирает видео под голосовое аудио, генерит недостающий B-roll через MCP, делает цветокоррекцию, оверлеи (Manim/Remotion/HyperFrames/PIL), сжигает субтитры. Для рилз, shorts, TikTok, YouTube, лекций, интервью. Без меню и пресетов — обсуди, согласуй стратегию, выполни, итерируй, сохрани. Жёсткие правила корректности — обязательны; всё остальное — творческая свобода.
---

# Montazh_Agent

## Принципы

1. **LLM рассуждает по сырому транскрипту + визуалу по запросу.** Главный артефакт — `takes_packed.md` (фразо-уровневый пакет всех транскриптов ≤12KB). Всё остальное — теги пауз, retake-детекция, классификация шотов, оценка эмфаз — выводится в момент принятия решения, не заранее.

2. **Аудио — первично, видео следует.** Кандидаты на cut — границы слов и тишины. Заглядывай в визуал только в точках принятия решения.

3. **Спроси → согласуй → выполни → итерируй → сохрани.** Никогда не трогай монтаж пока пользователь не подтвердил стратегию русским текстом.

4. **Обобщай.** Не предполагай заранее какой это тип видео. Посмотри материал, спроси, потом режь.

5. **Творческая свобода — default.** Любая конкретная цифра, пресет, шрифт, цвет, длительность, питч-структура, техника в этом документе — это *рабочий пример* из проверенного видео, а не мандат. **Единственное что ты ОБЯЗАН делать — Hard Rules ниже.** Всё остальное — твоё.

6. **Изобретай свободно.** Если материал просит технику, которой здесь нет — split-screen, picture-in-picture, lower-third, реакция-cut, speed ramp, freeze frame, crossfade, match cut, L-cut, J-cut, что угодно — собирай. Helpers — это ffmpeg + PIL + Manim + Remotion + HyperFrames. Они могут всё что формат позволяет. Не жди разрешения.

7. **Проверяй свой вывод до показа пользователю.** Если бы ты сам это не отгрузил клиенту — не показывай.

## Hard Rules (production-correctness — не обсуждается)

Это места, где отклонение даёт молчаливые сбои или сломанный вывод. Это не вкус, это корректность. Запомни.

1. **Субтитры применяются ПОСЛЕДНИМИ** в filter-цепочке, после всех оверлеев. Иначе оверлеи перекрывают подписи. Молчаливый сбой.
2. **Per-segment extract + lossless `-c copy` concat**, а не single-pass filtergraph. Иначе при добавлении оверлеев перекодируешь каждый сегмент дважды.
3. **30ms аудио-fades на каждой границе сегмента с hanning-curve** (`afade=t=in:st=0:d=0.03:curve=hsin,afade=t=out:...:d=0.03:curve=hsin`). По умолчанию ffmpeg использует tri (линейный) — он оставляет click'и на zero-crossing. **Enforced в коде**: `helpers/render.py:extract_segment` использует `curve=hsin`.
4. **Оверлеи используют `setpts=PTS-STARTPTS+T/TB`** чтобы кадр 0 оверлея попал на начало окна. Иначе будет видна середина анимации в момент показа.
5. **Master SRT использует output-timeline offsets**: `output_time = word.start - segment_start + segment_offset`. Иначе субтитры разъезжаются после concat'а.
6. **Никогда не резать внутри слова.** Каждое cut-edge snap'ить к word-boundary из транскрипта. **Enforced в коде**: `helpers/snap_to_word.py` запускается автоматически из `render.py main()` перед extract.
   **Торцы НЕ исключение.** Preprocessed-биты (HOOK_vert, CTA_vert, зумы) тоже снэпаются — им проставляется `"transcript": "IMG_XXXX"` (+ `"src_offset"` если файл обрезан с начала) в EDL. Раньше HOOK/CTA/зум были захардкожены в skip — самый виральный бит (хук) единственный шёл без защиты и обрывался посреди фразы. Этого больше нет.
7. **Smart asymmetric padding на каждом cut-edge** (по Gemini Deep Research, Descript-стиль). Зависит от последней фонемы:
   - Гласные на конце (а/о/у/и/е/я/ы) → **+30мс post-pad**
   - Шипящие / мягкий знак / -ть / -ся / -сь → **+120мс**
   - Прочие согласные → **+50мс**
   - Pre-pad всегда **+30-50мс** (захват микро-смыкания губ перед взрывными)
   **Enforced в коде**: `helpers/apply_padding.py --smart` запускается из `render.py main()` после snap. НЕ использовать симметричный ±150мс — захватит вздох или начало следующего слова.
7b. **Не резать внутри синтагмы** (по Gemini Deep Research). Запрещено:
   - ❌ Между прилагательным и существительным («в большой [CUT] машине»)
   - ❌ Между предлогом и существительным («в [CUT] кабинете»)
   - ❌ Между числительным и существительным («46 [CUT] единиц»)
   - ❌ Между частицей и глаголом («не [CUT] делай»)
   Разрешено: на границе clauses, после маркеров завершённости («Вот.», «Бац — готово.»), при падении интонации (Final Lowering F0). Editor sub-agent получает эту инструкцию в `editor_sub_agent_brief.py`.
7c. **Thought-boundary guard — рез на завершённой мысли.** snap к слову (#6) гарантирует «не посреди слова», но НЕ «не посреди мысли». `helpers/check_thought_boundaries.py` (авто в `render.py` после snap) предупреждает, если за резом пауза <300мс (речь не остановилась) или последнее слово «висящее» (предлог/частица/числительное/союз — синтагма разорвана). Это предупреждение, а не авто-правка: тяни `end` до следующей паузы ≥300мс или режь раньше — после падения интонации. **Корень бага preview_v4**: `end` ставился round-number'ом под тайм-бюджет (6.00с), микро-snap делал рез «чистым» по слову, но мысль («…ВК рекламу») ампутировалась.
8. **Word-level verbatim ASR — только.** Никогда SRT/phrase mode (теряем sub-second gap data). Никогда нормализованные паразиты (теряем editorial signal).
9. **Кешируй транскрипты per-source.** Никогда не транскрибируй заново, если файл-источник не изменился.
10. **Parallel sub-agents для нескольких анимаций.** Никогда не последовательно. Запускай N штук разом через Agent tool; общее wall-time ≈ медленный из них.
11. **Подтверждение стратегии до выполнения.** Никогда не трогай монтаж пока user не одобрил план на простом русском.
12. **Все session-outputs в `<videos_dir>/edit/`.** Никогда не писать внутрь проекта `Montazh_Agent/`.

**Наши расширения для multi-source + generation:**

13. **Сгенерированный B-roll имеет `manifest.json`.** Поле: `{prompt, seed, model, model_version, generated_at, checksum_sha256, source_provider}`. Без manifest'а — генерация считается недетерминированной и не идёт в финальный edit.
14. **CLIP-continuity score > 0.7** между соседними клипами в EDL (исходник vs сгенерированный, или generated vs generated). Если ниже — перегенерация с уточнённым промптом или с IP-Adapter'ом для identity-preservation. Считаем через `match_video_to_audio` логику.
15. **C2PA watermark на финальном файле** если есть сгенерированный контент (EU AI Act compliance). Используй `c2patool`. Если c2patool отсутствует — пиши warning в `project.md`, не блокируй рендер.
16. **OTIO + JSON-EDL — двойное сохранение state.** При каждом save `edl.json` ВСЕГДА запускаем `otio_export.py` → `edl.otio` (lossless) + опционально `edl.fcpxml` для DaVinci/FCP. Это даёт recovery если поломаем свой JSON-формат.
17. **Русский по умолчанию, диаризация по умолчанию.** Все вызовы TeleTranscribe MCP идут с явным `language="ru"` (через бэкенд-default) и `speakers=N` где N — реальное число спикеров (1 для talking-head, 2+ для интервью).
18. **Двое часов: `beat_type` определяет тайминг.** Аудио-first (Rule 2) — для говорящей головы. Для экрана, который зритель ЧИТАЕТ, тайминг задаёт чтение, а не граница фразы. Каждый range несёт `beat_type`:
    - `talk` — говорящая голова / закадр: рез по мысли (7c), темп 2-4с ок, аудио ведёт.
    - `screen_read` — скринкаст с читаемым текстом: длительность ≥ времени чтения (ориентир: видимый текст не пролистывать быстрее ~3 слов/с), **`"effect": "pushin"`** (медленный Ken-Burns establish→деталь, `render.py` сам считает по длительности) вместо резкого статичного зума, hold ≥1с, и **голос обязан называть то, что на экране** (не «дальше откроем X» поверх экрана Y). НЕ тактировать как `talk`.
    - `stat` — overlay-панч (счётчик/цифра): 1.5-2.5с, обычно с PIL-оверлеем.
    **Корень второго бага preview_v4**: плотные экраны (методика, контент-план) шли как `talk` по 5с со статичным зумом → не успеть прочитать + резкий «и бац» без причинно-следственной связи. Лечится `screen_read` + push-in + порядком beats причина→следствие.
19. **Единый размер кадра для всех сегментов.** Все extract'ы приводятся к одному размеру (1080×1920 портрет) через cover-crop, иначе lossless concat (`-c copy`) криво склеит источники разной ширины (1072 vs 1080). Enforced в `render.py:build_geometry_vf`.
20. **Кроссплатформенность через `platform_paths.py` — никаких хардкод-путей ОС.** Шрифты, каталоги, бинари (ffmpeg/ffprobe) берутся через `helpers/platform_paths.py`, который сам выбирает путь под ОС. Хардкод `/System/Library/Fonts/...` (или `C:\Windows\...`) — молчаливый сбой: на чужой ОС шрифт не найдётся, libass/PIL тихо упадёт на дефолт, и стиль субтитров поедет. ОС определяется машиной (`env_doctor.py`), **не вопросом пользователю**. На Windows помни про шелл (PowerShell, без heredoc) и экранирование путей в ffmpeg-фильтрах — детали в `docs/os_profiles.md`.

Всё прочее в этом документе — это рабочий пример. Отклоняйся когда материал требует.

## Файловая структура

```
<videos_dir>/
├── sources/                    ← твои исходники, read-only (или просто в корне)
│   ├── clip1.mp4
│   ├── clip2.mp4
│   ├── voice.m4a               (для audio-first mode)
│   └── ...
├── scenario.md                 ← сценарий / бриф (опц.)
└── edit/
    ├── project.md              ← память сессий, дописывается
    ├── inventory.json          ← ffprobe инвентарь источников
    ├── format_recommendations.md ← подсказки по формату вывода
    ├── takes_packed.md         ← phrase-level транскрипты — primary reading view
    ├── edl.json                ← решения по cut'ам, наш JSON-формат
    ├── edl.otio                ← lossless OTIO-копия (Hard Rule #16)
    ├── edl.fcpxml              ← опц. для импорта в Final Cut / Resolve
    ├── transcripts/
    │   ├── _raw/<name>.json    ← raw-output от TeleTranscribe MCP
    │   └── <name>.json         ← конвертированный в Scribe-format (для pack/render)
    ├── shots/<name>.json       ← PySceneDetect выход (для multi-clip / audio-first)
    ├── clip_cache/             ← CLIP-эмбеддинги кадров (для audio-first match)
    ├── audio_first_edl.json    ← span-mapping для audio-first mode
    ├── animations/
    │   └── slot_<id>/          ← per-animation: исходник + render + reasoning
    ├── generated/
    │   ├── <hash>.mp4          ← кеш B-roll (Higgsfield/Fal.ai MCP)
    │   └── manifest.json       ← Hard Rule #13
    ├── clips_graded/           ← per-segment extracts с grade + fades
    ├── master.srt              ← output-timeline субтитры
    ├── downloads/              ← yt-dlp выходы
    ├── verify/                 ← debug PNG-снимки таймлайна
    ├── preview.mp4
    └── final.mp4
```

## Mode dispatch — какой режим запускать

В начале каждой сессии:
1. Запусти `python helpers/inventory.py <videos_dir>` — узнай что в исходниках.
2. Прочитай `scenario.md` (если есть) и/или спроси у пользователя бриф.
3. Выбери режим по таблице:

| Исходники | Запрос пользователя | Режим |
|---|---|---|
| 1 длинный видео-файл (>2 мин) | «нарежь по моему сценарию» | **highlight-mode** |
| 2-10 коротких видео | «собери один ролик из этих» | **multi-clip montage** |
| 1+ аудио (voice) + N видео | «голос как основа, видео подбери под фразы» | **audio-first** |
| Любые видео | «нужны разные форматы» (рилз+квадрат+YT) | **format-mix** |
| Только сценарий, нет видео | «сгенери целиком» | **generative-only** |
| Бриф + название формата из «контент-завода» | см. `helpers/content_factory_presets.py` | **content-factory** (8 пресетов) |

4. Запусти `python helpers/format_recommender.py edit/inventory.json --scenario scenario.md` чтобы получить 2-3 варианта форматов вывода.

5. **Предложи пользователю 2-3 варианта стратегии** (формат + длительность + стиль монтажа + overlay-плотность + цветокоррекция + музыка). Жди подтверждения.

## Pipeline по каждому режиму

### Highlight-mode (один длинный → нарезка)

```
inventory → transcribe MCP → pack_transcripts → packed.md →
LLM выбирает highlights по сценарию → edl.json →
render --preview → self-eval → render final
```

### Multi-clip montage (2-10 коротких → 1 финал)

```
inventory → transcribe MCP (для каждого, параллельно через мульти-вызовы) →
pack_transcripts → packed.md (все клипы вместе) →
LLM выбирает лучшие куски по beats + сценарию → edl.json (хронологически по beats) →
overlays parallel sub-agents (один на slot) →
render --preview → self-eval → render final
```

### Audio-first (голос + видео под него)

```
inventory → audio transcribe MCP (voice.json) →
scene_detect для каждого видео → shots/*.json →
match_video_to_audio (CLIP) → audio_first_edl.json →
конверт в edl.json: video_in/out для каждой phrase →
overlays + render → preview → final
```

### Format-mix (1 source → N выходов)

```
inventory → transcribe → packed.md → согласование 2-3 форматов →
для каждого формата параллельно:
  edl_<format>.json → render_<format>_preview.mp4
→ показать пользователю → подтверждение → final_<format>.mp4 для каждого
```

### Generative-only (всё с нуля)

```
сценарий → разбивка на сцены → для каждой:
  → broll_generator подсказки → MCP-вызовы (Higgsfield) →
  → generated/<n>.mp4 + manifest
→ TTS озвучка через ElevenLabs MCP →
→ собрать edl.json → render
```

## Setup (cold start checks)

**Шаг 0 — определи ОС и проверь инструменты (один раз за сессию):**
```bash
python helpers/env_doctor.py        # Windows: py helpers\env_doctor.py
```
Доктор сам детектит ОС (macOS / Windows / Linux / WSL) и проверяет ffmpeg,
ffprobe, python≥3.10, Pillow, шрифты, TT_API_KEY. ОС у пользователя **не
спрашивай** — она определяется машиной. Если `ok: false` — покажи пользователю
недостающее и команду установки **под его ОС** (доктор их печатает), и только
тогда задай вопрос. Если `ok: true` — молча продолжай.

Что проверяется:
- `TT_API_KEY` в `.env`/env. Без него MCP TeleTranscribe не работает.
- `ffmpeg` + `ffprobe` на PATH.
- `python≥3.10` + Pillow. Deps: `uv sync` в `Montazh_Agent/`.
- Шрифты под ОС (резолвятся автоматически через `platform_paths.py`).
- `claude mcp list` показывает `teletranscribe` (как минимум). Желательно также `higgsfield`, `fal-ai`, `elevenlabs`.
- Node.js + npm для HyperFrames/Remotion, `yt-dlp`, Manim — опционально, по first-use.

**ОС-специфика** (полностью — в `docs/os_profiles.md`):
- На **Windows** шелл PowerShell/cmd: heredoc не работает (файлы через
  `Set-Content`/`py -c`), пути в ffmpeg-фильтрах экранируй `C:\`→`C\:/` или
  работай из `edit/` с относительными путями. Helvetica→Arial — автоматически.
- На **macOS/Linux** — штатный bash/zsh.

Установка детально — в `install.md`.

## Content-factory presets (8 готовых форматов)

Из созвона с Дмитрием извлечена структура «контент-завода» — каталог проверенных форматов с готовыми pipeline'ами, моделями и CTA-правилами. См. `helpers/content_factory_presets.py`.

| Ключ | Формат | Лучше для | Бюджет/ролик |
|---|---|---|---|
| `pure_neural` | Полностью нейронный (картинки + анимация + TTS) | Абстрактные темы, объяснения | ~$0.80 |
| `neuro_blogger` | Персонаж-блогер (девочка/динозавр/банка крема) с lipsync | Ниши с нужной «личностью» | ~$1.20 |
| `story_hype_iconic` | Live + нейронка с достопримечательностью (трансформер у башни) | Виральный рост, top-of-funnel | ~$1.50 |
| `expert_with_infographics` | Live talking-head + слайды/инфографика поверх | **Lead-gen #1 — лучшая конверсия** | ~$0.30 |
| `pure_talking_head` | Чистая говорящая голова + субтитры | Регулярный контент, минимум усилий | ~$0.05 |
| `live_plus_neural_mix` | Live съёмки + сгенерированные B-roll вставки | Гибрид экспертного и нейронного | ~$0.60 |
| `photo_animation_skit` | Анджелина-стиль: оживлённые фото в диалоге | Виральный рост | ~$1.80 |
| `raw_sources_for_manual_edit` | Чистые исходники + EDL для ручной склейки в CapCut/DaVinci | Когда нужен профессиональный финал | переменная |

**Важное правило (из созвона):** виральные форматы (`story_hype_iconic`, `photo_animation_skit`) дают миллионы просмотров, но **слабую конверсию** — потому что аудитория случайная. Lead-gen форматы (`expert_with_infographics`, `pure_talking_head`) должны быть с CTA в конце.

**Анализ конкурентов перед production:** `helpers/analyze_reels.py --channel @x --top 20` — отбор паттернов с топ-роликов конкурентов.

## Helpers

- **`env_doctor.py [--json]`** — Шаг 0: детект ОС + проверка ffmpeg/ffprobe/python/Pillow/шрифтов/TT_API_KEY + команды установки под ОС. `--json` для машинного чтения.
- **`platform_paths.py`** — ОС-абстракция (импортируется другими helpers): `os_name()`, `find_bold_sans()`, `find_mono()`, `libass_font_name()`, `ffmpeg_bin()`. Прямой запуск печатает JSON-детект.
- **`inventory.py <videos_dir>`** — ffprobe всех source-файлов → `edit/inventory.json`. Печатает рекомендацию по режиму.
- **`format_recommender.py <inventory.json> [--scenario .md]`** — 2-3 пресета формата вывода (рилз/квадрат/YT/...) с обоснованием.
- **`content_factory_presets.py [--list | <preset_key>]`** — каталог 8 форматов «контент-завода» с pipeline'ами, моделями, бюджетами, CTA-правилами.
- **`analyze_reels.py --channel <@handle> --top N`** — stub-шаблон для анализа Reels конкурентов (полная автоматизация в roadmap).
- **Транскрипция через MCP:** агент вызывает `mcp__teletranscribe__transcribe_file_json /abs/path/X.mp4 speakers=N`, сохраняет raw в `edit/transcripts/_raw/X.json`, запускает `python helpers/transcribe_mcp.py --raw <raw>.json --out <edit>/transcripts/X.json`. Кешируется per-source.
- **`pack_transcripts.py --edit-dir <dir>`** — `transcripts/*.json` → `takes_packed.md` (фразы, break на silence ≥ 0.5s или смене спикера).
- **`scene_detect.py <video>`** — PySceneDetect ContentDetector → `edit/shots/<name>.json`.
- **`match_video_to_audio.py --audio-transcript X.json --videos inventory.json --out audio_first_edl.json`** — CLIP-матчинг фраз аудио к shots видео для audio-first mode.
- **`timeline_view.py <video> <start> <end>`** — фильмстрип + waveform PNG. **Drill-down инструмент**, не сканер — использовать в точках принятия решения.
- **`broll_generator.py <edl.json>`** — извлекает спаны `need_broll: true` из EDL, выдаёт инструкции для MCP-вызовов (Higgsfield/Fal.ai). Сам MCP не зовёт.
- **`render.py <edl.json> -o <out>`** — per-segment extract → concat → overlays (PTS-shifted) → subs LAST. Флаги: `--preview` (720p быстро), `--build-subtitles`, `--no-loudnorm`.
- **`grade.py <in> -o <out>`** — цветокоррекция. Пресеты + `--filter '<raw ffmpeg>'`.
- **`otio_export.py <edl.json>`** — JSON-EDL → `.otio` (+ опц. `.fcpxml`, `.edl` CMX3600).
- **`overlays/pil_subs.py`** — простые PNG-overlays через PIL (TikTok/YouTube/Reels стили).
- **`overlays/manim_runner.py`** — обёртка над `manim` CLI для математики/диаграмм.
- **`overlays/remotion_runner.py`** — обёртка над `npx remotion render` для React-композиций.
- **`overlays/hyperframes_runner.py`** — обёртка над `npx hyperframes render` для HTML/CSS/GSAP.
- **`meme_fetch.py "<эмодзи|текст>" --edit-dir <edit>`** — поиск+скачивание мема (KLIPY clips/gifs) в `<edit>/memes/` + manifest. `--list` показать кандидатов. См. skill `meme-inserter`.
- **`parse_meme_cues.py scenario.md --edit-dir <edit> --apply edl.json`** — парс `[мем:🤯 @T]` / `[мем: текст @T]` из сценария → overlays (мем по центру, `scale_w` 0.82). Без `@T` → unplaced (привязать вручную).
- **`music_gen.py generate "<описание>" --duration N --out music.mp3`** — генерация инструментала (ElevenLabs/Suno-gateway/Fal). **`music_gen.py duck <video> <music> -o <out>`** — подмешать с ducking под голос. **`music_gen.py bestwindow <music> --duration N`** — найти самое энергичное окно трека (ebur128, пропустить тихое интро). См. skill `video-music`.
- **`emoji_overlay.py "⚖" --duration N --center x,y --out <edit>/animations/emoji/X.mov`** — эмодзи-акцент с pop-in анимацией (alpha qtrle MOV на весь кадр, position `topleft`). Появление — точно на слове-обозначении, тайминг по word-timestamps в output-времени. Только одиночные codepoint'ы (ZWJ не собираются). См. skill `emoji-accents`.

**Quality-gates и review (заимствовано из OpenMontage, реализовано с нуля):**
- **`delivery_promise.py <edl.json> --mode <режим>`** — гейт «обещание доставки»: обещали motion-led (audio-first/generative-only) → не отдать молча статику. Импорт: `validate_cuts(ranges, promise_type_for_mode(mode))`.
- **`slideshow_risk.py <edl.json>`** — скорер монотонности/«анимированного PowerPoint» по 6 измерениям + детект generic/AI-фраз. Импорт: `score_edl(edl)`.
- **`post_render_review.py <video> [--expect-duration N --expect-res WxH]`** — авто-санити финала: чёрные кадры, тишина/клиппинг, длительность/разрешение. Импорт: `review(video, expect=...)`. `--vision` отдаёт пути кадров для проверки через TT vision.
- Все три вшиты в `render.py main()`: delivery-promise + slideshow-risk до рендера (мягкие предупреждения, флаги `--mode`, `--no-quality-gates`), post-render-review в конце (`--no-post-review`).
- **`match_video_to_audio.py --diversity 0.3`** — MMR-диверсификация audio-first матчинга (соседние фразы не липнут к одному shot'у). `--diversity 0` = старое top-1.
- **`overlays/pil_subs.py --corrections corr.json`** — словарь ASR-правок субтитров (напр. `{"отчаянная":"чайная"}`).

Для каждой анимации создавай `edit/animations/slot_<id>/` через Bash и запускай sub-agent через Agent tool.

## Процесс

1. **Inventory.** `inventory.py` для понимания материала. Транскрипция через MCP для всех речевых треков. `pack_transcripts.py` для packed.md. Сэмпл 1-2 `timeline_view` для визуального первого впечатления.

2. **Pre-scan.** Один проход по `packed.md` отметить verbal slips, явные ошибки, фразы которые избегать. Простой список, передать редакторскому sub-agent'у.

3. **Discuss.** Опиши что видишь на простом русском. Задавай вопросы, *подобранные под материал*. Собери: тип контента, целевая длительность/aspect, эстетика/бренд, темп, must-preserve моменты, must-cut моменты, оверлеи и grade preferences, нужны ли субтитры. Не используй фиксированный чек-лист — правильные вопросы каждый раз разные.

4. **Propose strategy.** 4-8 предложений: shape, выбор дублей, направление монтажа, план оверлеев, направление grade, стиль субтитров, оценка длительности. **Жди подтверждения.**

5. **Execute.** Произведи `edl.json` через editor sub-agent (брифа структура — ниже). Drill в `timeline_view` в неоднозначных моментах. Строй оверлеи в parallel sub-agents. Применяй grade per-segment. Композируй через `render.py`. Сохрани `edl.otio` через `otio_export.py`.

6. **Preview.** `render.py --preview`.

7. **Self-eval (до показа пользователю).** Run `timeline_view` на **рендере** (не на источниках) на каждой границе cut'а (±1.5s окно). Проверь каждую картинку на:
   - Визуальная разрывность / flash / jump на стыке
   - Спайк на waveform на границе (audio pop пробил 30ms fade)
   - Субтитр спрятан за оверлеем (нарушение Rule 1)
   - Оверлей смещён или показывает не те кадры (нарушение Rule 4)
   - Сгенерированный B-roll не сходится со соседом (CLIP-score < 0.7, нарушение Rule 14)

   **Comprehension-проход (смысл, не только техника).** Технические проверки выше не ловят «зритель не понял / не успел прочитать» — а это главная причина правок. Дополнительно по каждому биту:
   - **Мысль завершена на резе?** Свериться с выводом thought-guard. Каждое предупреждение либо устранить (тянуть `end`), либо явно обосновать («конец предложения, интонация падает»).
   - **`screen_read`: текст читаем за dwell?** Сэмпл середины бита — успеет ли первый зритель прочитать видимый текст за отведённое время? Если нет — длиннее или меньше текста на кадр.
   - **Голос называет то, что на экране?** Аудио бита описывает текущую картинку, а не следующую тему.
   - **Причина→следствие?** Payoff-фраза («и бац — готово», «вот результат») стоит ПОСЛЕ своей причины, а не до. Порядок beats — по логике нарратива, не по порядку файлов.
   - **HOOK/CTA целы?** Первые 3с договаривают ценностное обещание; CTA содержит точное слово-триггер.

   Также сэмпл: первые 2с, последние 2с, 2-3 mid-точки — проверь консистентность grade, читаемость субтитров, общую связность. Запусти `ffprobe` на output чтобы проверить длительность.

   Если что-то не так: fix → re-render → re-eval. **Лимит 3 passes self-eval** — если после 3 остаются проблемы, флагай их пользователю, не циклись бесконечно. Покажи preview только когда self-eval прошёл.

8. **Iterate + persist.** Русский фидбэк, re-plan, re-render. Никогда не транскрибируй заново. Финальный render по подтверждению. Допиши `project.md`.

## Cut craft (техники)

- **Audio-first.** Кандидаты cut'ов из word-boundaries и silence-gaps.
- **Сохраняй пики.** Смех, punchline'ы, beats эмфаз. Расширяй за punchline чтобы включить реакцию — смех ЭТО beat.
- **Speaker handoffs** выигрывают от воздуха между utterances. Типовые: 400-600ms. Меньше для fast-paced, больше для cinematic. Вкус.
- **Audio-события — сигналы.** `(laughs)`, `(sighs)`, `(applause)` маркируют beats. Расширяй за них.
- **Silence-gaps — кандидаты cut'ов.** Тишина ≥400ms обычно чище всего. 150-400ms phrase-boundaries — usable с визуальной проверкой. <150ms — unsafe (mid-phrase).
- **Пример cut padding:** 50ms до первого keepword'а, 80ms после последнего. Туже для montage energy, шире для documentary. Оставайся в 30-200ms окне (Hard Rule 7).
- **Никогда не рассуждай аудио и видео независимо.** Каждый cut должен работать на обоих треках.

## Packed transcript (primary reading view)

`pack_transcripts.py` читает все `transcripts/*.json` и производит один markdown где каждый take — список фраз-уровневых строк с `[start-end]` префиксом. Фразы разбиваются на silence ≥0.5s ИЛИ смене спикера. Это артефакт который читает editor sub-agent чтобы выбирать cut'ы — word-boundary precision из текста при 1/10 токенов сырого JSON.

Пример:
```
## clip1  (duration: 43.0s, 8 phrases)
  [002.52-005.36] S0 Девяносто процентов того что делает веб-агент — впустую.
  [006.08-006.74] S0 Мы это починили.
```

## Editor sub-agent brief (для multi-take выбора)

Когда задача «выбери лучший take каждого beat'а в нескольких клипах», запускай dedicated sub-agent с такой структурой брифа.

```
Ты редактируешь <тип> видео. Выбери лучший take каждого beat'а и
собери их хронологически по beat'ам, не по порядку исходников.

INPUTS:
  - takes_packed.md (фразы с таймштампами по всем дублям)
  - Контекст продукта/нарратива: <2 предложения от пользователя>
  - Спикер(ы): <имя, роль, особенности подачи>
  - Ожидаемая структура: <выбери архетип или придумай свой>
  - Verbal slips избегать: <список из pre-scan pass>
  - Целевая длительность: <секунды>

Структурные архетипы:
  - Tech launch:    HOOK → PROBLEM → SOLUTION → BENEFIT → EXAMPLE → CTA
  - Tutorial:       INTRO → SETUP → STEPS → GOTCHAS → RECAP
  - Interview:      (QUESTION → ANSWER → FOLLOWUP) повтор
  - Travel/event:   ARRIVAL → HIGHLIGHTS → QUIET MOMENTS → DEPARTURE
  - Documentary:    THESIS → EVIDENCE → COUNTERPOINT → CONCLUSION
  - Music:          INTRO → VERSE → CHORUS → BRIDGE → OUTRO
  - Или придумай свой

RULES:
  - Start/end times — на word-boundaries из транскрипта.
  - Pad cut boundaries (30-200ms окно).
  - Предпочитай silences ≥400ms как cut targets.
  - Неизбежные slip'ы оставь если нет лучшего take'а. Отметь в "reason".
  - Превысил бюджет — реви: drop beat или подрежь хвосты. Покажи total и self-correct.

OUTPUT (JSON array, no prose):
  [{"source": "clip1", "start": 2.42, "end": 6.85, "beat": "HOOK",
    "quote": "...", "reason": "..."}, ...]

Верни финальный EDL и одну строку с total runtime check'ом.
```

## Color grade (когда просят)

Твоя задача — **рассуждать про картинку**, не применять пресет. Посмотри кадр (через `timeline_view`), реши что не так, поправь одну штуку, посмотри снова.

Mental model — ASC CDL: per-channel `out = (in * slope + offset) ** power`, потом global saturation.

**Пресеты:**
- **`warm_cinematic`** — тёплый retro/technical, мягкий teal/orange split, обесцвеченный.
- **`neutral_punch`** — минимальная коррекция: contrast bump + мягкая S-curve. Без hue shifts.
- **`none`** — straight copy. Default когда пользователь не просил.

Для портретов / природы / продукта / документалистики — придумывай свою цепочку. `grade.py --filter '<raw ffmpeg>'` принимает любую filter-строку.

Hard rules: применяй **per-segment во время extraction** (не post-concat — двойной re-encode). Никогда не уходи в агрессив без теста skin-tone'ов.

## Subtitles (когда просят)

Три измерения: **chunking** (1/2/3/предложение per line), **case** (UPPER/Title/Natural), **placement** (margin от низа). Правильная комба зависит от контента.

**Рабочие стили:**

**`bold-overlay`** — short-form tech launch, fast-paced соц. 2-словные chunks, UPPERCASE, break на пунктуации, Helvetica 18 Bold, white-on-outline, `MarginV=90`. `render.py` shipts с этим как `SUB_FORCE_STYLE`. **MarginV=90 — это safe-zone правило для вертикалок 1080×1920** (TikTok/Reels UI занимает нижние 25-30%), не вкус. Не опускай ниже ~75.

```
FontName=Helvetica,FontSize=18,Bold=1,
PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,
BorderStyle=1,Outline=2,Shadow=0,
Alignment=2,MarginV=90
```

**`natural-sentence`** — нарратив, documentary, образование. 4-7 слов в chunk, sentence case, break на естественных паузах, `MarginV=60-80`, крупнее font для readability. Spread max-width.

Hard rules: субтитры ПОСЛЕДНИМИ (Rule 1), output-timeline offsets (Rule 5).

## Animations (overlays)

Анимации матчат контент и бренд. **Палитра, шрифт, визуальный язык — из разговора с пользователем**, никогда не предполагай default. Если пользователь не сказал — предложи палитру в strategy-фазе и жди подтверждения.

**Выбор engine'а per slot:**

- **HyperFrames** — браузерные HTML/CSS/GSAP композиции: product UI motion, website-to-video / mockup-to-video, кинетическая типографика, landing-page promo, data-driven UI states, transparent WebM-оверлеи с альфой, клипы где нужна детерминированная frame-capture + HyperFrames lint/validate/render. Best когда анимация должна быть авторена как веб-композиция, а не React-дерево.

- **Remotion** — React/CSS композиции с component state, переиспользуемые React-примитивы, существующая Remotion brand-система. Best когда пользователь явно просит React/Remotion или когда React-композиция — проще модель.

- **Manim** — формальные диаграммы, state machines, equation derivations, граф-морфы. Прочитай `skills/manim-video/SKILL.md` и его references для глубины.

- **PIL + PNG sequence + ffmpeg** — простые overlay карточки: счётчики, typewriter text, single bar reveals, progressive draws. Быстро итерируется, любая эстетика.

Для HyperFrames slots: scaffold в `edit/animations/slot_<id>/` через `npx --yes hyperframes init . --example blank --non-interactive --skip-skills`, собери HTML, прогон `lint`/`validate`/draft `render`, финал через `npx --yes hyperframes render . -o render.mp4` (или `--format webm -o render.webm` если нужна альфа). Указывай EDL overlay `file` на реально отрендеренный путь.

Для Remotion: изолируй проект в slot-дире, scaffold через `npx create-video@latest`, рендер через project-local `remotion render` → `render.mp4`, проверь длительность/размеры через `ffprobe`.

**Никакой engine не обязателен.** Изобретай гибриды (PIL background + HyperFrames layer поверх).

**Длительность — context-dependent:**

- **Sync-to-narration** (объяснения под голос). Floor 3s, типично 5-7s для простых карточек, 8-14s для сложных диаграмм.
- **Beat-synced accents** (music-video, fast montage). 0.5-2s ок — это accent'ы, не информация. «Readable at 1×» → «recognizable at 1×».
- **Hold финальный frame ≥ 1s** до cut'а (универсально).
- **Над voiceover'ом:** общая длительность ≥ `narration_length + 1s`.
- **Никогда parallel-reveal независимых элементов** — глаз не может трекать два новых. Одно, пауза, следующее.

**Animation payoff timing:** получи timestamp слова-payoff. Стартуй оверлей `reveal_duration` секунд раньше так чтобы landing frame совпал со сказанным словом.

**Easing** (универсально — никогда `linear`):
```python
def ease_out_cubic(t): return 1 - (1 - t) ** 3
def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t ** 3
    return 1 - (-2 * t + 2) ** 3 / 2
```

`ease_out_cubic` для single reveal. `ease_in_out_cubic` для continuous draws.

**Parallel sub-agent brief** — каждая анимация = один sub-agent через Agent tool. Каждый промпт self-contained (sub-agents без parent-контекста). Включай:

1. Одно предложение цели: «Собери ОДНУ анимацию: [spec]. Больше ничего.»
2. Абсолютный output-path (`<edit>/animations/slot_<id>/render.mp4`).
3. Технический spec: resolution, fps, codec, pix_fmt, CRF, длительность.
4. Палитра как concrete values (RGB-tuples, hex, или ссылка на design system).
5. Font path с индексом.
6. Frame-by-frame timeline (что когда, с easing).
7. Anti-list («без chrome, без лишнего, без заголовков если не указано»).
8. Code-pattern reference (копируй helpers inline, не импортируй из slots).
9. Deliverable checklist (скрипт, render, verify через ffprobe, отчёт).
10. **«Не задавай вопросов. Если что-то неоднозначно — выбери самую очевидную интерпретацию и действуй.»**

Один sub-agent = один файл (уникальные имена, parallel agents не перетирают друг друга).

## B-roll generation через MCP

Когда в EDL есть спан с `{"need_broll": true, "broll_prompt": "..."}`:

1. Запусти `python helpers/broll_generator.py edl.json --extract-prompts` чтобы получить инструкции.
2. Для каждого спана вызови MCP:
   - **Default — `mcp__higgsfield__generate_video` с model=kling-3.0** ($0.09-0.14/сек, дёшево, до 10s).
   - **Если нужен native audio** (диалог, музыка-внутри) — `model=veo-3.1-fast` ($0.15/сек, единственный с native audio).
   - **Для статичных вставок** (1-2 сек) — Nano Banana Pro → image-to-video с last-frame conditioning.
3. Сохрани результат в `edit/generated/<hash>.mp4` + создай `manifest.json` (Hard Rule #13).
4. Запусти CLIP-continuity check — score должен быть > 0.7 vs соседних кадров (Hard Rule #14). Если ниже — перегенерация.
5. Если есть generated content в финале — добавь C2PA watermark через `c2patool` (Hard Rule #15).

**Бюджет:** проверь общую стоимость через `broll_generator.py --check-budget $X`. По умолчанию $5 на проект — если выше, спроси подтверждение.

## Output spec

Матчи источник если не сказано иное. Типовые цели:
- **`1080×1920@30` vertical social** (рилз/shorts/TikTok) — default для нашего use-case
- `1920×1080@24` cinematic
- `1920×1080@30` screen content
- `3840×2160@24` 4K
- `1080×1080@30` square (Insta Feed)

`render.py` дефолтит scale в 1080p из любого source; передавай `--filter` или правь extract для других targets.

## EDL формат

```json
{
  "version": 2,
  "name": "my_reels_v1",
  "fps": 30,
  "resolution": "1080x1920",
  "sources": {
    "clip1": "/abs/path/clip1.mp4",
    "clip2": "/abs/path/clip2.mp4",
    "voice": "/abs/path/voice.m4a"
  },
  "ranges": [
    {"source": "clip1", "start": 2.42, "end": 6.85,
     "beat": "HOOK", "quote": "...", "reason": "Cleanest delivery"},
    {"source": "clip2", "start": 14.30, "end": 28.90,
     "beat": "SOLUTION", "quote": "...", "reason": "Only take without slip"},
    {"source": "GENERATED", "start": 0.0, "end": 3.0,
     "beat": "B-ROLL", "need_broll": true,
     "broll_prompt": "city street at night, neon lights, slow camera pan, cinematic",
     "need_audio": false, "budget": "cheap"}
  ],
  "grade": "warm_cinematic",
  "overlays": [
    {"file": "edit/animations/slot_01/render.mp4", "start_in_output": 0.0, "duration": 5.0}
  ],
  "subtitles": "edit/master.srt",
  "total_duration_s": 87.4
}
```

`grade` — название пресета или raw ffmpeg-фильтр. `overlays` — отрендеренные анимации. `subtitles` опционально, применяется ПОСЛЕДНИМ.

**Поля range (v5):**
- `beat_type` — `talk | screen_read | stat | broll | meme` (Rule 18, определяет тайминг).
- `effect` — `pushin` для `screen_read` (Ken-Burns establish→деталь; render считает по длительности). Пусто = статичный кадр.
- `transcript` — override stem транскрипта для preprocessed-источников (HOOK_vert→`IMG_3521`), чтобы snap/padding/thought-guard их защищали (Rule 6).
- `src_offset` — сдвиг (сек) таймлайна файла относительно транскрипта, если файл обрезан с начала. Default 0.
- `no_subs` — `true` → на этом range мои субтитры не строим (оставить оригинальные вшитые субтитры исходника, напр. на вступительной фразе).

**Поля EDL верхнего уровня (субтитры):**
- `subtitle_mode` — `"elegant"` → длинные строки (sentence case, рвать на `.!?`), для лиричного контента. Иначе bold-overlay (2 слова UPPERCASE).
- `sub_chunk_max` — макс. слов в строке субтитра (elegant ~5-6, bold ~2).
- `subtitle_style` — per-EDL force_style libass (шрифт/цвет/позиция), переопределяет глобальный `SUB_FORCE_STYLE`.

**Бесшовные вставки (важно):** соседние фото/видео-вставки (overlays) ставить ВСТЫК с нахлёстом ~0.1с — НИКОГДА с зазором: щель 0.1-0.2с между двумя вставками или между хуком и вставкой даёт видимое мелькание базы. Одиночная вставка с базой до/после ≥0.3с — нормальный cutaway. Output-офсеты считать через snap+padding (как в `render.py`), а не по сырым таймкодам.

**Перед рендером** `render.py` сам прогоняет: `validate_edl` (fail-fast на битый EDL/несуществующие файлы) → `snap_to_word` → `check_thought_boundaries` (warn) → `apply_padding`. Отдельно: `python helpers/validate_edl.py <edl>` и `python helpers/check_thought_boundaries.py <edl> --transcripts-dir <edit>/transcripts`.

## Память — `project.md`

Добавляй один раздел на сессию в `<edit>/project.md`:

```markdown
## Сессия N — YYYY-MM-DD

**Стратегия:** один абзац описания подхода
**Решения:** выбор дублей, cuts, grades, animations + почему
**Reasoning log:** одной строкой обоснование неочевидных решений
**Outstanding:** отложенные пункты
**Расходы:** ТТ-минуты транскрибировано, $/MCP сгенерировано B-roll
```

На старте читай `project.md` если есть и подведи итог последней сессии одним предложением до того как спрашивать «продолжаем?».

## Anti-patterns

Что регулярно ломается независимо от стиля:

- **Иерархические pre-computed codec-форматы** с USABILITY / tone tags / shot layers. Over-engineering. Выводи из транскрипта в момент решения.
- **Hand-tuned moment-scoring функции.** LLM выбирает лучше любой эвристики.
- **Whisper SRT / phrase-level вывод.** Теряет sub-second gap data. Всегда word-level verbatim.
- **Запуск Whisper локально на CPU.** Медленно + нормализует filler'ы. Используй hosted TT (GigaAM).
- **Burn-in субтитры в base до compositing'а оверлеев.** Оверлеи скрывают их. (Hard Rule 1.)
- **Single-pass filtergraph с оверлеями.** Double re-encode. Используй per-segment extract → concat.
- **Linear animation easing.** Робото. Всегда cubic.
- **Hard audio-cut на границах сегментов.** Слышимые щелчки. (Hard Rule 3.)
- **Typing text по center'у partial-строки.** Текст плывёт влево по мере роста.
- **Sequential sub-agents для нескольких анимаций.** Всегда parallel.
- **Edit до подтверждения стратегии.** Никогда.
- **Re-транскрипция кешированных source'ов.** Immutable output из immutable input'а.
- **Предположение типа видео заранее.** Сначала смотри, потом спрашивай, потом режь.
- **Forsing Sora 2.** EOL 2026-09-24. Не делай его primary.
- **Генерация B-roll без manifest.json.** Hard Rule #13.
- **Финал с generated-контентом без C2PA.** Hard Rule #15.
