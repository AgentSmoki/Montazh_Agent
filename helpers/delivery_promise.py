"""Гейт «обещание доставки» — что обещали режимом, то и отдали.

Назначение: поймать молчаливый провал в статику. Если режим обещает зрителю
движущуюся картинку (generative-only, audio-first — «оживший» ролик), а EDL
по факту собран из говорящих голов и статичных слайдов, это нарушение обещания.
Лучше предупредить человека и потребовать явного подтверждения, чем выдать
«видео», которое на деле презентация.

Каждый range EDL классифицируется в одну из трёх категорий движения:
  - MOTION — генеративное видео или реальное движение (B-roll, мем-вставка).
  - SLIDE — анимированный слайд / карточка / скринкаст. ВАЖНО: слайд НЕ
            считается движением, даже с эффектом push-in. Эффект — это панорама
            по статике, а не реальное движение в кадре.
  - STILL  — статичный источник / говорящая голова без эффекта.

Идея гейта вдохновлена AGPL-проектом OpenMontage (lib/delivery_promise.py);
здесь реализована с нуля по описанию, чужой код не используется.

Usage (CLI):
    python3 helpers/delivery_promise.py edit/edl.json --mode generative-only
    python3 helpers/delivery_promise.py edit/edl.json --promise-type motion_led

Usage (импорт в render.py):
    from delivery_promise import validate_cuts, promise_type_for_mode
    verdict = validate_cuts(edl["ranges"], promise_type_for_mode(mode))
    if verdict["requires_override"]:
        # предупредить пользователя, потребовать явного «да, рендерим»
        ...
"""
from __future__ import annotations

import json
from pathlib import Path

# --- Типы обещаний и их правила -------------------------------------------
#
# still_fallback_allowed — можно ли молча скатиться в статику без нарушения.
# min_motion_ratio       — минимальная доля MOTION-ranges (по числу битов),
#                          ниже которой обещание считается невыполненным.
#
# motion_led: режим обещает «живой» ролик. Зритель ждёт движущуюся картинку,
#             а не презентацию. Падение в статику — это нарушение обещания.
# source_led / talk_led: режим работает с исходным видео (нарезка / монтаж
#             говорящей головы). Статика тут нормальна и ожидаема.
PROMISE_RULES: dict[str, dict] = {
    "motion_led": {
        "still_fallback_allowed": False,
        "min_motion_ratio": 0.5,
        "human": "оживший ролик (зритель ждёт движущуюся картинку)",
    },
    "source_led": {
        "still_fallback_allowed": True,
        "min_motion_ratio": 0.2,
        "human": "монтаж из исходного видео (статика допустима)",
    },
    "talk_led": {
        "still_fallback_allowed": True,
        "min_motion_ratio": 0.0,
        "human": "говорящая голова / нарезка (статика — норма)",
    },
}

# --- Маппинг режим агента → тип обещания -----------------------------------
#
# generative-only — всё с нуля, B-roll генерируется. Обещание — движущийся ролик.
# audio-first     — голос ведёт, под фразы подбирается/генерится видео-ряд.
#                   Зритель ждёт картинку, а не чёрный экран с голосом → motion.
# highlight       — нарезка одного длинного source. Источник-ведомый.
# multi-clip      — монтаж нескольких клипов. Источник-ведомый.
# format-mix      — один source в N форматов. Источник-ведомый.
# content-factory — пресеты контент-завода поверх исходников. Источник-ведомый.
MODE_TO_PROMISE: dict[str, str] = {
    "generative-only": "motion_led",
    "audio-first": "motion_led",
    "highlight": "source_led",
    "multi-clip": "source_led",
    "format-mix": "source_led",
    "content-factory": "source_led",
    # говорящая голова без B-roll, если когда-то понадобится отдельным режимом
    "talking-head": "talk_led",
}

# beat_type, которые мы трактуем как слайд/карточку/скринкаст
_SLIDE_BEATS = {"stat", "screen_read"}
# beat_type, которые мы трактуем как реальное движение/генеративное видео
_MOTION_BEATS = {"broll", "meme"}


def promise_type_for_mode(mode: str) -> str:
    """Режим агента → тип обещания. Падает понятным сообщением для чужого режима."""
    import sys

    key = (mode or "").strip().lower()
    if key not in MODE_TO_PROMISE:
        known = ", ".join(sorted(MODE_TO_PROMISE))
        sys.exit(f"Неизвестный режим '{mode}'. Доступны: {known} "
                 f"(или задайте тип обещания явно через --promise-type).")
    return MODE_TO_PROMISE[key]


