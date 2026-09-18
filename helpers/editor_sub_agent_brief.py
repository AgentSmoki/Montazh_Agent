"""Готовит structured prompt для запуска editor sub-agent через Agent tool.

Зачем: главный агент часто выбирает beats наугад и режет смысл. Sub-agent с
полным контекстом (packed.md + raw transcripts с words[]) + явными Hard Rules
в промпте даёт лучший выбор по семантическим мостам.

Sub-agent НЕ режет сам — он возвращает EDL с reasoning per cut. Главный агент
просматривает, при необходимости корректирует, и подает в render.py.

Pattern из browser-use/video-use SKILL.md «Editor sub-agent brief» — но
здесь Hard Rules цитируются ПРЯМО в промпт (раньше они были только в SKILL.md
который sub-agent мог не прочитать).

Usage:
    python helpers/editor_sub_agent_brief.py \\
        --packed <edit>/takes_packed.md \\
        --transcripts-dir <edit>/transcripts \\
        --scenario <project>/scenario.md \\
        --target-duration 35 \\
        -o <edit>/_editor_brief.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BRIEF_TEMPLATE = """# Editor Sub-Agent Brief

Ты — редактор talking-head видео. Твоя задача — выбрать лучшие beats из
доступных дублей и собрать EDL чтобы финальный ролик длительностью ~{target}с
имел **связную, логичную драматургию** и не звучал как лоскутное одеяло
обрывков.

## Hard Rules (НЕ нарушать)

1. **Никогда не резать внутри слова.** `range.start` ставь на `word.start`, а
   `range.end` — на `word.end` слова из transcripts/: это ориентир. Главный агент
   потом переносит каждую границу в ближайшую тишину по звуку (Hard Rule 6 в
   SKILL.md) — таймкоды ASR уезжают на 0,2–0,5 с.

2. **🚫 НЕ резать внутри синтагмы** (источник: Gemini Deep Research, май 2026).
   Синтагма у носителя русского — неделимая интонационная единица. Запрещено:
   - ❌ Между прилагательным и существительным: «в большой [CUT] машине»
   - ❌ Между предлогом и существительным: «в [CUT] кабинете»
   - ❌ Между подлежащим и сказуемым: «он [CUT] начинает»
   - ❌ Между числительным и существительным: «46 [CUT] единиц»
   - ❌ Между частицей и глаголом: «не [CUT] делай»

   Разрешено резать:
   - ✅ На границе clauses (простых предложений в составе сложного)
   - ✅ После сказуемого с законченной интонацией
   - ✅ Между вводным оборотом и основной частью
   - ✅ После маркеров завершённости: «Вот.», «Бац — готово.», «И всё.»

3. **Семантические мосты вместо фразовых пауз.** Если фраза обрывает мысль на
   полуслове — расширь range до следующей естественной завершённости. НЕ:
   - ❌ «Я напишу: давай делай.» (что дальше? мысль обрублена)
   - ✅ «Я напишу: давай делай. И он у нас начинает строить воронку.»

4. **Cross-clip контекст.** Когда выбираешь beats из разных файлов — убедись
   что слушатель понимает логику перехода. «А» → «Б» должно быть очевидным.

5. **Точную границу ставит главный агент.** Timestamps оставляй ровно по словам:
   рез в тишину по огибающей (или, если тишин нет, smart padding
   `apply_padding.py --smart`) добавляется после тебя.

6. **Длительность.** Целевая ~{target}с. Допуск ±20%. Если выходит больше —
   сократи менее ценные beats. Если меньше — добавь контекста.

7. **Для каждой склейки A→B — bridge_rationale.** В каждом range кроме первого
   добавь поле `"bridge_rationale": "почему cut здесь не разрушает смысл"`.
   Если переход резкий — пометь `"requires_b_roll": true` (это сигнал что
   нужна B-roll вставка для маскировки рваного стыка).

## Структура output

Верни **только** JSON-объект (без markdown-блоков), валидный для Montazh_Agent EDL:

```json
{{
  "version": 1,
  "name": "subagent_v1",
  "total_duration_s": 35.0,
  "sources": {{ "<source_name>": "<абсолютный путь>" }},
  "ranges": [
    {{"source": "...", "start": 0.12, "end": 5.40, "beat": "HOOK",
     "quote": "...", "reason": "почему этот beat — конкретно для драматургии"}},
     ...
  ],
  "grade": "neutral_punch",
  "overlays": [],
  "_subagent_meta": {{
    "potential_issues": [
      "beat #3 переход к #4 может звучать резко — рассмотри L-cut"
    ]
  }}
}}
```

## Доступные источники (packed transcripts)

{packed_content}

## Сценарий клиента (если есть)

{scenario_content}

## Подсказки

- HOOK (0-3с) — самое виральное. Выбирай beat с яркой первой фразой.
- DEMO/BODY — связные блоки по 2-5с, **не обрывки**.
- CTA в конце — полная фраза с призывом.
- Если есть «stat»-моменты (цифры, циферные proof-points) — выделяй их.
- Естественные мосты: «И вот...», «Дальше...», «А теперь...», «Бац — готово».
  Эти фразы — хорошие точки для cut'а.

Поехали. Верни только JSON.
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Подготовить brief для editor sub-agent (через Agent tool)"
    )
    ap.add_argument("--packed", type=Path, required=True,
                    help="Path to takes_packed.md")
    ap.add_argument("--transcripts-dir", type=Path, required=True,
                    help="Папка с *.json transcripts (для info, в brief упоминается)")
    ap.add_argument("--scenario", type=Path, default=None,
                    help="scenario.md клиента (опц)")
    ap.add_argument("--target-duration", type=int, default=35,
                    help="Целевая длительность ролика (сек, default 35)")
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="Куда сохранить brief.md")
    args = ap.parse_args()

    if not args.packed.exists():
        sys.exit(f"packed.md не найден: {args.packed}")

    packed_content = args.packed.read_text(encoding="utf-8")
    scenario_content = ""
    if args.scenario and args.scenario.exists():
        scenario_content = args.scenario.read_text(encoding="utf-8")
    else:
        scenario_content = "(сценария нет, ориентируйся на содержание dialog'а)"

    brief = BRIEF_TEMPLATE.format(
        target=args.target_duration,
        packed_content=packed_content,
        scenario_content=scenario_content,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(brief, encoding="utf-8")

    kb = args.output.stat().st_size / 1024
    print(f"✓ {args.output} ({kb:.1f} KB)")
    print()
    print("Дальше — в чате запусти Agent tool:")
    print("  Agent(")
    print("    description='Editor sub-agent: выбор beats',")
    print(f"    prompt=open('{args.output}').read(),")
    print("    subagent_type='general-purpose'")
    print("  )")
    print("Sub-agent вернёт EDL — сохрани в edit/edl.json, далее границы в тишины по звуку (Hard Rule 6) и render --no-snap --no-pad.")


if __name__ == "__main__":
    main()
