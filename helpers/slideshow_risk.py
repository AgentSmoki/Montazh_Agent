"""Скорер риска «анимированного PowerPoint» — ловит монотонность EDL до рендера.

Идея: даже валидный EDL может смонтироваться в скучный слайд-шоу с
декоративными вставками, шаблонными подписями и без смены планов.
Этот хелпер считает 6 измерений риска (0..5, где 0 — хорошо, 5 — плохо)
и даёт вердикт ДО дорогого рендера.

Измерения:
  1. repetition           — повтор beat_type / source / похожих длин подряд
  2. decorative_visuals   — overlays/broll без смысловой связи (слабый reason/prompt)
  3. weak_motion          — слишком много статичных кадров без движения/смены плана
  4. weak_shot_intent     — кадры без beat и/или без reason (нет намерения)
  5. typography_overreliance — много подряд текстовых карточек (stat/overlay)
  6. generic_ai_phrasing  — шаблонные «AI»-фразы в reason / broll_prompt

Вердикт по среднему: <2 → strong, 2..<4 → warn, >=4 → fail.

Реализовано с нуля по описанию задачи. Чужой код не использовался.

Usage:
    from slideshow_risk import score_edl
    report = score_edl(edl_dict)   # -> {scores, average, verdict, notes}

CLI:
    python3 helpers/slideshow_risk.py <edl.json>
    exit 0 strong / 1 warn / 2 fail
"""
from __future__ import annotations

import json
from pathlib import Path

# Шаблонные «AI»-фразы. Маркер сгенерированной воды без конкретики.
# В основном русские; несколько английских — частые кальки из промптов.
GENERIC_PHRASES = [
    # русские штампы
    "современный",
    "потрясающий",
    "потрясающе",
    "завораживающий",
    "завораживает",
    "динамичный",
    "динамично",
    "атмосферный",
    "атмосфера",
    "уникальный",
    "уникальное",
    "незабываемый",
    "незабываемое",
    "в лучших традициях",
    "на новом уровне",
    "захватывающий",
    "захватывает дух",
    "поражает воображение",
    "не оставит равнодушным",
    "идеальный",
    "идеально подходит",
    "погружает в мир",
    "магия",
    "волшебный",
    "ошеломляющий",
    "впечатляющий",
    "великолепный",
    "стильный",
    "элегантный",
    "премиальный",
    # английские кальки из промптов
    "by the way",
    "stunning",
    "modern",
    "cutting-edge",
    "seamless",
    "breathtaking",
    "vibrant",
    "immersive",
    "state-of-the-art",
    "next level",
    "game-changer",
    "cinematic masterpiece",
]

# beat_type, которые по своей природе статичны (нет движения камеры/смены планов).
STATIC_BEATS = {"talk", "stat", "screen_read"}

# beat_type, считающиеся текстовыми карточками / типографикой.
TEXT_BEATS = {"stat", "screen_read"}

_VERDICT_STRONG = "strong"
_VERDICT_WARN = "warn"
_VERDICT_FAIL = "fail"


def _clamp(x: float) -> float:
    """Ограничить оценку диапазоном 0..5."""
    return max(0.0, min(5.0, x))


def _ratio_to_score(ratio: float) -> float:
    """Линейно перевести долю 0..1 в оценку 0..5."""
    return _clamp(ratio * 5.0)


def _max_run(items: list) -> int:
    """Максимальная длина серии одинаковых подряд идущих значений."""
    best = 0
    cur = 0
    prev = object()
    for it in items:
        if it == prev:
            cur += 1
        else:
            cur = 1
            prev = it
        best = max(best, cur)
    return best


