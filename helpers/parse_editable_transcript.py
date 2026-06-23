"""Parse edited editable_transcript.md → edl.json.

Обратное к build_editable_transcript.py: читает markdown, выбирает строки
помеченные `[x]`, парсит таймштампы и собирает EDL.

Поддерживает inline-пометки:
  +ZOOM      — zoom 1.4× (через preprocessing FFmpeg crop+scale)
  +EXTEND    — расширить range до следующей паузы (parser сам ищет в transcript)
  +CTA       — пометить как CTA-beat
  +CROP=X,Y  — кастомный crop offset (например +CROP=120,0 для smart-crop landscape)
  +BLURFILL  — blurred-background fill для landscape → portrait

Из заголовков `## IMG_3008.MOV (...)` парсится source name → находит соответствующий
файл в `sources/` (искать .mp4/.mov/.MOV/etc).

Usage:
    python helpers/parse_editable_transcript.py <edit>/editable_transcript.md \\
        -o <edit>/edl.json \\
        --sources-dir <project>/sources \\
        [--zoom-factor 1.4]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# regex
LINE_RE = re.compile(
    r"^\s*[-*]\s+"                                 # bullet
    r"\[(?P<check>[xX ])\]\s+"                     # checkbox
    r"\[(?P<ts_in>\d{1,2}:\d{2}\.\d{1,3})-"        # timestamp in
    r"(?P<ts_out>\d{1,2}:\d{2}\.\d{1,3})\]\s*"     # timestamp out
    r"(?:\((?P<dur>[\d.]+)с\)\s*)?"                # duration (опц)
    r"(?P<text>.+?)$",                              # text + tags
    re.UNICODE,
)
SOURCE_HEADER_RE = re.compile(r"^##\s+(?P<name>\S+?)(?:\.[A-Za-z0-9]+)?\b", re.UNICODE)
TAG_RE = re.compile(r"\+(?:ZOOM|EXTEND|CTA|BLURFILL|CROP=\d+,\d+)", re.UNICODE)
CROP_RE = re.compile(r"\+CROP=(\d+),(\d+)")


VIDEO_EXTS = (".mp4", ".mov", ".MOV", ".MP4", ".m4v", ".mkv", ".avi")


def parse_ts(s: str) -> float:
    """'00:05.67' → 5.67"""
    m, sec = s.split(":", 1)
    return int(m) * 60 + float(sec)


def find_source(name: str, sources_dir: Path) -> Path | None:
    """Поиск файла с любым видео-расширением."""
    for ext in VIDEO_EXTS:
        p = sources_dir / f"{name}{ext}"
        if p.exists():
            return p
    return None


def extract_tags(text: str) -> tuple[str, list[str]]:
    """Извлекает inline-теги из текста. Возвращает (clean_text, tags)."""
    tags = TAG_RE.findall(text)
    clean = TAG_RE.sub("", text).strip()
    return clean, tags


def main() -> None:
    ap = argparse.ArgumentParser(description="editable_transcript.md → edl.json")
    ap.add_argument("md_file", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--sources-dir", type=Path, required=True,
                    help="Папка с source-файлами для resolve paths")
    ap.add_argument("--name", default=None,
                    help="EDL name (default: stem md-файла)")
    ap.add_argument("--grade", default="neutral_punch",
                    help="Color grade preset (default neutral_punch)")
    args = ap.parse_args()

    md_path = args.md_file.resolve()
    if not md_path.exists():
        sys.exit(f"md не найден: {md_path}")
    sources_dir = args.sources_dir.resolve()
    if not sources_dir.is_dir():
        sys.exit(f"sources_dir не найдена: {sources_dir}")

    current_source = None
    sources_map: dict[str, str] = {}
    ranges: list[dict] = []

    for line_num, line in enumerate(md_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.rstrip()

        # Source header
        m = SOURCE_HEADER_RE.match(stripped)
        if m:
            current_source = m.group("name")
            continue

        # Phrase line
        m = LINE_RE.match(stripped)
        if not m:
            continue

        check = m.group("check").lower()
        if check != "x":
            continue  # пропускаем неотмеченные

        if not current_source:
            print(f"  ⚠️  строка {line_num}: нет source-header выше — пропускаю")
            continue

        ts_in = parse_ts(m.group("ts_in"))
        ts_out = parse_ts(m.group("ts_out"))
        raw_text = m.group("text")
        clean_text, tags = extract_tags(raw_text)

        # Регистрируем source в map при первом встрече
        if current_source not in sources_map:
            src_path = find_source(current_source, sources_dir)
            if src_path is None:
                print(f"  ⚠️  source {current_source} не найден в {sources_dir} — пропускаю beat")
                continue
            sources_map[current_source] = str(src_path)

        beat_data = {
            "source": current_source,
            "start": ts_in,
            "end": ts_out,
            "beat": f"line_{line_num}",
            "quote": clean_text,
        }
        if tags:
            beat_data["tags"] = tags
            crop_m = CROP_RE.search(" ".join(tags))
            if crop_m:
                beat_data["crop_offset"] = [int(crop_m.group(1)), int(crop_m.group(2))]

        ranges.append(beat_data)

    if not ranges:
        sys.exit("⚠️  нет ни одной отмеченной [x] фразы в файле")

    edl = {
        "version": 4,
        "name": args.name or md_path.stem,
        "total_duration_s": sum(r["end"] - r["start"] for r in ranges),
        "_built_from": str(md_path),
        "sources": sources_map,
        "ranges": ranges,
        "grade": args.grade,
        "overlays": [],
        "_processing_pipeline": [
            "1. snap_to_word.py — snap ranges к word-boundaries",
            "2. apply_padding.py — расширить ±100/150мс",
            "3. render.py --preview --build-subtitles",
            "4. detect_audio_spikes.py — авто-проверка стыков",
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(edl, ensure_ascii=False, indent=2))
    print(f"✓ EDL: {args.output}")
    print(f"  {len(ranges)} beats, ~{edl['total_duration_s']:.1f}с total")
    print(f"  sources: {', '.join(sources_map.keys())}")


if __name__ == "__main__":
    main()
