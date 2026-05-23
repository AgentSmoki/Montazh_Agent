# Промпт для патча TeleTranscribe MCP

Скопируй этот файл целиком в **новую сессию Claude Code в `~/Documents/Razarabotka/TeleTranscribe/`**. Задача: добавить новые MCP-tools которые возвращают полную JSON-структуру с word-level timestamps и диаризацией.

---

## Контекст

TeleTranscribe MCP-сервер (`services/telegram-bot/mcp_server.py` + `mcp_server_http.py`) сейчас экспонирует:
- `transcribe_file(file_path: str, speakers: int = 1) → str` — возвращает **plain text** + footer (duration, cost, balance)
- `transcribe_url(url: str, speakers: int = 1) → str` — аналогично
- `check_balance() → dict`

Backend (GigaAM ASR) при этом **эмитит полную структуру с word-timestamps** — `utterances[].words[]` с `{text, start, end, speaker}` для каждого слова. Эти данные доступны:
1. В Task.result JSON в PostgreSQL.
2. Через HTTP API `/api/tasks/{task_id}?format=full` (есть в `services/telegram-bot/telegram_bot/api_server.py`).

Сейчас MCP-tool делает HTTP-вызов и берёт только `.text` поле, выбрасывая `segments[].words[]`.

## Зачем

Я делаю отдельный проект `Montazh_Agent` (`/Users/admin/Documents/Razarabotka/Montazh_Agent/`) — AI-видеомонтажёр на базе browser-use/video-use. Он требует word-timestamps для hard rule «never cut inside a word» — иначе режет в середине слова, получаются обрывки.

Без патча — Montazh_Agent работает в degraded mode (режет по фразам с 200ms padding). С патчем — full word-boundary precision.

## Что нужно сделать

Добавить **два новых MCP-tool** рядом с существующими (НЕ ломая старые):

### `transcribe_file_json(file_path: str, speakers: int = 1) → dict`

### `transcribe_url_json(url: str, speakers: int = 1) → dict`

Оба возвращают JSON-объект:

```json
{
  "source": "/abs/path/to/file.mp4",
  "duration_sec": 1834.5,
  "language": "ru",
  "speakers_count": 2,
  "utterances": [
    {
      "speaker": "SPEAKER_00",
      "start": 0.12,
      "end": 4.56,
      "text": "Привет, сегодня поговорим про монтаж видео...",
      "words": [
        {"text": "Привет", "start": 0.12, "end": 0.55},
        {"text": "сегодня", "start": 0.78, "end": 1.30},
        {"text": "поговорим", "start": 1.35, "end": 2.10}
      ]
    }
  ],
  "billing": {
    "duration_minutes": 30.5,
    "cost_rub": 15.25,
    "balance_remaining_rub": 1234.5
  }
}
```

## Требования к реализации

1. **Не ломать существующие `transcribe_file` / `transcribe_url`** — они продолжают возвращать plain text (обратная совместимость для текущих потребителей в Telegram-боте).

2. **Переиспользовать существующий task-poll механизм** из `mcp_server.py` — после успешного завершения task'а сделать дополнительный `GET /api/tasks/{id}?format=full` и парсить `Task.result.segments` напрямую вместо `.text`.

3. **Если в Task.result нет `words[]`** (например, ASR упал на fallback без word-timestamps) — возвращать поле `words: []` с пустым массивом и warning в логе, не падать.

4. **Дополнить `README.md`** TeleTranscribe: новые tools, JSON-схема, пример вызова из Claude Code.

5. **Юнит-тесты:** добавить в существующий тестовый сьют (поищи `tests/` или `services/telegram-bot/tests/`) тест-кейс с mocked HTTP response, проверяющий что:
   - конверсия Task.result.segments → utterances корректна
   - speakers нормализуются (SPEAKER_00 как строка)
   - words пустые → возвращается пустой массив без crash'а

6. **Деплой:** rsync до прода + restart MCP-сервиса по существующей процедуре (см. `CLAUDE.md` TeleTranscribe).

7. **ОБЯЗАТЕЛЬНО** прочесть сначала `graphify-out/GRAPH_REPORT.md` TeleTranscribe и понять текущую архитектуру MCP-серверов до изменений.

## Definition of Done

- [ ] `claude mcp call teletranscribe transcribe_file_json /path/to/test.mp4` возвращает корректный dict с word-timestamps
- [ ] `claude mcp call teletranscribe transcribe_url_json https://...` — то же для URL
- [ ] Старые `transcribe_file` / `transcribe_url` продолжают работать без изменений
- [ ] Тесты проходят
- [ ] Деплой в прод (если есть production-инстанс TT)
- [ ] README TT обновлён с примерами вызова новых tools

## После завершения

В сессии Montazh_Agent:
1. Проверить через `claude mcp list teletranscribe` что новые tools видны.
2. Удалить из `Montazh_Agent/SKILL.md` упоминания degraded-mode (если есть).
3. Закоммитить в `Montazh_Agent` коммит «TeleTranscribe MCP патч задеплоен, удалён fallback».

## Связь с Montazh_Agent helpers

После патча `Montazh_Agent/helpers/transcribe_mcp.py` будет конвертировать выхлоп этих tools в Scribe-формат для совместимости с `pack_transcripts.py` и `render.py`. Конвертация:

```python
# TeleTranscribe формат
{
  "utterances": [
    {"speaker": "SPEAKER_00", "words": [{"text": "X", "start": 0.1, "end": 0.5}, ...]}
  ]
}

# → Scribe-формат
{
  "words": [
    {"type": "word", "text": "X", "start": 0.1, "end": 0.5, "speaker_id": "speaker_0"},
    {"type": "spacing", "text": " ", "start": 0.5, "end": 0.7},
    ...
  ]
}
```

Так что важно: имя/тип поля `words[].text`, `words[].start`, `words[].end` — должны быть **строками "text"/"start"/"end"** (не "word"/"begin"/"finish") для зеро-friction конверсии.

## Если возникнет вопрос «а нужно ли менять формат?»

**Нет**, формат уже определён в этом промпте. Если в Task.result.segments поля называются иначе — конвертируй внутри MCP-tool, наружу выдавай в указанной схеме. Это даст стабильный контракт для Montazh_Agent.
