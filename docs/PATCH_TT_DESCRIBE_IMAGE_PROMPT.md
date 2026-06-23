# PATCH-промпт для TeleTranscribe MCP — `describe_image` tool

Скопируй этот файл целиком в **новую сессию Claude Code в `/Users/admin/Documents/Razarabotka/TeleTranscribe/`**.

Задача: добавить MCP-tool `describe_image` (и опционально `describe_image_batch`), используя уже существующий vision-стек TeleTranscribe (NVIDIA NIM → Yandex → OpenRouter каскад).

---

## Контекст

В TeleTranscribe уже есть полностью работающая система описания изображений:
- `services/telegram-bot/telegram_bot/processors/llm_client.py`
  - `async def describe_image(image_data: bytes, caption: str = "") → tuple[str|None, str|None]` (строки 1150–1173)
  - `async def process_image_with_llm(image_data, prompt, mime_type="image/jpeg", max_output_tokens=500)` (строки 907–1147)
- Каскад моделей (Phase 11, 2026-05-14):
  - **Tier 1 NVIDIA NIM**: `nemotron-nano-12b-v2-vl`, `llama-3.2-90b-vision`, `llama-3.2-11b-vision-instruct`
  - **Tier 2 Yandex Responses API**: `qwen3.6-35b-a3b`, `gemma-3-27b-it`, `qwen2.5-vl-72b`, `yandexgpt-vision`
  - **Tier 3 OpenRouter**: `google/gemini-2.5-flash`, `nvidia/nemotron-nano-12b-v2-vl:free`
- Используется в `handlers/admin_dump.py:_describe_image()` для `/dump` команды TG-канала.
- Production-deployment работает на VM `93.77.187.33` (Yandex Cloud, 8 vCPU, 32 GB).
- Авторизация — общая для всех LLM (`NVIDIA_API_KEY*`, `YANDEX_API_KEY`, `FREE_API_KEY`).
- **Vision-запросы не биллируются** (нет записей в `api_billing.py`) — но эту логику можно добавить тем же патчем.

**Чего нет:** MCP-tool в `mcp_server.py` / `mcp_server_http.py`. Также нет публичного HTTP endpoint типа `/api/describe_image`.

## Зачем

В соседнем проекте `Montazh_Agent` (`/Users/admin/Documents/Razarabotka/Montazh_Agent/`) — AI-видеомонтажный агент. Один из его режимов — **audio-first matching**: пользователь записал отдельно голосовое аудио + несколько разных видеосъёмок → агент укладывает голос как timeline, подбирает видеокадры под каждую фразу.

**Текущее решение** — `helpers/match_video_to_audio.py` через CLIP-эмбеддинги (sentence-transformers + PyTorch). Это:
- +2.5 ГБ зависимостей
- +2.5 ГБ RAM при работе
- 40-50 сек на 50 кадров на Intel CPU

**Лучшее решение** — переиспользовать уже работающий vision-стек TT через MCP. Это:
- Качество выше (Llama-Vision/Yandex точнее CLIP-ViT-B-32 на семантике)
- Локальная нагрузка обнуляется (всё в облаке/на VM)
- Lean-стек в Montazh_Agent (можно выкинуть sentence-transformers + torch вовсе)

## Что нужно сделать

Добавить **два новых MCP-tool** рядом с существующими `transcribe_*` (НЕ ломая старые):

### `describe_image(file_path: str, prompt: str = "", max_tokens: int = 300) → dict`

### `describe_image_batch(file_paths: list[str], prompt: str = "", max_tokens: int = 300) → dict`

Возвращают JSON:

```json
{
  "source": "/abs/path/to/frame.jpg",
  "description": "Городская улица ночью, неоновые вывески, влажный асфальт после дождя, медленный пешеходный поток.",
  "model_used": "qwen2.5-vl-72b",
  "tier": "yandex",
  "language": "ru",
  "duration_ms": 4230
}
```

Для batch — массив таких объектов + общий `billing`:

```json
{
  "results": [{...}, {...}, ...],
  "billing": {
    "images_count": 12,
    "cost_rub": 0.0,
    "balance_remaining_rub": 1234.5
  }
}
```

## Требования к реализации

1. **Переиспользовать `llm_client.describe_image()`** напрямую — не дублировать логику каскада.

