"""Инструкции для генерации недостающих B-roll кадров через MCP.

Сам этот скрипт — stub, потому что MCP-вызовы делает агент в чате, а не Python.
Скрипт принимает EDL и находит спаны с маркером `{"need_broll": true, ...}`,
выдаёт агенту список конкретных промптов для MCP-вызовов.

Стратегия (для использования агентом):
  - Default модель: Kling 3.0 через Higgsfield MCP ($0.09-0.14/сек, дёшево)
  - Upgrade на Veo 3.1 Fast если в EDL есть `{"need_audio": true}` (только Veo даёт native audio)
  - Для статичных вставок (1-2 сек) → Nano Banana Pro → image-to-video с last-frame conditioning
  - CLIP-continuity check после генерации (через match_video_to_audio логику)
  - Бюджет per-project ограничен $X в project.md

Usage:
    python helpers/broll_generator.py <edl.json> --check-budget 5.00
    python helpers/broll_generator.py <edl.json> --extract-prompts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Ценник на май 2026 (см. research/02_mcp_catalog.md)
PRICES_USD_PER_SEC = {
    "kling-3.0": 0.12,        # Higgsfield, average $0.09-0.14
    "veo-3.1-fast": 0.15,     # Higgsfield, единственный с native audio
    "veo-3.1-standard": 0.40,
    "hailuo-02": 0.05,        # дешёвый fallback
    "seedance-2.0": 0.10,
}


def select_model(span: dict) -> str:
    """Выбор модели на основе требований спана."""
    if span.get("need_audio"):
        return "veo-3.1-fast"
    if span.get("budget") == "cheap":
        return "hailuo-02"
    return "kling-3.0"  # дефолт


def extract_broll_spans(edl: dict) -> list[dict]:
    """Найти все спаны где `need_broll: true`."""
    out = []
    for i, r in enumerate(edl.get("ranges", [])):
        if r.get("need_broll"):
            out.append({
                "idx": i,
                "duration": round(float(r.get("end", 0)) - float(r.get("start", 0)), 2),
                "prompt": r.get("broll_prompt", ""),
                "need_audio": r.get("need_audio", False),
                "budget": r.get("budget"),
                "model_recommended": select_model(r),
            })
    return out


def estimate_cost(spans: list[dict]) -> float:
    total = 0.0
    for s in spans:
        rate = PRICES_USD_PER_SEC.get(s["model_recommended"], 0.15)
        total += s["duration"] * rate
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description="Извлекает B-roll-задачи из EDL для MCP-вызовов")
    ap.add_argument("edl", type=Path, help="Путь к edl.json")
    ap.add_argument("--check-budget", type=float, default=None,
                    help="Проверка бюджета в USD")
    ap.add_argument("--extract-prompts", action="store_true",
                    help="Печать инструкций для агента")
    args = ap.parse_args()

    edl = json.loads(args.edl.read_text())
    spans = extract_broll_spans(edl)

    if not spans:
        print("В EDL нет спанов с need_broll: true. B-roll не требуется.")
        return

    cost = estimate_cost(spans)
    print(f"Найдено {len(spans)} B-roll-спанов, оценка стоимости: ~${cost:.2f}")

    if args.check_budget and cost > args.check_budget:
        print(f"⚠️ Превышен бюджет ${args.check_budget:.2f}. Требуется подтверждение пользователя.")
        sys.exit(1)

    if args.extract_prompts:
        print("\nИнструкции для агента (вызови каждое через MCP):")
        for s in spans:
            model = s["model_recommended"]
            print(f"\n[span {s['idx']}, {s['duration']}s, model={model}]")
            print(f"  prompt: {s['prompt'][:200]}")
            if model.startswith("veo"):
                print(f"  MCP: mcp__higgsfield__generate_video model=veo-3.1-fast")
            else:
                print(f"  MCP: mcp__higgsfield__generate_video model={model}")
            print(f"  → сохрани в edit/generated/{s['idx']:03d}.mp4 + manifest.json")
            print(f"     (Hard Rule #13: manifest должен содержать prompt + seed + model + checksum)")


if __name__ == "__main__":
    main()
