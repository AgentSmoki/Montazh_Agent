"""Apply padding (±N мс) к каждому range в EDL.

Решает Hard Rule #7 SKILL.md: «Padding 30-200ms на cut-edges».

ДВА РЕЖИМА:

1. **--smart** (Recommended, по Gemini Deep Research) — padding зависит от
   последней фонемы слова на границе:
   - Гласные (а/о/у/и/е/я/ы) → +30мс post-pad (оборвутся чище)
   - Шипящие/мягкий знак/-ть/-ся/-сь (ть/ся/сь/ш/щ/ч/ц/ь) → +120мс
     (шипящие звучат дольше после word.end в ASR)
   - Прочие согласные → +50мс
   - Pre-pad всегда +30-50мс (захват микро-смыкания губ перед взрывными)

   Требует доступа к transcripts/<source>.json для определения последней буквы.

2. **--simple** (legacy) — фиксированный padding pad_in/pad_out для всех ranges.

Источник: Gemini Deep Research, май 2026 — Descript Underlord использует
именно асимметричный smart padding по фонемам.

Использовать ПОСЛЕ `snap_to_word.py` — иначе padding впадает в зону соседних слов
а не в тишину.

Usage:
    # Smart (рекомендуется):
    python helpers/apply_padding.py <edl.json> --in-place --smart \\
        --transcripts-dir <edit>/transcripts/

    # Simple legacy:
    python helpers/apply_padding.py <edl.json> --simple --pad-in 100 --pad-out 150 -o ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Smart padding rules по Gemini Deep Research (Descript-style)
VOWELS = set("аоуиеяыёэю")
LONG_TAIL_CHARS = set("ьшщчц") | {"ь"}  # шипящие + мягкий знак
LONG_TAIL_SUFFIXES = ("ть", "ся", "сь", "шь", "жь", "чь", "щь")

POST_PAD_VOWEL_MS = 30        # гласные обрываются чище
POST_PAD_LONG_TAIL_MS = 120   # шипящие звучат дольше после word.end
POST_PAD_DEFAULT_MS = 50      # обычные согласные

PRE_PAD_MS = 40               # фикс — захват микро-смыкания губ


def smart_post_pad_for_text(text: str) -> tuple[int, str]:
    """Возвращает (post_pad_ms, reason) на основе последней фонемы слова."""
    if not text:
        return POST_PAD_DEFAULT_MS, "empty"
    t = text.lower().strip(" ,.!?;:")
    if not t:
        return POST_PAD_DEFAULT_MS, "punct-only"

    # Глагольные/возвратные окончания — длинный хвост
    for suf in LONG_TAIL_SUFFIXES:
        if t.endswith(suf):
            return POST_PAD_LONG_TAIL_MS, f"verb/refl '{suf}'"

    last_char = t[-1]
    if last_char in VOWELS:
        return POST_PAD_VOWEL_MS, f"vowel '{last_char}'"
    if last_char in LONG_TAIL_CHARS:
        return POST_PAD_LONG_TAIL_MS, f"sibilant '{last_char}'"
    return POST_PAD_DEFAULT_MS, f"consonant '{last_char}'"


def find_last_word_text(end: float, words: list[dict]) -> str:
    """Найти текст последнего слова которое заканчивается ≤ end + 50мс."""
    best = None
    for w in words:
        we = w.get("end")
        if we is None:
            continue
        if we <= end + 0.05:
            if best is None or we > best.get("end", -1):
                best = w
    return (best.get("text") if best else "") or ""


def _resolve_stem(r: dict, sources_map: dict) -> str | None:
    """Stem транскрипта для range — общий резолвер с snap_to_word.

    Учитывает `transcript`-override (для preprocessed HOOK/CTA/зум) и
    sources-mapping. Импортируем из snap_to_word, чтобы логика была одна.
    """
    try:
        from snap_to_word import resolve_transcript_stem  # same dir
        return resolve_transcript_stem(r, sources_map)
    except Exception:
        src = r.get("source")
        if not src:
            return None
        ov = r.get("transcript")
        if ov:
            return Path(sources_map[ov]).stem if ov in sources_map else Path(ov).stem
        mapped = sources_map.get(src)
        return Path(mapped).stem if mapped else src


def apply_smart_padding(
    edl: dict,
    transcripts_dir: Path,
    verbose: bool = True,
) -> dict:
    """Smart: padding по последней букве слова на границе range.end."""
    cache: dict[str, list[dict]] = {}
    sources_map = edl.get("sources", {})

    for i, r in enumerate(edl.get("ranges", [])):
        src = r.get("source")
        if not src:
            continue
        # Резолвим транскрипт через override/mapping (а не по имени источника).
        # Снято «слепое пятно торцов»: HOOK/CTA/зум с проставленным transcript
        # теперь паддятся по реальной последней фонеме, а не дефолтом.
        stem = _resolve_stem(r, sources_map)
        if stem not in cache:
            tp = transcripts_dir / f"{stem}.json"
            if tp.exists():
                try:
                    data = json.loads(tp.read_text(encoding="utf-8"))
                    cache[stem] = [w for w in (data.get("words") or [])
                                   if w.get("type") == "word"]
                except Exception:
                    cache[stem] = []
            else:
                cache[stem] = []
        words = cache[stem]
        pad_in_s = PRE_PAD_MS / 1000.0
        if words:
            offset = float(r.get("src_offset", 0.0))
            last_text = find_last_word_text(r["end"] + offset, words)
            pad_out_ms, reason = smart_post_pad_for_text(last_text)
        else:
            # Нет транскрипта (generated B-roll и т.п.) — дефолтный хвост.
            pad_out_ms = POST_PAD_DEFAULT_MS
            reason = "no-transcript-default"

        pad_out_s = pad_out_ms / 1000.0
        old_start = r["start"]
        old_end = r["end"]
        r["start"] = max(0.0, old_start - pad_in_s)
        r["end"] = old_end + pad_out_s
        r["_pad_log"] = {
            "mode": "smart",
            "pre_ms": PRE_PAD_MS,
            "post_ms": pad_out_ms,
            "post_reason": reason,
        }
        if verbose:
            print(f"  [{i:02d}] {src} {old_start:.3f}-{old_end:.3f} → "
                  f"{r['start']:.3f}-{r['end']:.3f}  "
                  f"(+{PRE_PAD_MS}мс / +{pad_out_ms}мс [{reason}])")

    if "total_duration_s" in edl:
        edl["total_duration_s"] = sum(r["end"] - r["start"] for r in edl["ranges"])
    return edl


def apply_simple_padding(
    edl: dict,
    pad_in_ms: int = 100,
    pad_out_ms: int = 150,
    verbose: bool = True,
) -> dict:
    """Legacy режим — фикс ±N мс. Применять только если нет transcripts."""
    pad_in = pad_in_ms / 1000.0
    pad_out = pad_out_ms / 1000.0
    for i, r in enumerate(edl.get("ranges", [])):
        old_start = r["start"]
        old_end = r["end"]
        r["start"] = max(0.0, old_start - pad_in)
        r["end"] = old_end + pad_out
        r["_pad_log"] = {"mode": "simple", "pre_ms": pad_in_ms, "post_ms": pad_out_ms}
        if verbose:
            print(f"  [{i:02d}] {r.get('source','?')} "
                  f"{old_start:.3f}-{old_end:.3f} → "
                  f"{r['start']:.3f}-{r['end']:.3f}  (+{pad_in_ms}/+{pad_out_ms}ms)")
    if "total_duration_s" in edl:
        edl["total_duration_s"] = sum(r["end"] - r["start"] for r in edl["ranges"])
    return edl


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply padding ±ms к EDL ranges")
    ap.add_argument("edl", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--in-place", action="store_true")
    mode_group = ap.add_mutually_exclusive_group()
    mode_group.add_argument("--smart", action="store_true",
                            help="Asymmetric по последней букве (default если есть transcripts)")
    mode_group.add_argument("--simple", action="store_true",
                            help="Legacy фикс pad_in/pad_out")
    ap.add_argument("--transcripts-dir", type=Path, default=None,
                    help="Для smart mode")
    ap.add_argument("--pad-in", type=int, default=100, help="(simple) ms")
    ap.add_argument("--pad-out", type=int, default=150, help="(simple) ms")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    edl = json.loads(args.edl.read_text(encoding="utf-8"))

    # Auto: если есть transcripts-dir и не указано --simple → smart
    use_smart = args.smart or (args.transcripts_dir and not args.simple)
    if use_smart:
        if not args.transcripts_dir:
            sys.exit("--smart требует --transcripts-dir")
        edl = apply_smart_padding(edl, args.transcripts_dir.resolve(), verbose=not args.quiet)
    else:
        edl = apply_simple_padding(edl, args.pad_in, args.pad_out, verbose=not args.quiet)

    out_path = args.edl if args.in_place else args.output
    if not out_path:
        sys.exit("укажи -o или --in-place")
    out_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2))
    print(f"✓ {out_path}  (total_duration: {edl.get('total_duration_s', 0):.2f}с, "
          f"mode={'smart' if use_smart else 'simple'})")


if __name__ == "__main__":
    main()