2. **Сигнатура MCP-tool**:
   - Принимает абсолютный путь к локальному файлу (`file_path: str`).
   - Поддерживаемые форматы: JPEG, PNG, WebP (как уже умеет `process_image_with_llm`).
   - Опциональный `prompt` (если пустой — использовать default «Опиши кратко содержимое кадра в 30 слов на русском»).
   - Опциональный `max_tokens` (default 300, max 1000).

3. **HTTP transport** — добавить и в `mcp_server.py` (stdio), и в `mcp_server_http.py` (для удалённых клиентов). Авторизация — та же `Bearer $TT_API_KEY` для HTTP.

4. **Биллинг** (опционально, но желательно):
   - Зафиксировать стоимость per-image (типично $0.001-0.003 в зависимости от модели)
   - Логировать в `api_billing.py` рядом с транскрипциями
   - Возвращать `billing.balance_remaining_rub` в ответе

5. **Batch-оптимизация**:
   - При `describe_image_batch` — параллельные вызовы каскада (asyncio.gather, лимит 4-8 одновременно)
   - При rate-limit на одном tier — fallback на следующий, как уже делает `llm_client`

6. **Обработка ошибок** (как у `transcribe_*_json`):
   - При ошибке возвращать тот же dict-тип с полем `error` вместо raise:
     ```json
     {"error": "Vision caskad down (all tiers failed)", "source": "/path"}
     {"error": "Unsupported format: .heic", "source": "/path"}
     ```
   - Это даёт LLM-агенту возможность `if "error" in result:` вместо try/except.

7. **Дополнить `doc/MCP_TOOLS.md`** — секция «Vision (описание изображений)» с новыми tools, схемой и примерами вызова.

8. **Юнит-тесты:** в `services/telegram-bot/tests/` (или где они есть) — тест-кейс с моком одного tier'а.

9. **Деплой:** rsync до прода (`93.77.187.33`) + restart MCP-сервиса по существующей процедуре. Не забудь supervisord конфиг `tt:mcp-http` если меняешь HTTP.

10. **ОБЯЗАТЕЛЬНО** прочитать сначала `graphify-out/GRAPH_REPORT.md` TeleTranscribe и `doc/ARCHITECTURE.md §8 (LLM-каскад)` до изменений.

## Definition of Done

- [ ] `claude mcp call teletranscribe describe_image /path/to/frame.jpg` возвращает корректный dict с описанием
- [ ] `claude mcp call teletranscribe describe_image_batch '["/p1.jpg","/p2.jpg"]'` тоже работает (параллельно)
- [ ] Старые `transcribe_*` tools не сломались
- [ ] `doc/MCP_TOOLS.md` обновлён
- [ ] Тесты проходят
- [ ] Деплой в production (если есть)
- [ ] Опционально: биллинг для vision-запросов

## Связь с Montazh_Agent

После патча — `Montazh_Agent/helpers/match_video_to_audio.py` (backend `tt-describe`)
автоматически заработает. Структура взаимодействия:

```
1. match_video_to_audio.py --backend tt-describe
   → создаёт edit/match_cache/_pending_shots.json
   → выписывает агенту список frame'ов, которые нужно описать через MCP

2. Агент в чате (Claude Code):
   for shot in pending:
       result = mcp__teletranscribe__describe_image(shot["frame_path"])
       Path(shot["save_description_to"]).write_text(result["description"])

3. match_video_to_audio.py --backend tt-describe --judge-only
   → читает descriptions/*.txt + phrases
   → создаёт edit/match_cache/_judge_input.json для LLM-as-judge

4. Агент делает финальный ranking (Claude как judge) →
   edit/audio_first_edl.json
```

## Если возникнет вопрос «использовать batch или single tool?»

**Оба нужны.** single — для гранулярного контроля и удобства Telegram-бот сценария.
batch — для эффективности при обработке десятков кадров в Montazh_Agent.

## Если возникнет вопрос «может, добавить HTTP endpoint вместо/вместе с MCP?»

**Только MCP.** HTTP endpoint — лишний интерфейс, который придётся поддерживать.
MCP уже стандартизирован для AI-агентов, других клиентов у этой функции нет.
Telegram-бот по-прежнему вызывает `llm_client.describe_image` напрямую, без MCP.
