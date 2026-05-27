# test_sessions/ — рабочая директория для тестовых монтажей

Сюда кладутся **исходники видео + сценарий**, и тут же агент создаёт `edit/` со всеми кешами и финальным MP4.

## Структура одной сессии

```
test_sessions/
└── <имя_сессии>/             # например: 2026-05-27_first_test
    ├── sources/              # ⬅ КЛАДИ СЮДА твои mp4/mov/m4a/wav
    │   ├── clip1.mp4
    │   ├── clip2.mp4
    │   └── voice.m4a         # для audio-first режима
    ├── scenario.md           # ⬅ КЛАДИ СЮДА бриф/сценарий (от другого агента)
    └── edit/                 # ⬅ создаётся агентом — НЕ ТРОГАТЬ
        ├── inventory.json
        ├── transcripts/
        ├── takes_packed.md
        ├── edl.json
        ├── preview.mp4
        └── final.mp4
```

## Как запустить монтаж

1. Создай папку под сессию (любое имя, рекомендую `<YYYY-MM-DD>_<краткое_описание>`):
   ```bash
   mkdir -p test_sessions/2026-05-27_my_first_reel/sources
   ```

2. Перенеси туда видео (через Finder, AirDrop с iPhone, scp с другого мака — как удобно):
   ```bash
   cp ~/Downloads/clip1.mp4 test_sessions/2026-05-27_my_first_reel/sources/
   cp ~/Downloads/clip2.mp4 test_sessions/2026-05-27_my_first_reel/sources/
   ```

3. Положи `scenario.md` (бриф/сценарий — пиши руками или приноси от другого агента). Смотри `scenario_template.md` рядом для структуры.

4. Запусти Claude Code из этой папки:
   ```bash
   cd test_sessions/2026-05-27_my_first_reel
   claude
   ```

5. В чате скажи что-то вроде:
   ```
   смонтируй один рилз из исходников по scenario.md в формате pure_talking_head
   ```
   или
   ```
   проведи inventory и предложи 3 варианта формата
   ```

## Что игнорируется git'ом

`.gitignore` исключает всё содержимое сессий (медиа-файлы, кеши, edit/) — в репо
коммитятся только `README.md` и `scenario_template.md`. Так что можно безопасно
держать здесь конфиденциальные видео клиентов.

## Лимиты

- **Один файл-источник:** до ~2 ГБ практически (FFmpeg сам справится с большим, но
  транскрипция через TT MCP оптимальна на длительности до 60 мин)
- **Параллельных сессий:** одна за раз на одном Claude Code; для конкурентных
  запусков — отдельные copies skill'а или Telegram-бот wrapper (см. roadmap)
- **Бюджет MCP:** проверяй через `mcp__teletranscribe__check_balance` перед
  большими сессиями; B-roll через Higgsfield считается через `broll_generator.py
  --check-budget`

## Удаление старой сессии

```bash
rm -rf test_sessions/<имя_сессии>
```

Сессии полностью изолированы — удаление одной не задевает другие.

## Если тестовая сессия удалась — куда переносить production

Когда придёт время делать продакшен-монтажи (клиентам, для соцсетей), создавай
сессии **не здесь**, а в любой удобной папке вне Montazh_Agent — например:

```bash
mkdir -p ~/Movies/reels/2026-05_neuroclub_launch/sources
cd ~/Movies/reels/2026-05_neuroclub_launch
claude
```

Skill работает в любой директории. `test_sessions/` — это именно тестовое
песочница рядом с кодом проекта для удобства разработки.