def _has_generic(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(phrase in low for phrase in GENERIC_PHRASES)


def _is_weak_text(text) -> bool:
    """Пустой или слишком короткий текст = слабое намерение/связь."""
    if not text or not isinstance(text, str):
        return True
    return len(text.strip()) < 8


# --- отдельные измерения -----------------------------------------------------

def _score_repetition(ranges: list[dict]) -> tuple[float, str | None]:
    n = len(ranges)
    if n <= 1:
        return 0.0, None

    beats = [r.get("beat_type") or "" for r in ranges]
    sources = [r.get("source") or "" for r in ranges]

    # 1) длиннейшая серия одинакового beat_type подряд
    run_beat = _max_run(beats)
    beat_score = _ratio_to_score((run_beat - 1) / max(1, n - 1))

    # 2) длиннейшая серия одинакового source подряд
    run_src = _max_run(sources)
    src_score = _ratio_to_score((run_src - 1) / max(1, n - 1))

    # 3) доля кадров с почти одинаковой длительностью (монотонный ритм)
    durs = []
    for r in ranges:
        try:
            durs.append(max(0.0, float(r["end"]) - float(r["start"])))
        except (KeyError, TypeError, ValueError):
            durs.append(0.0)
    similar = 0
    for i in range(1, len(durs)):
        a, b = durs[i - 1], durs[i]
        if a <= 0 and b <= 0:
            continue
        denom = max(a, b, 0.001)
        if abs(a - b) / denom < 0.15:  # <15% разницы = «тот же» план по длине
            similar += 1
    dur_score = _ratio_to_score(similar / max(1, n - 1))

    score = _clamp(max(beat_score, src_score) * 0.6 + dur_score * 0.4)
    if score >= 2:
        return score, (
            f"Монотонность: серия одинаковых beat_type до {run_beat} подряд, "
            f"одинаковый source до {run_src} подряд, "
            f"{similar} переходов без смены длины плана"
        )
    return score, None


def _score_decorative_visuals(ranges: list[dict], overlays: list[dict]) -> tuple[float, str | None]:
    visuals: list[tuple[str, str]] = []  # (вид, текст-обоснование)
    for r in ranges:
        if (r.get("beat_type") == "broll") or r.get("broll_prompt"):
            reason = r.get("reason") or ""
            prompt = r.get("broll_prompt") or ""
            link = reason if not _is_weak_text(reason) else prompt
            visuals.append(("broll", link))
    for ov in overlays:
        link = ov.get("reason") or ov.get("text") or ov.get("note") or ""
        visuals.append(("overlay", link))

    if not visuals:
        return 0.0, None

    weak = sum(1 for _, link in visuals if _is_weak_text(link))
    score = _ratio_to_score(weak / len(visuals))
    if score >= 2:
        return score, (
            f"Декоративные вставки без смысловой связи: {weak} из {len(visuals)} "
            f"overlay/broll имеют пустой или слабый reason/broll_prompt"
        )
    return score, None


def _score_weak_motion(ranges: list[dict]) -> tuple[float, str | None]:
    n = len(ranges)
    if n == 0:
        return 0.0, None
    static = 0
    for r in ranges:
        bt = r.get("beat_type")
        eff = (r.get("effect") or "").strip().lower()
        moving = eff and eff not in ("none", "")
        if bt in STATIC_BEATS and not moving:
            static += 1
    ratio = static / n
    score = _ratio_to_score(ratio)
    if score >= 2:
        return score, (
            f"Мало движения: {static} из {n} кадров статичны "
            f"(talk/stat/screen_read без effect и смены плана)"
        )
    return score, None


def _score_weak_shot_intent(ranges: list[dict]) -> tuple[float, str | None]:
    n = len(ranges)
    if n == 0:
        return 0.0, None
    weak = 0
    for r in ranges:
        no_beat = not (r.get("beat") or r.get("beat_type"))
        no_reason = _is_weak_text(r.get("reason"))
        if no_beat or no_reason:
            weak += 1
    score = _ratio_to_score(weak / n)
    if score >= 2:
        return score, (
            f"Нет намерения кадра: {weak} из {n} range без beat и/или без reason"
        )
    return score, None


def _score_typography_overreliance(ranges: list[dict], overlays: list[dict]) -> tuple[float, str | None]:
    n = len(ranges)
    if n == 0:
        return 0.0, None

    # помечаем каждый кадр: текстовая карточка или нет (учитываем и overlay поверх)
    overlay_count = len(overlays)
    text_flags = [1 if (r.get("beat_type") in TEXT_BEATS) else 0 for r in ranges]

    text_total = sum(text_flags)
    # длиннейшая серия текстовых карточек подряд
    run = _max_run(["T" if f else f"x{i}" for i, f in enumerate(text_flags)])
    # подмешиваем долю overlay-карточек к таймлайну
    overlay_ratio = min(1.0, overlay_count / max(1, n))

    run_score = _ratio_to_score(run / max(1, n))
    total_score = _ratio_to_score(text_total / n)
    score = _clamp(max(run_score, total_score) * 0.7 + overlay_ratio * 5.0 * 0.3)
    if score >= 2:
        return score, (
            f"Перебор типографики: {text_total} текстовых кадров (серия до {run} подряд), "
            f"{overlay_count} overlay на {n} кадров"
        )
    return score, None


def _score_generic_ai_phrasing(ranges: list[dict], overlays: list[dict]) -> tuple[float, str | None]:
    texts: list[str] = []
    for r in ranges:
        texts.append(r.get("reason") or "")
        texts.append(r.get("broll_prompt") or "")
    for ov in overlays:
        texts.append(ov.get("reason") or "")
        texts.append(ov.get("text") or "")
    texts = [t for t in texts if t]
    if not texts:
        return 0.0, None
    hits = sum(1 for t in texts if _has_generic(t))
    # шаблонные фразы караем строго: даже малая доля = заметный балл
    ratio = hits / len(texts)
    score = _clamp(ratio * 8.0)  # 0.6+ доли уже даёт fail
    if score >= 2:
        found = sorted({
            phrase
            for t in texts
            for phrase in GENERIC_PHRASES
            if phrase in t.lower()
        })
        sample = ", ".join(found[:6])
        return score, (
            f"Шаблонные «AI»-фразы: {hits} из {len(texts)} текстов содержат штампы "
            f"({sample})"
        )
    return score, None


# --- публичный API -----------------------------------------------------------

def score_edl(edl: dict) -> dict:
    """Оценить EDL на риск монотонного «анимированного PowerPoint».

    Параметры:
        edl: разобранный EDL-словарь (как из validate_edl) с полями
             ranges:[...] и опционально overlays:[...].

    Возвращает dict:
        {
          "scores":  {измерение: оценка 0..5},
          "average": float,
          "verdict": "strong" | "warn" | "fail",
          "notes":   [русские пояснения по проблемным измерениям],
        }
    """
    ranges = edl.get("ranges") or []
    overlays = edl.get("overlays") or []

    dims = {
        "repetition": _score_repetition(ranges),
        "decorative_visuals": _score_decorative_visuals(ranges, overlays),
        "weak_motion": _score_weak_motion(ranges),
        "weak_shot_intent": _score_weak_shot_intent(ranges),
        "typography_overreliance": _score_typography_overreliance(ranges, overlays),
        "generic_ai_phrasing": _score_generic_ai_phrasing(ranges, overlays),
    }

    scores = {name: round(score, 2) for name, (score, _note) in dims.items()}
    notes = [note for _, (_, note) in dims.items() if note]

    average = round(sum(scores.values()) / len(scores), 2) if scores else 0.0
    if average < 2:
        verdict = _VERDICT_STRONG
    elif average < 4:
        verdict = _VERDICT_WARN
    else:
        verdict = _VERDICT_FAIL

    return {
        "scores": scores,
        "average": average,
        "verdict": verdict,
        "notes": notes,
    }


_VERDICT_EXIT = {_VERDICT_STRONG: 0, _VERDICT_WARN: 1, _VERDICT_FAIL: 2}
_VERDICT_MARK = {_VERDICT_STRONG: "✓", _VERDICT_WARN: "⚠️", _VERDICT_FAIL: "❌"}


def main() -> None:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Скорер риска «анимированного PowerPoint» / монотонности EDL"
    )
    ap.add_argument("edl", type=Path, help="Путь к edl.json")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"EDL не найден: {edl_path}")
    try:
        edl = json.loads(edl_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"EDL — битый JSON: {e}")
    if not isinstance(edl, dict) or "ranges" not in edl:
        sys.exit("EDL без поля 'ranges' — нечего оценивать")

    report = score_edl(edl)

    print("Риск монотонности EDL (0 = хорошо, 5 = плохо):")
    print(f"{'измерение':<26} оценка")
    print("-" * 36)
    for name, val in report["scores"].items():
        flag = "  ← проблема" if val >= 2 else ""
        print(f"{name:<26} {val:>4.2f}{flag}")
    print("-" * 36)
    print(f"{'СРЕДНЕЕ':<26} {report['average']:>4.2f}")

    if report["notes"]:
        print("\nПояснения:")
        for note in report["notes"]:
            print(f"  • {note}")

    verdict = report["verdict"]
    print(f"\n{_VERDICT_MARK[verdict]} вердикт: {verdict}")
    sys.exit(_VERDICT_EXIT[verdict])


if __name__ == "__main__":
    main()
