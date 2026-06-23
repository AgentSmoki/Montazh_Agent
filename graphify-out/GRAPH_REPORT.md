# Graph Report - .  (2026-06-23)

## Corpus Check
- 34 files · ~411,523 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 286 nodes · 375 edges · 34 communities detected
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 8 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]

## God Nodes (most connected - your core abstractions)
1. `CLIPOnnx` - 13 edges
2. `run()` - 8 edges
3. `fetch_and_cache()` - 7 edges
4. `extract_segment()` - 7 edges
5. `extract_all_segments()` - 7 edges
6. `main()` - 7 edges
7. `main()` - 7 edges
8. `render_timeline()` - 7 edges
9. `snap_edl()` - 7 edges
10. `build_final_composite()` - 6 edges

## Surprising Connections (you probably didn't know these)
- `Audio-first match: для каждой фразы в аудио подбираем подходящий shot из видео.` --uses--> `CLIPOnnx`  [INFERRED]
  helpers/match_video_to_audio.py → helpers/clip_onnx.py
- `Группируем word-токены в фразы (повторяем логику pack_transcripts.py).` --uses--> `CLIPOnnx`  [INFERRED]
  helpers/match_video_to_audio.py → helpers/clip_onnx.py
- `Сохраняет кадр в JPEG нужного размера (для CLIP / TT vision).` --uses--> `CLIPOnnx`  [INFERRED]
  helpers/match_video_to_audio.py → helpers/clip_onnx.py
- `Собираем shots из всех видео + извлекаем middle-frame в кеш.      Returns: [{sou` --uses--> `CLIPOnnx`  [INFERRED]
  helpers/match_video_to_audio.py → helpers/clip_onnx.py
- `Этап 1: подготовить список shots, которые нужно описать через TT MCP.      Запис` --uses--> `CLIPOnnx`  [INFERRED]
  helpers/match_video_to_audio.py → helpers/clip_onnx.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.1
Nodes (34): apply_loudnorm_two_pass(), auto_grade_for_clip(), build_final_composite(), build_geometry_vf(), build_master_srt(), concat_segments(), extract_all_segments(), extract_segment() (+26 more)

### Community 1 - "Community 1"
Cohesion: 0.15
Nodes (19): CLIPOnnx, Stub-класс. Реальная реализация — после первого реального запроса., _add_shot(), clip_onnx_backend(), clip_pytorch_backend(), collect_shots(), extract_middle_frame(), load_phrases() (+11 more)

### Community 2 - "Community 2"
Cohesion: 0.17
Nodes (15): _dl(), duck_under_voice(), _extract_audio_url(), gen_apiframe(), gen_elevenlabs(), gen_sunoapi_org(), generate(), _load_env() (+7 more)

### Community 3 - "Community 3"
Cohesion: 0.22
Nodes (14): _download(), fetch_and_cache(), _http_get_json(), klipy_search(), _load_env(), main(), query_from_cue(), Поиск и загрузка видео/картинок-мемов под ролики.  Источник по умолчанию — KLIPY (+6 more)

### Community 4 - "Community 4"
Cohesion: 0.22
Nodes (12): load_words(), main(), Snap EDL ranges к ближайшим word-boundaries из transcripts/.  Решает Hard Rule #, Modify EDL in-place: snap each range to word-boundaries.      Иммунитета по имен, Возвращает только type=='word' токены из Scribe JSON., Найти ближайший word.start ≤ start, в пределах MAX_DRIFT_MS.     Возвращает (sna, Найти ближайший word.end ≥ end, в пределах MAX_DRIFT_MS., Определить stem транскрипта для range.      Приоритет:     1. Явный override `r[ (+4 more)

### Community 5 - "Community 5"
Cohesion: 0.22
Nodes (12): apply_simple_padding(), apply_smart_padding(), find_last_word_text(), main(), Apply padding (±N мс) к каждому range в EDL.  Решает Hard Rule #7 SKILL.md: «Pad, Smart: padding по последней букве слова на границе range.end., Legacy режим — фикс ±N мс. Применять только если нет transcripts., Возвращает (post_pad_ms, reason) на основе последней фонемы слова. (+4 more)

