---
name: video-music
description: Фоновая музыка под ролик — генерация трека по текстовому описанию + умное подмешивание под голос (ducking). Богдан говорит «добавь lo-fi музыку», «нужен фон под видео», «музыку потише под речь» — агент генерит инструментал через ElevenLabs Music / Suno-gateway / Fal, подкладывает под голос с автоприседанием музыки в моменты речи (sidechaincompress). Триггеры — «добавь музыку», «фоновый трек», «музыка под видео», «ducking», «приглуши музыку под голос», «бэкграунд». Часть Montazh_Agent.
---

# video-music

Генерирует фоновую музыку под ролик и подмешивает её под голос с **ducking** (музыка автоматически приседает в моменты речи — громкая в паузах, тихая под словами). Это правильнее статичного −25dB.

## Workflow

**1. Сгенерить трек** под длину ролика:
```bash
python helpers/music_gen.py generate "calm lo-fi tech ambient, soft beat, unobtrusive" \
    --duration 56 --out <edit>/music_bed.mp3
```
- `--provider <name>` — форсировать конкретного провайдера.
- `--callback <url>` — для sunoapi.org (он требует публичный вебхук).

**2. Подмешать под видео с ducking:**
```bash
python helpers/music_gen.py duck <edit>/preview.mp4 <edit>/music_bed.mp3 \
    -o <edit>/final_music.mp4 --music-db -12 --ratio 8
```
- `--music-db` — базовая громкость музыки (тише голоса). −12 норм, −16 тише.
- `--ratio` — сила приседания под голос. 8 = заметное, 4 = мягкое.

Музыка зацикливается/обрезается под длину видео автоматически.

## Провайдеры (порядок автопереключения)

| Провайдер | Ключ (.env) | Особенность |
|---|---|---|
| **elevenlabs** (проще всего) | `ELEVENLABS_API_KEY` | REST `POST /v1/music`, отдаёт mp3 сразу, **без callback**. `force_instrumental:true` |
| **sunoapi** (sunoapi.org) | `SUNOAPI_ORG_KEY` | **требует** `callBackUrl` (публичный URL) + polling по taskId. Локально неудобно |
| **apiframe** (✅ работает) | `APIFRAME_KEY` | `POST https://api.apiframe.ai/v2/music/generate` (header `X-API-Key`, body `{prompt, model:"suno", sunoParams:{model_version:"V4_5PLUS", style}}`) → `{jobId, status:QUEUED}` (202, async). Poll `GET /v2/jobs/{jobId}` → `status COMPLETED` + `result.tracks[].audioUrl` (Suno даёт 2 трека, ~3 мин длина). Реализован в `music_gen.py:gen_apiframe` |
| acedata | `ACEDATA_SUNO_KEY` | нужен баланс на acedata.cloud |
| fal | `FAL_KEY` | fal.ai music-модели |

По умолчанию порядок `["elevenlabs", "sunoapi"]`. Добавить fal/apiframe/acedata — дописать функцию в `music_gen.py:PROVIDERS`.

## Важно про права (ролики для клиентов!)

- **Suno**: коммерческие права на треки — только на **платных** тарифах. Free-tier треки коммерчески использовать нельзя.
- **ElevenLabs Music**: проверить тариф на коммерцию.
- Это критично — Богдан делает ролики клиентам, не для себя.

## Правила

- **Ключи — только из `.env`** (`.gitignore`). Не хардкодить.
- **Ducking, не статичная громкость** — `sidechaincompress` с голосом как ключом.
- **Инструментал** (`force_instrumental` / `instrumental:true`) — фон не должен перебивать речь вокалом.
- Длительность трека ≥ длины ролика + запас (зацикливание сгладит, но лучше с запасом).
- **C2PA**: ElevenLabs умеет `sign_with_c2pa` — для compliance, если ролик с сгенерированным контентом (Hard Rule #15).
