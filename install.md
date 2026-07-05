---
name: montazh-agent-install
description: Установка Montazh_Agent в Claude Code (или Codex/Hermes) и подключение TeleTranscribe MCP + Higgsfield MCP. Один раз на машине.
---

# Установка Montazh_Agent

Только для первой установки. Для ежедневного редактирования читай `SKILL.md` + `CLAUDE.md`.

## Что должно быть на машине

1. Репозиторий `Montazh_Agent/` в `/Users/admin/Documents/Razarabotka/`.
2. `ffmpeg` + `ffprobe` в `$PATH` (опционально `yt-dlp`, `manim`, Node.js).
3. **TeleTranscribe** API доступен на `http://localhost:8000` (или указанный `TT_API_BASE_URL`) и `TT_API_KEY` в `.env`.
4. Claude Code умеет находить skill — symlink в `~/.claude/skills/montazh-agent`.

## Шаги установки

### 1. Клон (если ещё нет)

```bash
test -d /Users/admin/Documents/Razarabotka/Montazh_Agent || {
  echo "Папки нет — клонировать заново вручную, см. ancient-baking-book план"
  exit 1
}
cd /Users/admin/Documents/Razarabotka/Montazh_Agent
```

### 2. Python-зависимости

```bash
command -v uv >/dev/null && uv sync || pip install -e .
```

Опциональные группы:
```bash
# Manim для математических оверлеев
uv sync --extra animations

# OTIO-Plugins для экспорта в Final Cut / Resolve / EDL CMX3600
uv sync --extra otio-export
```

### 3. FFmpeg + yt-dlp

```bash
command -v ffmpeg >/dev/null || brew install ffmpeg
command -v yt-dlp >/dev/null || brew install yt-dlp    # опц., для скачивания YouTube/TikTok
command -v ffprobe >/dev/null && ffprobe -version | head -1
```

**⚠️ macOS 12 Monterey + Intel — заморозь Homebrew от обновлений.**
Homebrew официально поддерживает только 3 последние мажорные macOS. macOS 12
выпала из окна — скоро brew перестанет отдавать прекомпилированные bottles для
FFmpeg/Node.js, и при `brew update && brew upgrade` начнёт собирать из исходников
(часы CPU + 100% вентилятор). По рекомендации Gemini Deep Research:

```bash
# Добавь в ~/.zshrc (или ~/.bashrc) и перезапусти shell
echo 'export HOMEBREW_NO_AUTO_UPDATE=1' >> ~/.zshrc
echo 'export HOMEBREW_NO_INSTALL_UPGRADE=1' >> ~/.zshrc

# Проверка: автоапдейт выключен
echo $HOMEBREW_NO_AUTO_UPDATE   # должно вывести "1"
```

После этого `brew install X` не будет триггерить полное обновление дерева.
Обновления делаешь вручную через `brew update && brew upgrade <конкретный_пакет>`,
только когда сам это решишь.

### 4. Node.js (опц., для Remotion / HyperFrames)

```bash
command -v node >/dev/null || brew install node
node --version | grep -E 'v(2[2-9]|[3-9][0-9])' || echo "⚠️ Нужен Node.js >= 22 для HyperFrames"
```

### 5. .env

```bash
cp .env.example .env
# Открой .env и впиши:
#   TT_API_KEY=tt_xxxxxxxxxxxxxxxxxxxx
#   TT_API_BASE_URL=http://localhost:8000
chmod 600 .env
```

