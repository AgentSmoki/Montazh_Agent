# OS-профили Montazh_Agent

Справочник различий между macOS / Windows / Linux для агента-монтажёра.
Агент определяет ОС автоматически (`helpers/env_doctor.py`) и применяет нужный
профиль. Этот файл — точка правды про различия; код берёт пути через
`helpers/platform_paths.py`.

---

## Как агент определяет ОС (без вопроса пользователю)

Claude Code работает локально на машине пользователя, поэтому ОС определяется
детерминированно, а не вопросом. На старте сессии и перед монтажём:

```bash
python helpers/env_doctor.py          # отчёт (ru) + команды установки под ОС
python helpers/env_doctor.py --json   # машинный JSON: {os, critical, fonts, ok}
```

`ok: true` → инструменты на месте, монтаж можно начинать.
`ok: false` → агент показывает пользователю, чего не хватает, и команду установки
**под его ОС**. Вопрос пользователю задаётся только в этом случае.

---

## Таблица различий

| Аспект | macOS | Windows | Linux |
|---|---|---|---|
| **Имя ОС** (`platform_paths.os_name()`) | `macos` | `windows` | `linux` |
| **Шелл** | zsh/bash | PowerShell/cmd | bash |
| **Heredoc** (`<<EOF`) | ✅ работает | ❌ нет — `Set-Content` или `py -c` | ✅ работает |
| **ffmpeg install** | `brew install ffmpeg` | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` |
| **Шрифт sans (PIL)** | Helvetica.ttc | arialbd.ttf | DejaVuSans-Bold.ttf |
| **Шрифт mono (PIL)** | Menlo.ttc | consola.ttf | DejaVuSansMono.ttf |
| **libass FontName** | `Helvetica` | `Arial` | `DejaVu Sans` |
| **Каталог шрифтов** | `/System/Library/Fonts` | `%WINDIR%\Fonts` | `/usr/share/fonts` |
| **Разделитель пути** | `/` | `\` (но `/` тоже принимается) | `/` |
| **Удаление открытого файла** | ✅ можно | ❌ файл залочен, сначала закрыть | ✅ можно |

---

## Windows — доп. правила (главные грабли)

1. **Шелл — PowerShell/cmd, не bash.** Heredoc (`cat <<EOF`) не работает.
   Для записи файлов — `Set-Content -Path file -Value '...'` или `py -c "..."`.
   Для запуска Python — `py` или `python`, не `python3`.

2. **Пути в FFmpeg-фильтрах.** Внутри `filter_complex`/`drawtext`/`subtitles`
   двоеточие диска экранируется: путь `C:\clip.srt` → `C\:/clip.srt`
   (бэкслеши → прямые слеши, `:` → `\:`). Лучший способ обойти — передавать
   относительные пути и запускать ffmpeg из рабочей папки `edit/`, либо собирать
   путь через `pathlib.Path(...).as_posix()`.

3. **Шрифты.** Helvetica на Windows нет — код сам подставит Arial/Segoe UI через
   `platform_paths`. Если нужен кастомный шрифт — положить `.ttf` в
   `%LOCALAPPDATA%\Microsoft\Windows\Fonts` (установка без прав админа).

4. **Длинные пути.** Windows по умолчанию ограничивает путь 260 символами.
   Держи `videos_dir` неглубоко (например `C:\mz\<проект>`), не в
   `C:\Users\...\OneDrive\Документы\...`.

5. **Залоченные файлы.** Нельзя удалить/перезаписать mp4, пока его держит
   открытым проигрыватель или другой ffmpeg-процесс. Закрой превью перед
   ре-рендером.

6. **Переносы строк.** Гит-репо настроен на LF; на Windows проверь, что
   редактор не превращает `.py`/`.srt` в CRLF (ffmpeg subtitles это переживает,
   но скрипты лучше держать в LF).

7. **MCP-сервера.** `claude mcp list` и регистрация MCP идентичны, но пути в
   конфиге — Windows-стиль. TeleTranscribe MCP работает по сети, ОС-независим.

---

## macOS — заметки

- Helvetica/Menlo/SF идут из коробки — основной целевой профиль (на нём
  отлаживалось).
- Apple Silicon (arm64) vs Intel (x86_64): `platform_paths` это не различает,
  но некоторые pip-колёса (torch, onnxruntime) ставятся по-разному — см.
  `research/03_research_stack.md`.
- `sed -i ''` (BSD-вариант с пустым аргументом) — только macOS; на Linux это
  `sed -i`. Для кроссплатформенных правок файлов используй Python, не sed.

---

## Linux / WSL — заметки

- Базовых шрифтов может не быть: `sudo apt install fonts-dejavu fonts-liberation`.
- **WSL** определяется автоматически (`platform_paths.is_wsl()`): это Linux, но
  Windows-диски монтируются в `/mnt/c`. ffmpeg ставится как на Linux. Если
  исходники лежат на Windows-разделе — работай с копией в Linux-ФС (на `/mnt/c`
  ввод-вывод медленнее и бывают проблемы с правами).

---

## Что НЕ зависит от ОС

- Логика EDL, транскрипция (TeleTranscribe MCP по сети), все 17 hard rules,
  тайминги, padding, диаризация.
- MCP B-roll генерация (Higgsfield/Fal по сети).
- Структура `<videos_dir>/edit/`.

Кроссплатформенность изолирована в `helpers/platform_paths.py` — новый
ОС-зависимый код добавляй только туда.
