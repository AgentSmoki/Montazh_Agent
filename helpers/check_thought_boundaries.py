"""Thought-boundary guard — ловит резы посреди мысли/синтагмы.

Закрывает дыру, которую НЕ ловят snap_to_word (рез по границе слова) и
detect_audio_spikes (технический pop). Эти проверяют МИКРО-корректность.
Здесь — МАКРО: завершена ли мысль на резе.

Симптом, ради которого написано: HOOK обрывался на «…который сам
настраивает…» — слово целое, щелчка нет, но мысль («…ВК рекламу») ампутирована.

Эвристика по каждому range.end (в transcript-time с учётом src_offset):
  1. Находим последнее слово внутри окна и первое слово ПОСЛЕ него.
  2. gap = next.start − last.end.
     - gap ≥ CLAUSE_GAP (0.30с) → вероятно конец clause/предложения → OK.
     - gap < CLAUSE_GAP → речь продолжается без паузы → рез посреди потока → WARN.
  3. Если последнее слово — «висящее» (предлог/частица/числительное/союз/
     местоимение-связка) → синтагма разорвана → WARN независимо от gap
     (Hard Rule #7b: не резать прилаг+сущ, предл+сущ, числ+сущ, частица+глаг).

Это ВАЛИДАТОР-предупреждение, не авто-правка: раздувать длину молча нельзя,
поэтому решение оставляем монтажёру/агенту (как со spike-detection).

Usage:
    from check_thought_boundaries import check_thought_cuts
    warnings = check_thought_cuts(edl, transcripts_dir)
"""
from __future__ import annotations

import json
from pathlib import Path

CLAUSE_GAP = 0.30  # сек — меньше = речь не остановилась, рез посреди мысли

# Слова, после которых резать нельзя — следующее слово к ним «приклеено».
# Предлоги, частицы, союзы, числительные-связки, указательные.
DANGLING_TAILS = {
    # предлоги
    "в", "во", "на", "за", "к", "ко", "с", "со", "из", "от", "до", "по",
    "при", "про", "под", "над", "об", "о", "у", "для", "без", "через",
    # частицы / союзы
    "не", "ни", "и", "а", "но", "что", "чтобы", "как", "это", "этот",
    "эта", "эти", "наш", "наша", "наши", "свой", "своя",
    # числительные-связки (число перед существительным)
    "два", "три", "пять", "шесть", "десять", "сорок",
}


def _words(transcripts_dir: Path, stem: str) -> list[dict]:
    p = transcripts_dir / f"{stem}.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [w for w in (data.get("words") or []) if w.get("type") == "word"]


def _resolve_stem(r: dict, sources_map: dict) -> str | None:
    try:
        from snap_to_word import resolve_transcript_stem
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


def check_thought_cuts(
    edl: dict, transcripts_dir: Path, clause_gap: float = CLAUSE_GAP
) -> list[dict]:
    """Вернуть список предупреждений о резах посреди мысли."""
    sources_map = edl.get("sources", {})
    cache: dict[str, list[dict]] = {}
    warnings: list[dict] = []

    for i, r in enumerate(edl.get("ranges", [])):
        stem = _resolve_stem(r, sources_map)
        if not stem:
            continue
        if stem not in cache:
            cache[stem] = _words(transcripts_dir, stem)
        words = cache[stem]
        if not words:
            continue

        offset = float(r.get("src_offset", 0.0))
        end_t = float(r["end"]) + offset

        # последнее слово внутри окна
        inside = [w for w in words if w.get("end") is not None and w["end"] <= end_t + 0.05]
        if not inside:
            continue
        last = max(inside, key=lambda w: w["end"])
        after = [w for w in words if w.get("start") is not None and w["start"] > last["end"] - 0.001]
        if not after:
            continue  # окно до конца файла — мысль завершена де-факто
        nxt = min(after, key=lambda w: w["start"])
        gap = nxt["start"] - last["end"]

        last_norm = (last.get("text") or "").lower().strip(" ,.!?;:—-«»\"")
        reasons = []
        if last_norm in DANGLING_TAILS:
            reasons.append(f"висящее слово '{last_norm}' (синтагма разорвана, Rule 7b)")
        if gap < clause_gap:
            reasons.append(f"пауза после реза всего {gap*1000:.0f}мс (<{clause_gap*1000:.0f}) — речь не остановилась")

        if reasons:
            warnings.append({
                "beat_idx": i,
                "beat": r.get("beat", ""),
                "source": r.get("source"),
                "end": round(float(r["end"]), 3),
                "last_word": last.get("text", ""),
                "next_word": nxt.get("text", ""),
                "gap_s": round(gap, 3),
                "reasons": reasons,
                "fix_hint": f"тяни end до конца фразы (следующая пауза ≥{clause_gap}с) "
                            f"или режь раньше — после слова с падающей интонацией",
            })

    return warnings


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Проверить резы EDL на завершённость мысли")
    ap.add_argument("edl", type=Path)
    ap.add_argument("--transcripts-dir", type=Path, required=True)
    args = ap.parse_args()
    edl = json.loads(args.edl.read_text(encoding="utf-8"))
    ws = check_thought_cuts(edl, args.transcripts_dir.resolve())
    if not ws:
        print("✓ thought-guard: все резы на завершённой мысли")
        return
    print(f"⚠️  thought-guard: {len(ws)} подозрительных рез(ов):")
    for w in ws:
        print(f"  [{w['beat_idx']:02d}] {w['source']} '{w['beat']}' end={w['end']}с: "
              f"…{w['last_word']} | {w['next_word']}…  (gap={w['gap_s']}с)")
        for rs in w["reasons"]:
            print(f"        – {rs}")


if __name__ == "__main__":
    main()
