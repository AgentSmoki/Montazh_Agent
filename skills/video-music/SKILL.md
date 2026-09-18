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

Статус — на 2026-09-03, по реальным сессиям (Urist 07-2026, BMW 08-2026). Провайдер без ключа в `.env` пропускается.

| Провайдер | Ключ (.env) | Статус и особенности |
|---|---|---|
| **sunoapi** (sunoapi.org) — основной | `SUNOAPI_ORG_KEY` + `SUNO_CALLBACK_URL` | ✅ **работает**. API формально требует `callBackUrl` — подходит любой публичный https-URL, результат забирается поллингом `record-info` по taskId (без реального вебхука). Cloudflare перед API режет дефолтный User-Agent (код 1010) — `music_gen.py` шлёт браузерный. Инструментал `V4_5`, трек ~2-4 мин → `bestwindow` |
| elevenlabs | `ELEVENLABS_API_KEY` | REST `POST /v1/music`, mp3 сразу, без callback, `force_instrumental:true`. ⚠️ С 07-2026 отдаёт **403** — проверить тариф/ключ перед тем, как рассчитывать |
| apiframe | `APIFRAME_KEY` | `POST https://api.apiframe.ai/v2/music/generate` (header `X-API-Key`, body `{prompt, model:"suno", sunoParams:{model_version:"V4_5PLUS", style}}`) → `{jobId}` (202), poll `GET /v2/jobs/{jobId}` → `result.tracks[].audioUrl`. Работал 06-2026, ⚠️ с 07-2026 **403** |
| acedata | `ACEDATA_SUNO_KEY` | в `PROVIDERS` не реализован; на 07-2026 баланс 0 |
| fal | `FAL_KEY` | в `PROVIDERS` не реализован; ключа нет |

По умолчанию порядок `["sunoapi", "elevenlabs", "apiframe"]` (`music_gen.py:DEFAULT_ORDER`) — от проверенного к сомнительным. Добавить fal/acedata — дописать функцию в `music_gen.py:PROVIDERS` и имя ключа в `PROVIDER_KEYS`.

## Важно про права (ролики для клиентов!)

- **Suno**: коммерческие права на треки — только на **платных** тарифах. Free-tier треки коммерчески использовать нельзя.
- **ElevenLabs Music**: проверить тариф на коммерцию.
- Это критично — Богдан делает ролики клиентам, не для себя.
- **Альтернатива AI-музыке — записи CC0** (например, Musopen «The Complete Chopin Collection» на archive.org, лицензия CC0 1.0: коммерция, нарезка, без атрибуции). Важно: произведение может быть общественным достоянием, а конкретная **запись** — защищена правами исполнителя и издателя, и соцсети ловят её по Content ID. Отсеивать `by-nc-nd`. Окно трека под резы подбирать по динамике (см. сессию BMW), не только по громкости.

## Правила

- **Ключи — только из `.env`** (`.gitignore`). Не хардкодить.
- **Ducking, не статичная громкость** — `sidechaincompress` с голосом как ключом.
- **Инструментал** (`force_instrumental` / `instrumental:true`) — фон не должен перебивать речь вокалом.
- Длительность трека ≥ длины ролика + запас (зацикливание сгладит, но лучше с запасом).
- **C2PA**: ElevenLabs умеет `sign_with_c2pa` — для compliance, если ролик с сгенерированным контентом (Hard Rule #15).