### Community 6 - "Community 6"
Cohesion: 0.26
Nodes (11): format_duration(), format_time(), group_into_phrases(), main(), pack_one_file(), Pack all Scribe transcripts in <edit>/transcripts/ into one readable markdown., Return (header_name, duration, phrases) for one transcript file., Format a time in seconds as "NNN.NN" with fixed 6-char width for alignment. (+3 more)

### Community 7 - "Community 7"
Cohesion: 0.26
Nodes (11): compute_envelope(), extract_frames(), find_silences(), load_font(), main(), Filmstrip + waveform composite PNG for a time range of a video.  The only visual, Find gaps >= threshold seconds inside [start, end] between kept tokens., Extract N frames evenly spaced across [start, end]. Returns paths in order. (+3 more)

### Community 8 - "Community 8"
Cohesion: 0.29
Nodes (9): apply_grade(), auto_grade_for_clip(), get_preset(), main(), Apply a color grade to a video via ffmpeg filter chain.  Two modes:    1. Preset, Analyze a clip range and emit a subtle per-clip correction filter.      Returns, Return the ffmpeg filter string for a preset name. Empty string for 'none'., Sample N frames from a range and compute brightness/contrast/saturation stats. (+1 more)

### Community 9 - "Community 9"
Cohesion: 0.31
Nodes (9): aspect_class(), ffprobe_streams(), find_sources(), main(), print_human(), Инвентаризация исходников в <videos_dir>/sources/ (или в <videos_dir>/).  Запуск, sources/ имеет приоритет; если её нет — берём корень videos_dir., ffprobe → dict со всеми потоками файла. (+1 more)

### Community 10 - "Community 10"
Cohesion: 0.33
Nodes (8): file_section(), format_dur(), format_ts(), group_into_phrases(), main(), Build editable_transcript.md from Scribe-format transcripts.  Edit-by-transcript, Один блок для одного source-файла., Same as pack_transcripts.py — для consistency.

### Community 11 - "Community 11"
Cohesion: 0.31
Nodes (8): convert_tt_to_scribe(), main(), Транскрипция через TeleTranscribe MCP с конверсией в Scribe-формат.  Этот helper, TeleTranscribe JSON → Scribe-формат JSON., Один utterance TeleTranscribe → плоский список Scribe-words., SPEAKER_00 → 0, SPEAKER_01 → 1, etc. Если новый — добавляем в mapping., speaker_label_to_index(), utterance_to_scribe_words()

### Community 12 - "Community 12"
Cohesion: 0.36
Nodes (7): estimate_cost(), extract_broll_spans(), main(), Инструкции для генерации недостающих B-roll кадров через MCP.  Сам этот скрипт —, Выбор модели на основе требований спана., Найти все спаны где `need_broll: true`., select_model()

### Community 13 - "Community 13"
Cohesion: 0.29
Nodes (7): filter_by_use_case(), get_preset(), list_presets(), Каталог форматов и pipeline'ов «контент-завода».  Извлечён из созвона Богдан × Д, Все доступные ключи пресетов., Один пресет по ключу. KeyError если нет., Фильтр пресетов по use-case: 'lead_gen' / 'viral_growth' / 'manual_edit'.

### Community 14 - "Community 14"
Cohesion: 0.36
Nodes (7): extract_tags(), find_source(), main(), parse_ts(), Parse edited editable_transcript.md → edl.json.  Обратное к build_editable_trans, Поиск файла с любым видео-расширением., Извлекает inline-теги из текста. Возвращает (clean_text, tags).

### Community 15 - "Community 15"
Cohesion: 0.39
Nodes (7): find_font(), main(), make_png_sequence(), png_seq_to_mp4(), Простые PIL-overlays: TikTok-style 2-словные UPPERCASE-субтитры, бейджи, counter, PNG sequence → MP4 с прозрачным альфа-каналом (yuva420p)., render_frame()

### Community 16 - "Community 16"
Cohesion: 0.38
Nodes (6): detect_spikes(), extract_wav(), main(), Detect audio spikes на cut-границах в готовом preview.mp4.  Решает gap из SKILL., ffmpeg → mono 16kHz wav для анализа., Dual-check: onset detection + RMS-delta peaks (по Gemini Deep Research).      Cl

