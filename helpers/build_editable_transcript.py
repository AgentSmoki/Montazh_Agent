"""Build editable_transcript.md from Scribe-format transcripts.

Edit-by-transcript pattern (как Descript / Riverside / Opus Clip).
Пользователь редактирует markdown файл (отмечает [x] что брать), агент потом
парсит через parse_editable_transcript.py и строит EDL.

Каждая строка в выходе содержит:
  - [ ] чекбокс для пометки «взять»
  - таймштампы [MM:SS.cc-MM:SS.cc] в формате читаемом человеком
  - реальную длительность (помощь для chunk planning)
  - сам текст фразы (без UPPERCASE — естественное чтение)

Фразы группируются как в `pack_transcripts.py:group_into_phrases` (silence ≥0.5s
или смена спикера), но без сжатия — пользователь видит ВСЁ что произнесено
и выбирает руками.

Usage:
    python helpers/build_editable_transcript.py <edit_dir>/transcripts/ \\
        -o <edit_dir>/editable_transcript.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HEADER = """# Стенограмма для редактирования

**Как пользоваться:**
- Меняй `[ ]` → `[x]` на тех фразах что хочешь оставить в финале
- Переставляй строки drag-and-drop если хочешь изменить порядок подачи
- Дописывай пометки в конце строки:
  - `+ZOOM` — приблизить кадр 1.4× для деталей
  - `+EXTEND` — расширить кусок до следующей паузы (для контекста)
  - `+CTA` — финальная вставка
- Сохрани файл, агент подхватит изменения

**Технические правила (включены автоматически):**
- Padding ±100мс на каждом краю (не обрезает окончания слов)
- Snap к word-boundaries из ASR (не режет внутри слова)
- Auto-detect аудио-щелчков на стыках с auto-fix
- 30мс audio fades на каждой границе

---

"""


def format_ts(sec: float) -> str:
    """5.67 → '00:05.67'"""
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:05.2f}"


def format_dur(sec: float) -> str:
    """6.8 → '6.8с'"""
    return f"{sec:.1f}с"


def group_into_phrases(words: list[dict], silence_threshold: float = 0.5) -> list[dict]:
    """Same as pack_transcripts.py — для consistency."""
    phrases: list[dict] = []
    current_words: list[dict] = []
    current_start: float | None = None

    def flush():
        nonlocal current_words, current_start
        if not current_words:
            return
        text_parts = []
        for w in current_words:
            t = w.get("type", "word")
            raw = (w.get("text") or "").strip()
            if not raw:
                continue
            if t == "audio_event":
                if not raw.startswith("("):
                    raw = f"({raw})"
            text_parts.append(raw)
        if not text_parts:
            current_words = []
            current_start = None
            return
        text = " ".join(text_parts)
        text = (text.replace(" ,", ",").replace(" .", ".")
                    .replace(" ?", "?").replace(" !", "!"))
        end_time = current_words[-1].get("end") or current_words[-1].get("start") or current_start or 0.0
        phrases.append({
            "start": current_start,
            "end": end_time,
            "text": text,
        })
        current_words = []
        current_start = None

    prev_end: float | None = None
    for w in words:
        t = w.get("type", "word")
        if t == "spacing":
            start = w.get("start")
            end = w.get("end")
            if start is not None and end is not None and end - start >= silence_threshold:
                flush()
            continue
        start = w.get("start")
        if start is None:
            continue
        if prev_end is not None and start - prev_end >= silence_threshold:
            flush()
        if current_start is None:
            current_start = start
        current_words.append(w)
        prev_end = w.get("end", start)

    flush()
    return phrases


def file_section(source_name: str, duration_sec: float, phrases: list[dict]) -> str:
    """Один блок для одного source-файла."""
    lines = []
    lines.append(f"## {source_name}.MOV  ({duration_sec:.1f}с — {len(phrases)} фраз)")
    lines.append("")
    for p in phrases:
        ts_in = format_ts(p["start"])
        ts_out = format_ts(p["end"])
        dur = p["end"] - p["start"]
        text = p["text"]
        lines.append(f"- [ ] [{ts_in}-{ts_out}] ({format_dur(dur)}) {text}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate editable_transcript.md from Scribe-format transcripts/"
    )
    ap.add_argument("transcripts_dir", type=Path,
                    help="Папка с *.json транскриптами в Scribe-формате")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="Куда сохранить (default: <parent>/editable_transcript.md)")
    ap.add_argument("--silence-threshold", type=float, default=0.5,
                    help="Разбивать фразы на silence ≥ N секунд (default 0.5)")
    args = ap.parse_args()

    transcripts_dir = args.transcripts_dir.resolve()
    if not transcripts_dir.is_dir():
        sys.exit(f"папка не найдена: {transcripts_dir}")

    json_files = sorted(p for p in transcripts_dir.glob("*.json"))
    if not json_files:
        sys.exit(f"нет *.json в {transcripts_dir}")

    out_path = args.output or transcripts_dir.parent / "editable_transcript.md"

    sections = []
    for json_path in json_files:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skip {json_path.name}: {e}")
            continue
        words = data.get("words") or []
        if not words:
            print(f"  skip {json_path.name}: пустой words[]")
            continue
        phrases = group_into_phrases(words, args.silence_threshold)
        if not phrases:
            continue
        duration = phrases[-1]["end"] - phrases[0]["start"]
        sections.append(file_section(json_path.stem, duration, phrases))

    if not sections:
        sys.exit("не сформировано ни одной секции")

    content = HEADER + "\n".join(sections)
    out_path.write_text(content, encoding="utf-8")

    total_phrases = sum(s.count("- [ ]") for s in sections)
    kb = out_path.stat().st_size / 1024
    print(f"✓ {out_path}")
    print(f"  {len(sections)} файлов, {total_phrases} фраз, {kb:.1f} KB")


if __name__ == "__main__":
    main()
