"""Транскрипция через TeleTranscribe MCP с конверсией в Scribe-формат.

Этот helper — мост между MCP-вызовом (который делает агент в чате)
и helper-скриптами (pack_transcripts.py / render.py), которые исторически
ожидают формат ElevenLabs Scribe.

ПОТОК:
1. Агент вызывает `mcp__teletranscribe__transcribe_file_json /abs/path/X.mp4 speakers=N`
2. Сохраняет сырой ответ TT в <edit>/transcripts/_raw/<stem>.json
3. Запускает этот скрипт: `python helpers/transcribe_mcp.py --raw <path>.json --out <path>.json`
4. На выходе — <edit>/transcripts/<stem>.json в Scribe-совместимом формате.

ФОРМАТ TT (после патча transcribe_file_json):
{
  "source": "abs/path",
  "duration_sec": 1834.5,
  "language": "ru",
  "speakers_count": 2,
  "utterances": [
    {"speaker": "SPEAKER_00", "start": 0.12, "end": 4.56, "text": "...",
     "words": [{"text": "...", "start": 0.12, "end": 0.55}, ...]}
  ],
  "billing": {...}
}

ФОРМАТ SCRIBE (то что ожидают pack_transcripts.py и render.py):
{
  "language_code": "ru",
  "words": [
    {"type": "word", "text": "Привет", "start": 0.12, "end": 0.55, "speaker_id": "speaker_0"},
    {"type": "spacing", "text": " ", "start": 0.55, "end": 0.78},
    ...
  ]
}

FALLBACK: если в TT-ответе нет word-timestamps (patch ещё не доехал),
скрипт упадёт с понятной ошибкой и инструкцией для агента.

Usage:
    python helpers/transcribe_mcp.py --raw raw/X.json --out X.json
    python helpers/transcribe_mcp.py --check  # печатает текущий статус (есть ли патч)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SPACING_THRESHOLD = 0.05  # доли секунды между словами — добавляем spacing-token


def utterance_to_scribe_words(utt: dict, speaker_idx: int) -> list[dict]:
    """Один utterance TeleTranscribe → плоский список Scribe-words."""
    out: list[dict] = []
    words = utt.get("words") or []
    if not words:
        return out

    speaker_id = f"speaker_{speaker_idx}"
    prev_end: float | None = None

    for w in words:
        start = w.get("start")
        end = w.get("end")
        text = (w.get("text") or "").strip()
        if start is None or end is None or not text:
            continue

        # spacing между prev_end и текущим start
        if prev_end is not None and (start - prev_end) >= SPACING_THRESHOLD:
            out.append({
                "type": "spacing",
                "text": " ",
                "start": prev_end,
                "end": start,
            })

        out.append({
            "type": "word",
            "text": text,
            "start": start,
            "end": end,
            "speaker_id": speaker_id,
        })
        prev_end = end

    return out


def speaker_label_to_index(speaker_label: str | None, mapping: dict[str, int]) -> int:
    """SPEAKER_00 → 0, SPEAKER_01 → 1, etc. Если новый — добавляем в mapping."""
    if not speaker_label:
        return 0
    if speaker_label in mapping:
        return mapping[speaker_label]
    idx = len(mapping)
    mapping[speaker_label] = idx
    return idx


def convert_tt_to_scribe(tt_data: dict) -> dict:
    """TeleTranscribe JSON → Scribe-формат JSON."""
    utterances = tt_data.get("utterances") or []
    if not utterances:
        raise ValueError(
            "TT-ответ без utterances[]. Возможно, патч transcribe_file_json ещё не задеплоен. "
            "Проверь: вызывал ли агент именно transcribe_file_json (а не transcribe_file)?"
        )

    has_words = any(u.get("words") for u in utterances)
    if not has_words:
        raise ValueError(
            "Utterances есть, но words[] пустые. GigaAM не вернул word-timestamps. "
            "Проверь патч TeleTranscribe MCP — Task.result должен содержать "
            "segments[].words[] с {text, start, end}."
        )

    speaker_mapping: dict[str, int] = {}
    words: list[dict] = []

    for utt in utterances:
        idx = speaker_label_to_index(utt.get("speaker"), speaker_mapping)
        words.extend(utterance_to_scribe_words(utt, idx))

    return {
        "language_code": tt_data.get("language", "ru"),
        "words": words,
        # Сохраняем метаданные TT — полезно для audit / billing
        "_tt_meta": {
            "source": tt_data.get("source"),
            "duration_sec": tt_data.get("duration_sec"),
            "speakers_count": tt_data.get("speakers_count"),
            "billing": tt_data.get("billing"),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="TT MCP raw JSON → Scribe-format JSON")
    ap.add_argument("--raw", type=Path, help="Path to raw TT response JSON")
    ap.add_argument("--out", type=Path, help="Output path for Scribe-format JSON")
    ap.add_argument("--check", action="store_true",
                    help="Печатает инструкцию для агента — как вызвать MCP")
    args = ap.parse_args()

    if args.check:
        print(
            "Чтобы транскрибировать через TeleTranscribe MCP:\n\n"
            "1. Из чата вызови MCP-tool:\n"
            "     mcp__teletranscribe__transcribe_file_json <abs/path/video.mp4> speakers=<N>\n"
            "   (после патча MCP — должен возвращать dict с utterances[].words[])\n\n"
            "2. Сохрани raw-ответ в <edit>/transcripts/_raw/<stem>.json\n\n"
            "3. Запусти конверсию:\n"
            "     python helpers/transcribe_mcp.py --raw <raw>.json --out <edit>/transcripts/<stem>.json\n\n"
            "Если используешь старый MCP без _json — обрати внимание: pack_transcripts.py "
            "не умеет работать с plain-text. Нужен патч TeleTranscribe MCP.\n\n"
            "Полная спека патча — в PATCH_TELETRANSCRIBE_PROMPT.md."
        )
        return

    if not args.raw or not args.out:
        sys.exit("--raw и --out обязательны (или используй --check)")

    raw_path = args.raw.resolve()
    if not raw_path.exists():
        sys.exit(f"raw файл не найден: {raw_path}")

    raw_data = json.loads(raw_path.read_text())
    converted = convert_tt_to_scribe(raw_data)

    out_path = args.out.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(converted, ensure_ascii=False, indent=2))

    word_count = sum(1 for w in converted["words"] if w.get("type") == "word")
    print(f"✓ {out_path.name}  ({word_count} word-tokens, "
          f"{len(converted['words'])} total tokens including spacing)")


if __name__ == "__main__":
    main()