### Community 17 - "Community 17"
Cohesion: 0.38
Nodes (6): main(), parse_cue_body(), parse_scenario(), Парсер мем-вставок из сценария → overlays для EDL.  В сценарии (scenario.md) мем, Разобрать тело cue на query + модификаторы (@T, dur=, full, gif)., Найти все cue, скачать мемы. Вернуть {placed:[overlay...], unplaced:[...]}.

### Community 18 - "Community 18"
Cohesion: 0.43
Nodes (6): check_thought_cuts(), main(), Thought-boundary guard — ловит резы посреди мысли/синтагмы.  Закрывает дыру, кот, Вернуть список предупреждений о резах посреди мысли., _resolve_stem(), _words()

### Community 19 - "Community 19"
Cohesion: 0.38
Nodes (6): detect_shots_ffmpeg(), detect_shots_scenedetect(), main(), Детект границ кадров (shots) в видео.  Два backend'а: - `scenedetect` (default), PySceneDetect ContentDetector.      downscale=4 — 4× меньше пикселей на frame →, FFmpeg select='gt(scene,T)' — нативный scene detector C-уровня.      threshold:

### Community 20 - "Community 20"
Cohesion: 0.47
Nodes (5): main(), Готовит подсказки для агента — какие форматы вывода предложить пользователю.  На, Эвристика: какие 2-3 формата предложить., recommend(), render_markdown()

### Community 21 - "Community 21"
Cohesion: 0.5
Nodes (4): main(), ONNX-CLIP — lean-альтернатива sentence-transformers + PyTorch.  Stub-модуль для, Конвертация CLIP-ViT-B-32 из HuggingFace в .onnx.      Делается один раз при под, setup_onnx_model()

### Community 22 - "Community 22"
Cohesion: 0.6
Nodes (4): main(), EDL-валидатор — дешёвая страховка перед рендером.  Ловит то, что иначе всплывёт, _resolve_path(), validate_edl()

### Community 23 - "Community 23"
Cohesion: 0.67
Nodes (3): edl_to_otio(), main(), Экспорт нашего JSON-EDL в OTIO (.otio) и совместимые форматы (FCPXML / EDL CMX36

### Community 24 - "Community 24"
Cohesion: 0.67
Nodes (1): Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем

### Community 25 - "Community 25"
Cohesion: 0.67
Nodes (1): Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем

### Community 26 - "Community 26"
Cohesion: 0.67
Nodes (1): Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (2): make(), rounded()

### Community 28 - "Community 28"
Cohesion: 0.67
Nodes (1): Анализ Reels/Shorts конкурентов перед запуском контент-завода.  Извлечено из соз

### Community 29 - "Community 29"
Cohesion: 0.67
Nodes (1): Готовит structured prompt для запуска editor sub-agent через Agent tool.  Зачем:

### Community 30 - "Community 30"
Cohesion: 0.67
Nodes (1): Manim runner — тонкая обёртка над `manim` CLI.  Используется для: - математическ

### Community 31 - "Community 31"
Cohesion: 0.67
Nodes (1): HyperFrames runner — browser-native HTML/CSS/GSAP композиции.  Используется для:

### Community 32 - "Community 32"
Cohesion: 0.67
Nodes (1): Remotion runner — React-композиции через npx + remotion CLI.  Используется для:

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): Overlay runners для Montazh_Agent.  Каждый runner — отдельный модуль, инкапсулир

## Knowledge Gaps
- **100 isolated node(s):** `Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем`, `Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем`, `Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем`, `Инструкции для генерации недостающих B-roll кадров через MCP.  Сам этот скрипт —`, `Выбор модели на основе требований спана.` (+95 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 33`** (2 nodes): `__init__.py`, `Overlay runners для Montazh_Agent.  Каждый runner — отдельный модуль, инкапсулир`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CLIPOnnx` connect `Community 1` to `Community 21`?**
  _High betweenness centrality (0.006) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `CLIPOnnx` (e.g. with `Audio-first match: для каждой фразы в аудио подбираем подходящий shot из видео.` and `Группируем word-токены в фразы (повторяем логику pack_transcripts.py).`) actually correct?**
  _`CLIPOnnx` has 8 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем`, `Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем`, `Пересчёт overlay.start_in_output по РЕАЛЬНОМУ таймлайну после snap+pad.  Проблем` to the rest of the system?**
  _100 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.1 - nodes in this community are weakly interconnected._