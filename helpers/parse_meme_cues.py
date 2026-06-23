"""Парсер мем-вставок из сценария → overlays для EDL.

В сценарии (scenario.md) мем задаётся одним из способов:
  [мем:🤯]                  — по эмодзи (словарь EMOJI_QUERIES в meme_fetch)
  [мем: confused math lady] — текстовый запрос
  [meme: mind blown]        — англ. синоним
  [мем:🤯 @3.5]             — с явным временем появления (сек в output-таймлайне)
  [мем:🤯 dur=2.0]          — с явной длительностью
  [мем:🤯 full]             — fullscreen-вставка вместо center
  [мем:🤯 gif]              — взять gif вместо видео-клипа

Каждый cue → находит мем через meme_fetch, скачивает, добавляет overlay в EDL:
  {"file": "memes/<hash>.mp4", "start_in_output": T, "duration": D,
   "position": "center"|"topleft", "scale_w": 0.85, "comment": "meme: ..."}

По умолчанию (по просьбе Богдана): position=center, scale_w=0.82.
Если время не указано — мем НЕ может быть позиционирован автоматически
(нужен output-таймлайн), поэтому без @T cue требует ручной привязки —
функция вернёт его в `unplaced` со скачанным файлом, агент проставит время.

CLI:
    python helpers/parse_meme_cues.py <scenario.md> --edit-dir <edit> [--apply <edl.json>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meme_fetch import fetch_and_cache  # noqa: E402

# [мем:...] / [meme:...] — захватываем содержимое до ]
CUE_RE = re.compile(r"\[(?:мем|meme)\s*:\s*([^\]]+)\]", re.IGNORECASE)

DEFAULT_SCALE_W = 0.82
DEFAULT_DURATION = 2.0


def parse_cue_body(body: str) -> dict:
    """Разобрать тело cue на query + модификаторы (@T, dur=, full, gif)."""
    body = body.strip()
    opts = {"position": "center", "scale_w": DEFAULT_SCALE_W,
            "duration": DEFAULT_DURATION, "kind": "clips", "prefer": "mp4",
            "start": None}
    # @T — время
    m = re.search(r"@([0-9]+(?:\.[0-9]+)?)", body)
    if m:
        opts["start"] = float(m.group(1)); body = body.replace(m.group(0), "")
    # dur=
    m = re.search(r"dur=([0-9]+(?:\.[0-9]+)?)", body)
    if m:
        opts["duration"] = float(m.group(1)); body = body.replace(m.group(0), "")
    # full / center
    if re.search(r"\bfull\b", body, re.IGNORECASE):
        opts["position"] = "topleft"; opts["scale_w"] = 1.0
        body = re.sub(r"\bfull\b", "", body, flags=re.IGNORECASE)
    # gif
    if re.search(r"\bgif\b", body, re.IGNORECASE):
        opts["kind"] = "gifs"; opts["prefer"] = "gif"
        body = re.sub(r"\bgif\b", "", body, flags=re.IGNORECASE)
    opts["query"] = body.strip(" ,")
    return opts


def parse_scenario(scenario_path: Path, edit_dir: Path) -> dict:
    """Найти все cue, скачать мемы. Вернуть {placed:[overlay...], unplaced:[...]}."""
    text = scenario_path.read_text(encoding="utf-8")
    placed, unplaced = [], []
    for m in CUE_RE.finditer(text):
        opts = parse_cue_body(m.group(1))
        cue = opts["query"]
        res = fetch_and_cache(cue, edit_dir, kind=opts["kind"], prefer=opts["prefer"])
        if not res:
            unplaced.append({"cue": cue, "error": "not found"})
            continue
        rel = "memes/" + Path(res["path"]).name
        item = {
            "file": rel,
            "duration": opts["duration"],
            "position": opts["position"],
            "scale_w": opts["scale_w"],
            "comment": f"meme: {cue} «{res.get('title','')}»",
        }
        if opts["start"] is not None:
            item["start_in_output"] = opts["start"]
            placed.append(item)
        else:
            unplaced.append({**item, "cue": cue,
                             "note": "нет @T — проставь start_in_output вручную"})
    return {"placed": placed, "unplaced": unplaced}


def main() -> None:
    ap = argparse.ArgumentParser(description="Парсинг [мем:...] из сценария")
    ap.add_argument("scenario", type=Path)
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--apply", type=Path, default=None,
                    help="EDL.json — дописать placed-мемы в overlays")
    args = ap.parse_args()

    result = parse_scenario(args.scenario, args.edit_dir.resolve())
    print(f"placed: {len(result['placed'])}, unplaced: {len(result['unplaced'])}")
    for p in result["placed"]:
        print(f"  ✓ @{p['start_in_output']}с  {p['comment']}")
    for u in result["unplaced"]:
        tag = u.get("error") or u.get("note") or ""
        print(f"  ⚠ {u.get('cue','')}: {tag}  {u.get('file','')}")

    if args.apply and result["placed"]:
        edl = json.loads(args.apply.read_text(encoding="utf-8"))
        edl.setdefault("overlays", []).extend(result["placed"])
        args.apply.write_text(json.dumps(edl, ensure_ascii=False, indent=2))
        print(f"✓ {len(result['placed'])} мем(ов) дописано в {args.apply.name}")


if __name__ == "__main__":
    main()
