"""Разбор рилса в раскадровку «Текст | Кадр» + метрики удержания.

Вход: транскрипт в Scribe-формате (`transcribe_mcp.py`) и границы кадров
(`scene_detect.py`). Выход: markdown с таблицей и метриками.

Два прохода:
  1. С `--frames-dir` — вырезает по кадру из середины каждого шота и пишет
     `_pending_frames.json`. Агент описывает кадры через
     `mcp__teletranscribe__describe_image_batch` и кладёт ответы в
     `<frames-dir>/desc/<имя кадра>.txt`.
  2. Повторный запуск подставляет описания в правую колонку.

Использование:
    python helpers/reel_breakdown.py --video reel.mp4 \
        --transcript edit/transcripts/reel.json \
        --shots edit/shots/reel.json \
        --frames-dir edit/breakdown/reel \
        --out edit/breakdown/reel.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path


def load_words(path: Path) -> list[dict]:
    """Scribe-формат → список слов со start/end. Пустой список, если слов нет."""
    data = json.loads(path.read_text(encoding="utf-8"))
    words = data.get("words") if isinstance(data, dict) else data
    out: list[dict] = []
    for w in words or []:
        if w.get("type") not in (None, "word"):
            continue
        text = (w.get("text") or "").strip()
        if text and w.get("start") is not None and w.get("end") is not None:
            out.append({"text": text, "start": float(w["start"]), "end": float(w["end"])})
    return out


def load_shots(path: Path) -> list[tuple[float, float]]:
    """Границы кадров. Принимаем и список пар, и список словарей, и обёртку {"shots": [...]}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("shots", "scenes", "ranges"):
            if key in data:
                data = data[key]
                break
    shots: list[tuple[float, float]] = []
    for s in data or []:
        if isinstance(s, dict):
            start = s.get("start", s.get("start_time", s.get("start_seconds")))
            end = s.get("end", s.get("end_time", s.get("end_seconds")))
        elif isinstance(s, (list, tuple)) and len(s) >= 2:
            start, end = s[0], s[1]
        else:
            continue
        if start is None or end is None:
            continue
        start, end = float(start), float(end)
        if end > start:
            shots.append((start, end))
    return sorted(shots)