**Где взять `TT_API_KEY`:** в telegram-боте [@TeleTranscribe_bot](https://t.me/TeleTranscribe_bot) — команда `/api`. Там же выдаётся MCP-сервер для подключения транскрибатора.

### 6. Регистрация skill в Claude Code

```bash
mkdir -p ~/.claude/skills
ln -sfn /Users/admin/Documents/Razarabotka/Montazh_Agent ~/.claude/skills/montazh-agent
ls -la ~/.claude/skills/montazh-agent
```

Для Codex/Hermes/других агентов — аналогично, в их skills-директорию.

### 7. Регистрация MCP-серверов

#### TeleTranscribe (обязательно)

MCP-сервер и API-ключ выдаёт бот [@TeleTranscribe_bot](https://t.me/TeleTranscribe_bot) (команда `/api`). Регистрация:

```bash
claude mcp add teletranscribe \
  python3 <путь_к_mcp_server.py_из_бота> \
  -e TT_API_BASE_URL=<url_из_бота> \
  -e TT_API_KEY=$(grep ^TT_API_KEY .env | cut -d= -f2)
```

Проверка:
```bash
claude mcp list | grep teletranscribe
# В Claude Code → вызови mcp__teletranscribe__check_balance → должен вернуть dict с balance_rub
```

#### Higgsfield (для B-roll генерации, опц.)

```bash
claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp
# При первом вызове откроется браузер для OAuth. 150 free credits/мес.
```

#### Fal.ai (1000+ моделей, опц.)

```bash
# Получи ключ на https://fal.ai/dashboard/keys
claude mcp add --transport http fal-ai https://mcp.fal.ai/mcp \
  --header "Authorization: Bearer $(grep ^FAL_KEY .env | cut -d= -f2)"
```

#### ElevenLabs (TTS для generative-only режима, опц.)

```bash
claude mcp add elevenlabs npx @elevenlabs/elevenlabs-mcp
```

#### Suno (музыка, опц.)

```bash
claude mcp add suno https://...  # см. AceDataCloud/SunoMCP repo
```

### 8. Регистрация в VSCode workspace

Если ещё не сделано, открой `/Users/admin/Documents/Razarabotka/main-workspace.code-workspace` и добавь в `folders[]`:
```json
{ "name": "🎬 Монтажный агент", "path": "Montazh_Agent" }
```

### 9. Проверка end-to-end

```bash
# Helpers выполняются
python helpers/inventory.py --help >/dev/null && echo "✓ inventory.py"
python helpers/transcribe_mcp.py --check
python helpers/format_recommender.py --help >/dev/null && echo "✓ format_recommender.py"
python helpers/render.py --help >/dev/null && echo "✓ render.py"

# MCP виден
claude mcp list

# Symlink работает
readlink ~/.claude/skills/montazh-agent
```

### 10. Smoke test (опционально, потратит TT-минуты)

```bash
mkdir -p ~/test_video/sources
# Положи туда 1-3 коротких mp4 (по 30-60 сек)
echo "## Сценарий тест-ролика\n- хук\n- основа\n- CTA" > ~/test_video/scenario.md
cd ~/test_video
claude
# > смонтируй рилз из этих клипов по scenario.md
```

Ожидаемо:
- агент запустил `inventory.py`
- транскрибировал через MCP TeleTranscribe (если ключ работает)
- предложил 2-3 варианта формата
- после согласования сгенерил EDL и `edit/preview.mp4`
- после `да, финал` — `edit/final.mp4`

## Известные проблемы

### Word-timestamps для Hard Rule #6 (never cut inside a word)

✅ **Решено.** TT MCP отдаёт word-level JSON через `transcribe_file_json` / `transcribe_url_json` (`utterances[].words[]`) — патч задеплоен. `helpers/transcribe_mcp.py` конвертирует raw-ответ в Scribe-format.

Degraded fallback (если по какой-то причине доступен только plain-text MCP): агент режет по utterance-boundaries с padding 200ms — качество чуть хуже, но pipeline работает.

### 402 от MCP / нет кредитов

```bash
claude mcp call teletranscribe check_balance
# Если balance_rub < 100 — пополни через TeleTranscribe админку.
```

### "ffmpeg not found"

```bash
brew install ffmpeg
# Или скачай static build: https://www.ffmpeg.org/download.html
```

### HyperFrames падает с EBADENGINE

Нужен Node.js >= 22:
```bash
brew install node@22 && brew link --overwrite node@22
```

## Обновления

```bash
cd /Users/admin/Documents/Razarabotka/Montazh_Agent
git pull --ff-only
uv sync   # если deps менялись
```

Если хочешь смержить апстрим-фиксы из [browser-use/video-use](https://github.com/browser-use/video-use):
```bash
git remote add upstream https://github.com/browser-use/video-use 2>/dev/null
git fetch upstream
# cherry-pick конкретный коммит (например, фикс render.py)
git cherry-pick <hash>
# Проверь что наш русский SKILL.md / CLAUDE.md не перезатёрся
```
