"""Готовит подсказки для агента — какие форматы вывода предложить пользователю.

На вход: inventory.json (от inventory.py) + опционально scenario.md.
На выход: markdown-блок с 2-3 рекомендованными форматами и почему.

LLM-агент читает этот вывод и формирует своё предложение пользователю.
Сам этот скрипт LLM не вызывает — он чисто эвристический.

Usage:
    python helpers/format_recommender.py <edit_dir>/inventory.json
    python helpers/format_recommender.py <edit_dir>/inventory.json --scenario scenario.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Пресеты форматов вывода
FORMATS = {
    "reels_9_16_60": {
        "name": "Reels / Shorts / TikTok",
        "aspect": "9:16 (1080×1920)",
        "duration_s": 60,
        "subs_style": "bold-overlay (2-словные UPPERCASE, MarginV=90)",
        "platforms": "Instagram Reels, YouTube Shorts, TikTok",
        "когда": "вертикальный talking-head или быстрый монтаж под мобилу",
    },
    "reels_9_16_30": {
        "name": "Reels короткий (хук)",
        "aspect": "9:16 (1080×1920)",
        "duration_s": 30,
        "subs_style": "bold-overlay",
        "platforms": "TikTok, Reels, Shorts",
        "когда": "тизер / хук / 1 пойнт",
    },
    "square_1_1_90": {
        "name": "Square / Feed",
        "aspect": "1:1 (1080×1080)",
        "duration_s": 90,
        "subs_style": "natural-sentence",
        "platforms": "Instagram Feed, LinkedIn, X",
        "когда": "ленточный пост, не вертикалка но и не горизонт",
    },
    "youtube_16_9_180": {
        "name": "YouTube",
        "aspect": "16:9 (1920×1080)",
        "duration_s": 180,
        "subs_style": "natural-sentence",
        "platforms": "YouTube",
        "когда": "горизонтальное long-form, туториал, лекция",
    },
    "lecture_16_9_long": {
        "name": "Lecture / Webinar",
        "aspect": "16:9 (1920×1080)",
        "duration_s": 600,
        "subs_style": "natural-sentence",
        "platforms": "YouTube, Vimeo, корпоративные платформы",
        "когда": "длинный материал с минимальным монтажом, education",
    },
    "teaser_9_16_15": {
        "name": "Teaser",
        "aspect": "9:16 (1080×1920)",
        "duration_s": 15,
        "subs_style": "bold-overlay",
        "platforms": "Reels, Shorts, TikTok",
        "когда": "сверхкороткий promo для запуска кампании",
    },
}


def recommend(items: list[dict], scenario_text: str = "") -> list[str]:
    """Эвристика: какие 2-3 формата предложить."""
    videos = [x for x in items if x.get("kind") == "video"]
    if not videos:
        return ["reels_9_16_60", "square_1_1_90", "youtube_16_9_180"]

    aspects = [v.get("aspect_class") for v in videos]
    total_dur = sum(v.get("duration_sec", 0) for v in videos)
    n_clips = len(videos)
    vertical = sum(1 for a in aspects if a == "vertical")
    horizontal = sum(1 for a in aspects if a == "horizontal")

    suggestions: list[str] = []

    # Если все вертикалки → рилзы по умолчанию
    if vertical == n_clips:
        suggestions.append("reels_9_16_60")
        if total_dur > 90:
            suggestions.append("reels_9_16_30")
        suggestions.append("square_1_1_90")  # альтернатива для feed
    elif horizontal == n_clips:
        # Всё горизонтально → YouTube/лекция
        if total_dur > 300:
            suggestions.append("lecture_16_9_long")
        suggestions.append("youtube_16_9_180")
        suggestions.append("reels_9_16_60")  # можно ужать в шортс
    else:
        # Смешанные — даём максимум вариантов
        suggestions.append("reels_9_16_60")
        suggestions.append("square_1_1_90")
        suggestions.append("youtube_16_9_180")

    # Лимит — 3 предложения
    return suggestions[:3]


def render_markdown(items: list[dict], suggestions: list[str], scenario_text: str) -> str:
    lines: list[str] = []
    lines.append("# Рекомендации по формату вывода\n")

    n_v = sum(1 for x in items if x.get("kind") == "video")
    n_a = sum(1 for x in items if x.get("kind") == "audio")
    total_dur = sum(x.get("duration_sec", 0) for x in items)

    lines.append(f"**Исходники:** {n_v} видео, {n_a} аудио, "
                 f"суммарно ~{total_dur:.0f}s.\n")

    if scenario_text:
        lines.append("**Сценарий (первые 500 символов):**")
        lines.append(f"> {scenario_text[:500]}\n")

    lines.append("## Предложить пользователю 2-3 варианта:\n")
    for i, key in enumerate(suggestions, 1):
        fmt = FORMATS[key]
        lines.append(f"### Вариант {i}: {fmt['name']}")
        lines.append(f"- **Формат:** {fmt['aspect']}, ~{fmt['duration_s']}s")
        lines.append(f"- **Платформы:** {fmt['platforms']}")
        lines.append(f"- **Субтитры:** {fmt['subs_style']}")
        lines.append(f"- **Когда:** {fmt['когда']}")
        lines.append("")

    lines.append("## Что спросить у пользователя:")
    lines.append("1. Какой формат основной? (выбрать из вариантов выше или указать свой)")
    lines.append("2. Нужны ли несколько форматов сразу (format-mix mode)?")
    lines.append("3. Какие overlay-анимации — минимум (только субтитры) / средне (счётчики, бейджи) / "
                 "максимум (Manim/Remotion product motion)?")
    lines.append("4. Цветокоррекция: пресет warm_cinematic / neutral_punch / none / описать словами?")
    lines.append("5. Музыкальный бэкграунд — есть свой / сгенерить через Suno MCP / без музыки?")

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Рекомендация форматов вывода на основе инвентаря")
    ap.add_argument("inventory", type=Path, help="Путь к inventory.json")
    ap.add_argument("--scenario", type=Path, default=None, help="scenario.md (опц.)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Куда сохранить (по умолчанию рядом с inventory)")
    args = ap.parse_args()

    inv_path = args.inventory.resolve()
    if not inv_path.exists():
        sys.exit(f"inventory не найден: {inv_path}")

    items = json.loads(inv_path.read_text())
    scenario_text = ""
    if args.scenario and args.scenario.exists():
        scenario_text = args.scenario.read_text(encoding="utf-8")

    suggestions = recommend(items, scenario_text)
    md = render_markdown(items, suggestions, scenario_text)

    out_path = args.out or inv_path.parent / "format_recommendations.md"
    out_path.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n(сохранено: {out_path})")


if __name__ == "__main__":
    main()