def extract_frames(video: Path, shots: list[tuple[float, float]], frames_dir: Path) -> list[dict]:
    """По кадру из середины каждого шота → jpg. Возвращает список для vision-MCP."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    pending: list[dict] = []
    for i, (start, end) in enumerate(shots):
        mid = start + (end - start) / 2
        out = frames_dir / f"shot_{i:03d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{mid:.3f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=720:-2", "-q:v", "4", str(out)],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if out.exists():
            pending.append({"shot": i, "at": round(mid, 2), "frame_path": str(out.resolve()),
                            "save_description_to": str((frames_dir / "desc" / f"{out.stem}.txt").resolve())})
    (frames_dir / "desc").mkdir(exist_ok=True)
    (frames_dir / "_pending_frames.json").write_text(
        json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    return pending


def build_sheets(frames_dir: Path, shots: list[tuple[float, float]], per_page: int = 12,
                 cell: int = 360) -> list[Path]:
    """Контактные листы кадров с подписями «номер · тайминг» — их читает сам агент.

    Так правая колонка заполняется по реальному просмотру: vision-MCP на кадрах рилса
    даёт слабые описания (замер 2026-09-16: 0,5 ₽ и 90–110 с на кадр, выдуманный текст).
    """
    from PIL import Image, ImageDraw

    frames = sorted(frames_dir.glob("shot_*.jpg"))
    if not frames:
        return []
    cols = 4
    sheets: list[Path] = []
    for page_no, start in enumerate(range(0, len(frames), per_page)):
        chunk = frames[start:start + per_page]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cell, rows * (cell + 26)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, fp in enumerate(chunk):
            im = Image.open(fp).convert("RGB")
            im.thumbnail((cell - 8, cell - 8))
            x, y = (i % cols) * cell, (i // cols) * (cell + 26)
            sheet.paste(im, (x + 4, y + 4))
            idx = int(fp.stem.split("_")[1])
            # дефис ASCII: дефолтный шрифт PIL не рисует длинное тире
            label = f"{idx}  {shots[idx][0]:.1f}-{shots[idx][1]:.1f}s" if idx < len(shots) else fp.stem
            draw.text((x + 6, y + cell + 6), label, fill="black")
        out = frames_dir / f"_sheet_{page_no + 1:02d}.png"
        sheet.save(out)
        sheets.append(out)
    return sheets


def read_descriptions(frames_dir: Path, count: int) -> list[str]:
    desc_dir = frames_dir / "desc"
    out: list[str] = []
    for i in range(count):
        p = desc_dir / f"shot_{i:03d}.txt"
        out.append(p.read_text(encoding="utf-8").strip().replace("\n", " ") if p.exists() else "")
    return out


def words_in(words: list[dict], start: float, end: float) -> list[dict]:
    return [w for w in words if w["start"] < end and w["end"] > start]


def build_metrics(words: list[dict], shots: list[tuple[float, float]],
                  per_shot: list[list[dict]], descriptions: list[str]) -> dict:
    duration = max((s[1] for s in shots), default=0.0)
    lens = [len(ws) for ws in per_shot if ws]
    hook_end = shots[2][1] if len(shots) >= 3 else (shots[-1][1] if shots else 0.0)
    boundaries = [s[0] for s in shots[1:]]
    starts = [w["start"] for w in words]
    on_word = sum(1 for b in boundaries if any(abs(b - s) <= 0.25 for s in starts))
    silent = sum(1 for ws in per_shot if not ws)
    talking = sum(1 for d in descriptions if d and ("говор" in d.lower() or "камер" in d.lower()))
    return {
        "duration": duration,
        "shots": len(shots),
        "words": len(words),
        "words_per_shot": (len(words) / len(shots)) if shots else 0.0,
        "median_phrase": statistics.median(lens) if lens else 0,
        "long_phrases_share": (sum(1 for n in lens if n > 12) / len(lens)) if lens else 0.0,
        "hook_end": hook_end,
        "cuts_per_min": (len(boundaries) / duration * 60) if duration else 0.0,
        "on_word_share": (on_word / len(boundaries)) if boundaries else 0.0,
        "silent_shots": silent,
        "talking_head_shots": talking,
        "longest_shot": max(((e - s, i) for i, (s, e) in enumerate(shots)), default=(0.0, -1)),
    }


def render(video: Path, per_shot: list[list[dict]], shots: list[tuple[float, float]],
           descriptions: list[str], m: dict) -> str:
    head = [
        f"# Разбор: {video.name}",
        "",
        f"**Метрики:** {m['duration']:.1f} с · {m['shots']} кадров · {m['words']} слов · "
        f"{m['words_per_shot']:.1f} слов/кадр · хук {m['hook_end']:.1f} с · "
        f"{m['cuts_per_min']:.0f} смен/мин",
        "",
        f"- Медиана фразы: {m['median_phrase']:.0f} слов; длиннее 12 слов — {m['long_phrases_share']:.0%} кадров",
        f"- Ключевое слово на стыке: {m['on_word_share']:.0%} границ",
        f"- Кадров без речи: {m['silent_shots']}",
        f"- Самый длинный кадр: {m['longest_shot'][0]:.1f} с (кадр {m['longest_shot'][1]})",
        "",
        "| Тайминг | Текст | Кадр |",
        "|---|---|---|",
    ]
    rows = []
    for i, (start, end) in enumerate(shots):
        text = " ".join(w["text"] for w in per_shot[i]).replace("|", "/")
        desc = (descriptions[i] if i < len(descriptions) else "").replace("|", "/")
        rows.append(f"| {start:.1f}–{end:.1f} | {text} | {desc} |")
    return "\n".join(head + rows) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Разбор рилса в раскадровку + метрики")
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--transcript", type=Path, required=True, help="Scribe-формат из transcribe_mcp.py")
    ap.add_argument("--shots", type=Path, required=True, help="JSON из scene_detect.py")
    ap.add_argument("--frames-dir", type=Path, default=None,
                    help="Вырезать по кадру из середины каждого шота (+ _pending_frames.json)")
    ap.add_argument("--sheet", action="store_true",
                    help="Собрать контактные листы кадров с подписями — их читает сам агент")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    for p in (args.video, args.transcript, args.shots):
        if not p.exists():
            sys.exit(f"файл не найден: {p}")

    words = load_words(args.transcript)
    shots = load_shots(args.shots)
    if not shots:
        sys.exit(f"в {args.shots} нет границ кадров — запусти helpers/scene_detect.py")

    per_shot = [words_in(words, s, e) for s, e in shots]

    if args.frames_dir:
        pending = extract_frames(args.video, shots, args.frames_dir)
        print(f"кадры: {len(pending)} → {args.frames_dir}")
        if args.sheet:
            sheets = build_sheets(args.frames_dir, shots)
            for s in sheets:
                print(f"контактный лист: {s}")
            print("открой листы, опиши кадры одной строкой каждый и сохрани в "
                  f"{args.frames_dir / 'desc'}/shot_NNN.txt")
        else:
            print(f"список кадров для vision-MCP: {args.frames_dir / '_pending_frames.json'}")
        print("затем запусти команду снова без --frames-dir")

    descriptions = read_descriptions(args.frames_dir, len(shots)) if args.frames_dir else [""] * len(shots)
    if not any(descriptions) and args.frames_dir is None:
        print("warning: описаний кадров нет — правая колонка останется пустой "
              "(сначала запусти с --frames-dir)")

    metrics = build_metrics(words, shots, per_shot, descriptions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.video, per_shot, shots, descriptions, metrics), encoding="utf-8")
    print(f"✓ {args.out}  ({metrics['shots']} кадров, {metrics['words']} слов, "
          f"хук {metrics['hook_end']:.1f} с, {metrics['cuts_per_min']:.0f} смен/мин)")


if __name__ == "__main__":
    main()
