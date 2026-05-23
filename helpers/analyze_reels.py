"""Анализ Reels/Shorts конкурентов перед запуском контент-завода.

Извлечено из созвона: «прежде чем запускать продакшен, надо понять что
работает в нише — пройтись по YouTube/TikTok каналам конкурентов, отобрать
топ-хайповые ролики, проанализировать что сработало».

Этот скрипт — обёртка над несколькими шагами:
1. yt-dlp скачивает топ-N роликов с указанного канала
2. TeleTranscribe MCP транскрибирует каждый
3. LLM-агент анализирует:
   - типичная длительность
   - средний engagement (просмотры / подписчики)
   - сценарные паттерны (HOOK → ... → CTA)
   - визуальные приёмы (по timeline_view)
   - присутствует ли CTA (если да — какой)
4. Выдаёт markdown-отчёт с топ-3 паттернами для копирования

Это STUB — реальная имплементация требует:
- YouTube Data API key (или yt-dlp + scrape)
- определения «топ» (просмотры? engagement? recency?)
- LLM-промпта для паттерн-экстракции

Использование (когда будет готов):
    python helpers/analyze_reels.py --channel @aiblogerexample --top 20 \\
        --out edit/competitor_analysis.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


STUB_TEMPLATE = """# Анализ конкурентов: {channel}

⚠️ STUB — этот функционал в roadmap. Пока что выдаёт шаблон для ручного заполнения.

## Что нужно сделать руками сейчас

1. Открой канал {channel} в TikTok/YouTube/Instagram.
2. Найди топ-{top} роликов по просмотрам/лайкам за последние 30-90 дней.
3. Для каждого:
   - URL: ___
   - Просмотры: ___
   - Длительность: ___
   - Формат (из helpers/content_factory_presets.py):
     [ ] pure_neural
     [ ] neuro_blogger
     [ ] story_hype_iconic
     [ ] expert_with_infographics
     [ ] pure_talking_head
     [ ] live_plus_neural_mix
     [ ] photo_animation_skit
   - HOOK (первые 3 сек): ___
   - CTA в конце (есть/нет, какой): ___
   - Что сработало (1 предложение): ___

4. После заполнения дай этот файл агенту: «выбери топ-3 паттерна,
   которые мне нужно скопировать в свой контент-план на след. неделю».

## Какие helper'ы будут задействованы (когда реализуем)

- `yt-dlp` для скачивания исходников (опционально для глубокого анализа)
- `mcp__teletranscribe__transcribe_url_json` для транскрипции
- `pack_transcripts.py` для приведения в packed.md
- LLM (Sonnet 4.6) для паттерн-экстракции
- `content_factory_presets.py` для классификации форматов

## TODO для имплементации

- [ ] Парсер каналов TikTok/YouTube/Instagram → список URL топ-N
- [ ] Скачивание метаданных (views, duration, posted_at)
- [ ] Опционально — скачивание самих видео через yt-dlp
- [ ] Транскрипция через TT MCP (batch)
- [ ] LLM-промпт для классификации формата + извлечения HOOK/CTA
- [ ] Markdown-генератор отчёта
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Анализ Reels конкурентов (stub — пока ручной шаблон)"
    )
    ap.add_argument("--channel", required=True,
                    help="TikTok/YouTube/Instagram канал (@handle или URL)")
    ap.add_argument("--top", type=int, default=20,
                    help="Сколько топ-роликов проанализировать")
    ap.add_argument("--out", type=Path, default=None,
                    help="Куда сохранить отчёт (default: edit/competitor_analysis_<channel>.md)")
    args = ap.parse_args()

    safe_channel = args.channel.replace("@", "").replace("/", "_")
    out_path = args.out or Path(f"edit/competitor_analysis_{safe_channel}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    content = STUB_TEMPLATE.format(channel=args.channel, top=args.top)
    out_path.write_text(content, encoding="utf-8")

    print(f"✓ Шаблон создан: {out_path}")
    print(f"  Откройте {args.channel}, заполните руками, затем верните агенту.")
    print(f"  Полная автоматизация — в roadmap (см. TODO в файле).")


if __name__ == "__main__":
    main()
