# Промпт для Gemini Deep Research — оптимальность стека для моего железа

## Контекст

Я собираю AI-видеомонтажный агент (форк browser-use/video-use) и хочу проверить, оптимален ли выбранный технологический стек для **моего конкретного устройства**. Кейс — рилз/shorts/TikTok, нарезка из исходников + генерация B-roll через MCP.

### Моё железо и окружение

- **OS:** macOS 12 (Monterey), **Darwin 21.6.0**
- **CPU:** Intel x86_64 (НЕ Apple Silicon — нет MPS, нет CoreML acceleration)
- **Python:** 3.13.13
- **Package manager:** uv 0.11.7
- **Ограничения:**
  - macOS 12 — старая система (большинство ML-библиотек дропают её wheels)
  - Intel x86_64 — нет hardware AI-acceleration (только CPU)
  - Свежий `opencv-python` 4.13+ не имеет wheel под macOS 12 Intel → пришлось pin'ить `<4.10`
  - Аналогично могут возникнуть проблемы с PyTorch / torchvision / новыми версиями transformers

### Текущий стек проекта

**Локально (на моей машине):**
- **FFmpeg** + `ffprobe` — основной рендер. На Intel macOS поддерживается `h264_videotoolbox` (hardware encoder)? Или только software `libx264`?
- **PySceneDetect** (0.6+) + `opencv-python<4.10` — shot detection
- **sentence-transformers** (3.0+) + **PyTorch** + **CLIP-ViT-B-32** — семантический матч phrase ↔ shot для audio-first режима. Тяжёлая зависимость (~2GB), работает на CPU
- **librosa** + matplotlib — waveform-визуализация для timeline_view
- **PIL** (Pillow) — простые PNG-overlay'и (TikTok-style субтитры)
- **OpenTimelineIO** — lossless EDL формат
- **Manim** (опц.) — для математических оверлеев
- **Remotion / HyperFrames** (опц.) — Node.js 22+, React-композиции

**В облаке (через MCP, не нагружает моё устройство):**
- **TeleTranscribe MCP** (мой собственный GigaAM-стек, крутится на VM) — транскрипция с word-timestamps
- **Higgsfield MCP** — Veo 3.1 / Kling 3.0 / Wan 2.6 / Hailuo 02 / Nano Banana Pro
- **Fal.ai MCP** — альтернативный gateway (1000+ моделей)
- **ElevenLabs MCP** — TTS
- **Suno MCP** — музыка

### Типичная сессия

- Длительность исходников: 1 файл 10-30 мин ИЛИ 2-10 коротких рилз по 30-60с
- Финальный формат: вертикалка 1080×1920, 30fps, 60-90с
- Что делается локально:
  - FFmpeg cut'ы (lossless `-c copy`) — секунды
  - FFmpeg финальный encode с overlays + subs — 1-3 мин
  - CLIP-эмбеддинги в audio-first режиме — 30-60 сек на ~50 shot'ов
  - PySceneDetect — 10-20 сек на 10-минутный клип
- Что в облаке:
  - Транскрипция через TT MCP (10-30 сек wall-clock + cost ₽)
  - Опционально — B-roll генерация через Higgsfield (минуты)

---

## Что нужно от Gemini Deep Research

Проведи исследование и ответь развёрнуто (минимум 3000 слов, со ссылками):

### Блок 1. Совместимость стека с моим железом

1. **Каждая библиотека из списка** (FFmpeg, PySceneDetect, OpenCV, sentence-transformers, PyTorch, librosa, OpenTimelineIO, Manim, Remotion) — будет ли работать на macOS 12 Intel x86_64 в 2026? Какие версии последние с поддержкой?
2. **PyTorch на macOS 12 Intel** — какая версия последняя поддерживается? Скорость CLIP-ViT-B-32 inference на CPU (примерно: items/s)?
3. **FFmpeg на macOS 12 Intel:** доступен ли `h264_videotoolbox` (hardware encoder)? Какая разница в скорости с `libx264` (software)? Стоит ли использовать VideoToolbox для encode (или только decode)?
4. **OpenCV на macOS 12 Intel** — почему дропнули wheels? Какая последняя версия которая работает? Стоит ли мигрировать на `opencv-python-headless` (он шире поддерживает)?

### Блок 2. Bottlenecks и оптимизации

5. **Где будут реальные тормоза** для моих кейсов? (рендер длинного видео, CLIP-эмбеддинги, scene detection, FFmpeg overlays)
6. **Опции hardware acceleration** на Intel macOS — что доступно? (Intel Quick Sync? AMD GPU если есть? Metal Performance Shaders для CPU-only Intel?)
7. **Стоит ли вынести CLIP в облако?** Например, через **Replicate** / **fal.ai CLIP endpoint** / **OpenAI embeddings API** — вместо локального sentence-transformers? Сравни цену, latency, удобство.
8. **Стоит ли заменить PySceneDetect** на что-то другое (TransNetV2 ONNX, PyAV кадровый difference, FFmpeg scenecut filter)? Что быстрее на Intel CPU?

### Блок 3. Альтернативные стеки

9. **«Cloud-only» вариант:** что если всё кроме FFmpeg вынести в облако (CLIP → API, scene detection → API, Manim → cloud render)? Цена за один монтаж 1-минутного ролика? Latency?
10. **«Native Mac»:** есть ли смысл переписать критичные части на Swift + CoreML? Или это overkill для моего use-case?
11. **Минимальный «lean» стек:** что выкинуть из текущего набора без потери ключевой функциональности? Если жить только с FFmpeg + httpx + Pillow + OpenTimelineIO — что потеряем?

### Блок 4. Сценарии деградации и upgrade-path

12. **Если PyTorch перестанет ставиться** — какой fallback для CLIP-функционала (audio-first matching)?
13. **Если macOS 12 устареет окончательно** — что критично сломается? Что упгрейдится только переездом на macOS 14+ Intel или на Apple Silicon?
14. **Если перейду на Apple Silicon (M1/M2/M3)** — что получу в производительности? Какие части стека переписывать (MPS support для PyTorch, CoreML для CLIP, VideoToolbox для FFmpeg)?
15. **Если останусь на Intel macOS 12 ещё 2 года** — что произойдёт со стеком? Какие версии библиотек pin'нуть сейчас «навсегда»?

### Блок 5. Конкретные рекомендации

В конце дай:
1. **Топ-3 изменения** в моём текущем стеке, которые дадут наибольший profit (стабильность × производительность × поддерживаемость)
2. **Чёрный список** библиотек / версий которые НЕ стоит ставить на macOS 12 Intel (с обоснованием)
3. **Roadmap upgrade'ов** — что и когда сделать (например: «к Q3 2026 — переезд на opencv-contrib-python», «к концу года — рассмотреть Apple Silicon»)
4. **Альтернативный стек** (если ты считаешь текущий неоптимальным) — твоё видение «правильного» minimum viable стека для моего железа и кейсов

### Формат

- Структура по блокам
- Каждая библиотека/инструмент — со ссылками на pypi, github, доки
- Все цифры (скорости, цены, RAM) — с указанием источника и даты
- Минимум 3000 слов в финале + Sources в конце
- Язык — русский, термины и команды на английском

### Стиль исследования

- Используй Deep Research mode: ходи по awesome-lists (`awesome-video-editing`, `awesome-ml-on-cpu`), Reddit r/MachineLearning / r/LocalLLaMA / r/VideoEditing, Hacker News, GitHub issues библиотек (для проверки совместимости с macOS 12 Intel).
- Дата состояния — май 2026.
- Не галлюцинируй: если данных нет — пиши «не нашёл», предлагай как проверить.