def classify_range(r: dict) -> str:
    """Один range → 'motion' | 'slide' | 'still'.

    Приоритет: реальное движение → слайд → статика.
    Слайд с effect=pushin остаётся слайдом (панорама по статике ≠ движение).
    """
    beat_type = (r.get("beat_type") or "").strip().lower()

    # реальное движение / генеративное видео
    if beat_type in _MOTION_BEATS or bool(r.get("need_broll")):
        return "motion"

    # анимированный слайд / карточка / скринкаст — push-in движением не считаем
    if beat_type in _SLIDE_BEATS:
        return "slide"

    # говорящая голова / статичный источник
    return "still"


def validate_cuts(ranges: list[dict], promise_type: str) -> dict:
    """Проверить, выполнено ли обещание доставки для набора ranges.

    Args:
        ranges:       список range-объектов из edl.json.
        promise_type: ключ PROMISE_RULES (motion_led / source_led / talk_led).

    Returns:
        dict с полями:
          ok                 — bool, обещание выполнено;
          promise_type       — переданный тип обещания;
          motion_ratio       — доля motion-битов от общего числа (0.0..1.0);
          counts             — {'motion', 'slide', 'still'};
          violations         — список строк-объяснений по-русски;
          requires_override  — bool, нужно явное подтверждение человека.
    """
    import sys

    rule = PROMISE_RULES.get(promise_type)
    if rule is None:
        known = ", ".join(sorted(PROMISE_RULES))
        sys.exit(f"Неизвестный тип обещания '{promise_type}'. Доступны: {known}.")

    counts = {"motion": 0, "slide": 0, "still": 0}
    for r in ranges or []:
        counts[classify_range(r)] += 1

    total = sum(counts.values())
    motion_ratio = (counts["motion"] / total) if total else 0.0

    violations: list[str] = []
    requires_override = False

    if total == 0:
        violations.append("В EDL нет ни одного range — нечего доставлять.")
        requires_override = True
    elif motion_ratio < rule["min_motion_ratio"] and not rule["still_fallback_allowed"]:
        # обещали движущийся ролик, а собрали статику/слайды
        pct = round(motion_ratio * 100)
        need = round(rule["min_motion_ratio"] * 100)
        violations.append(
            f"Режим обещает {rule['human']}, но в ролике лишь {pct}% движущихся "
            f"битов (нужно минимум {need}%). По факту: говорящих голов "
            f"{counts['still']}, слайдов {counts['slide']}, движения "
            f"{counts['motion']} из {total}. Это молчаливый провал в статику — "
            f"зритель ждёт живую картинку, а получит презентацию."
        )
        requires_override = True

    ok = not violations
    return {
        "ok": ok,
        "promise_type": promise_type,
        "motion_ratio": round(motion_ratio, 3),
        "counts": counts,
        "violations": violations,
        "requires_override": requires_override,
    }


def main() -> None:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Гейт обещания доставки: режим обещал движение — EDL должен его отдать."
    )
    ap.add_argument("edl", type=Path, help="путь к edl.json")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--mode", help="режим агента (highlight, multi-clip, audio-first, "
                                  "format-mix, generative-only, content-factory)")
    g.add_argument("--promise-type", dest="promise_type",
                   help="тип обещания напрямую (motion_led / source_led / talk_led)")
    args = ap.parse_args()

    try:
        edl = json.loads(args.edl.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"Файл EDL не найден: {args.edl}")
    except json.JSONDecodeError as e:
        sys.exit(f"EDL не парсится как JSON: {e}")

    ranges = edl.get("ranges")
    if not isinstance(ranges, list):
        sys.exit("В EDL нет списка 'ranges' — нечего проверять.")

    if args.promise_type:
        ptype = args.promise_type.strip().lower()
        if ptype not in PROMISE_RULES:
            known = ", ".join(sorted(PROMISE_RULES))
            sys.exit(f"Неизвестный тип обещания '{args.promise_type}'. Доступны: {known}.")
    elif args.mode:
        ptype = promise_type_for_mode(args.mode)
    else:
        sys.exit("Укажите режим (--mode) или тип обещания (--promise-type).")

    v = validate_cuts(ranges, ptype)
    rule = PROMISE_RULES[ptype]

    print(f"Тип обещания: {ptype} — {rule['human']}")
    print(f"Биты: движение {v['counts']['motion']}, "
          f"слайды {v['counts']['slide']}, статика {v['counts']['still']} "
          f"(доля движения {v['motion_ratio']*100:.0f}%, "
          f"порог {rule['min_motion_ratio']*100:.0f}%)")

    if v["ok"]:
        print("✓ Обещание доставки выполнено — режим отдал то, что обещал.")
        sys.exit(0)

    for msg in v["violations"]:
        print(f"❌ {msg}")
    if v["requires_override"]:
        print("→ Требуется явное подтверждение человека перед рендером "
              "(или смена режима / добавление B-roll).")
    sys.exit(2)


if __name__ == "__main__":
    main()
