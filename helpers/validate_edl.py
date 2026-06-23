"""EDL-валидатор — дешёвая страховка перед рендером.

Ловит то, что иначе всплывёт как сломанный рендер или молчаливый desync:
  - битый/неполный JSON (отсутствуют version/sources/ranges)
  - range.source, которого нет в sources
  - start ≥ end, отрицательные времена
  - файл-источник не существует
  - overlay.file / subtitles не существует
  - transcript-override не резолвится в transcripts/
  - overlay.start_in_output за пределами таймлайна (warning)

Возвращает (errors, warnings). Пустой errors → можно рендерить.

Usage:
    from validate_edl import validate_edl
    errors, warnings = validate_edl(edl, edit_dir)
"""
from __future__ import annotations

import json
from pathlib import Path


def _resolve_path(maybe_path: str, base: Path) -> Path:
    p = Path(maybe_path)
    return p if p.is_absolute() else (base / p).resolve()


def validate_edl(edl: dict, edit_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # --- top-level schema ---
    for key in ("sources", "ranges"):
        if key not in edl:
            errors.append(f"нет обязательного поля '{key}'")
    if errors:
        return errors, warnings

    sources = edl.get("sources") or {}
    ranges = edl.get("ranges") or []
    if not isinstance(sources, dict) or not sources:
        errors.append("'sources' пуст или не объект")
    if not isinstance(ranges, list) or not ranges:
        errors.append("'ranges' пуст или не список")
    if errors:
        return errors, warnings

    # --- sources files exist ---
    for key, path in sources.items():
        p = _resolve_path(path, edit_dir)
        if not p.exists():
            errors.append(f"source '{key}': файла нет — {p}")

    # --- transcripts dir (для override-резолва) ---
    transcripts_dir = edit_dir / "transcripts"

    # --- ranges ---
    total = 0.0
    for i, r in enumerate(ranges):
        src = r.get("source")
        if src is None:
            errors.append(f"range[{i}]: нет 'source'")
            continue
        if src not in sources:
            errors.append(f"range[{i}]: source '{src}' отсутствует в sources")
        try:
            s = float(r["start"]); e = float(r["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"range[{i}] '{r.get('beat','')}': нет валидных start/end")
            continue
        if s < 0:
            errors.append(f"range[{i}] '{r.get('beat','')}': start<0 ({s})")
        if e <= s:
            errors.append(f"range[{i}] '{r.get('beat','')}': end≤start ({s}-{e})")
        total += max(0.0, e - s)

        # transcript override резолвится?
        ov = r.get("transcript")
        if ov:
            stem = Path(sources[ov]).stem if ov in sources else Path(ov).stem
            if not (transcripts_dir / f"{stem}.json").exists():
                warnings.append(
                    f"range[{i}] '{r.get('beat','')}': transcript-override '{ov}' "
                    f"→ {stem}.json не найден — snap/pad/thought-guard пропустят бит"
                )

        # effect известен?
        eff = r.get("effect")
        if eff and eff not in ("pushin", "none", ""):
            warnings.append(f"range[{i}]: неизвестный effect '{eff}' — будет проигнорирован")

    # --- overlays ---
    for j, ov in enumerate(edl.get("overlays") or []):
        f = ov.get("file")
        if not f:
            errors.append(f"overlay[{j}]: нет 'file'")
            continue
        if not _resolve_path(f, edit_dir).exists():
            errors.append(f"overlay[{j}]: файла нет — {f}")
        st = ov.get("start_in_output")
        if st is not None and float(st) > total + 0.5:
            warnings.append(
                f"overlay[{j}] start_in_output={st}с за пределами таймлайна (~{total:.1f}с)"
            )

    # --- subtitles ---
    subs = edl.get("subtitles")
    if subs and not _resolve_path(subs, edit_dir).exists():
        warnings.append(f"subtitles '{subs}' не найден")

    return errors, warnings


def main() -> None:
    import argparse, sys
    ap = argparse.ArgumentParser(description="Validate EDL before render")
    ap.add_argument("edl", type=Path)
    args = ap.parse_args()
    edl = json.loads(args.edl.read_text(encoding="utf-8"))
    errors, warnings = validate_edl(edl, args.edl.resolve().parent)
    for w in warnings:
        print(f"⚠️  {w}")
    for e in errors:
        print(f"❌ {e}")
    if errors:
        sys.exit(1)
    print(f"✓ EDL валиден ({len(edl.get('ranges', []))} ranges)")


if __name__ == "__main__":
    main()
