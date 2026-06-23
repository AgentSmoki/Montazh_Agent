"""Snap EDL ranges к ближайшим word-boundaries из transcripts/.

Решает Hard Rule #6 SKILL.md: «Never cut inside a word — snap to word boundaries».

Алгоритм для каждого `range`:
1. Загружает `<edit>/transcripts/<source>.json` (Scribe-формат с words[]).
2. Для `range.start`: ищет максимальный `word.start` ≤ `range.start`.
   Если разница > 200мс — оставляет как есть (cut в тишине).
3. Для `range.end`: ищет минимальный `word.end` ≥ `range.end`.
   То же — если > 200мс расхождение, оставляет.
4. Логирует каждое изменение.

Использовать ДО `apply_padding.py`. Идемпотентен.

Usage:
    python helpers/snap_to_word.py <edl.json> -o <edl_snapped.json> \\
        --transcripts-dir <edit>/transcripts/
    python helpers/snap_to_word.py <edl.json> --in-place --transcripts-dir ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


MAX_DRIFT_MS = 200  # если слово ближайшее дальше — не двигаем (вероятно в тишине)


def load_words(transcript_path: Path) -> list[dict]:
    """Возвращает только type=='word' токены из Scribe JSON."""
    if not transcript_path.exists():
        return []
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    return [w for w in (data.get("words") or []) if w.get("type") == "word"]


def snap_left(start: float, words: list[dict]) -> tuple[float, str]:
    """Найти ближайший word.start ≤ start, в пределах MAX_DRIFT_MS.
    Возвращает (snapped_start, note)."""
    if not words:
        return start, "no-transcript"

    best_w = None
    for w in words:
        ws = w.get("start")
        if ws is None or ws > start:
            continue
        if best_w is None or ws > best_w.get("start", -1):
            best_w = w

    if best_w is None:
        # start раньше первого слова → берём первое
        first = words[0]
        delta_ms = (first["start"] - start) * 1000
        return first["start"], f"first-word +{delta_ms:.0f}ms"

    delta_ms = (start - best_w["start"]) * 1000
    if delta_ms > MAX_DRIFT_MS:
        return start, f"in-silence (nearest word '{best_w.get('text','')[:20]}' -{delta_ms:.0f}ms)"

    return best_w["start"], f"snap '{best_w.get('text','')[:20]}' -{delta_ms:.0f}ms"


def snap_right(end: float, words: list[dict]) -> tuple[float, str]:
    """Найти ближайший word.end ≥ end, в пределах MAX_DRIFT_MS."""
    if not words:
        return end, "no-transcript"

    best_w = None
    for w in words:
        we = w.get("end")
        if we is None or we < end:
            continue
        if best_w is None or we < best_w.get("end", float("inf")):
            best_w = w

    if best_w is None:
        # end позже последнего слова → берём последнее
        last = words[-1]
        delta_ms = (end - last["end"]) * 1000
        return last["end"], f"last-word -{delta_ms:.0f}ms"

    delta_ms = (best_w["end"] - end) * 1000
    if delta_ms > MAX_DRIFT_MS:
        return end, f"in-silence (nearest word '{best_w.get('text','')[:20]}' +{delta_ms:.0f}ms)"

    return best_w["end"], f"snap '{best_w.get('text','')[:20]}' +{delta_ms:.0f}ms"


def resolve_transcript_stem(r: dict, sources_map: dict) -> str | None:
    """Определить stem транскрипта для range.

    Приоритет:
    1. Явный override `r["transcript"]` — может быть ключом sources
       (тогда берём stem его mapped-пути) или прямым stem'ом ("IMG_3521").
       Нужен для preprocessed-источников (HOOK_vert, *_zoom), у которых имя
       файла не совпадает с именем транскрипта, но контент тот же.
    2. `sources[src]` mapping → stem пути (C3008 → IMG_3008).
    3. fallback — сам src_key.

    Возвращает None если source отсутствует.
    """
    src = r.get("source")
    if not src:
        return None
    ov = r.get("transcript")
    if ov:
        if ov in sources_map:
            return Path(sources_map[ov]).stem
        return Path(ov).stem
    mapped = sources_map.get(src)
    if mapped:
        return Path(mapped).stem
    return src


def snap_edl(edl: dict, transcripts_dir: Path, verbose: bool = True) -> dict:
    """Modify EDL in-place: snap each range to word-boundaries.

    Иммунитета по имени источника БОЛЬШЕ НЕТ. Любой range, для которого
    резолвится транскрипт (через `transcript`-override или sources-mapping),
    снэпается к границам слов — включая HOOK/CTA/зум, если им проставлен
    `transcript`. Это закрывает «слепое пятно торцов»: раньше самый важный
    бит (хук) единственный шёл без защиты и обрывался посреди фразы.

    `src_offset` (сек) — сдвиг между таймлайном файла-источника и таймлайном
    транскрипта (если preprocessed-файл обрезан с начала). По умолчанию 0.
    """
    transcripts_cache: dict[str, list[dict]] = {}
    log: list[str] = []
    sources_map = edl.get("sources", {})

    for i, r in enumerate(edl.get("ranges", [])):
        src = r.get("source")
        if not src:
            continue
        stem = resolve_transcript_stem(r, sources_map)
        if stem not in transcripts_cache:
            transcripts_cache[stem] = load_words(transcripts_dir / f"{stem}.json")

        words = transcripts_cache[stem]
        if not words:
            # Действительно нет транскрипта (generated B-roll и т.п.) — оставляем.
            if verbose:
                log.append(f"  [{i:02d}] {src} — нет transcript '{stem}.json', skip")
            continue

        offset = float(r.get("src_offset", 0.0))
        old_start = r["start"]
        old_end = r["end"]
        # range-time → transcript-time (+offset), снэп, обратно (−offset)
        new_start, note_l = snap_left(old_start + offset, words)
        new_end, note_r = snap_right(old_end + offset, words)
        new_start -= offset
        new_end -= offset

        if abs(new_start - old_start) > 0.001 or abs(new_end - old_end) > 0.001:
            r["start"] = new_start
            r["end"] = new_end
            r["_snap_log"] = {"in": note_l, "out": note_r, "transcript": stem}
            if verbose:
                log.append(
                    f"  [{i:02d}] {src}←{stem} {old_start:.3f}-{old_end:.3f} → "
                    f"{new_start:.3f}-{new_end:.3f}  [{note_l} | {note_r}]"
                )

    if verbose:
        print("snap_to_word: переcнэплено", sum(1 for r in edl["ranges"] if "_snap_log" in r), "из", len(edl["ranges"]))
        for ln in log:
            print(ln)

    return edl


def main() -> None:
    ap = argparse.ArgumentParser(description="Snap EDL ranges к word-boundaries")
    ap.add_argument("edl", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--transcripts-dir", type=Path, required=True,
                    help="Папка с *.json (Scribe-формат с words[])")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    edl = json.loads(args.edl.read_text(encoding="utf-8"))
    edl = snap_edl(edl, args.transcripts_dir.resolve(), verbose=not args.quiet)

    out_path = args.edl if args.in_place else args.output
    if not out_path:
        sys.exit("укажи -o или --in-place")
    out_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2))
    print(f"✓ {out_path}")


if __name__ == "__main__":
    main()
