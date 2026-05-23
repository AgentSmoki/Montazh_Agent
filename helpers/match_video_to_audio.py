"""Audio-first match: для каждой фразы в аудио подбираем подходящий shot из видео.

ТРИ BACKEND'A (выбираются автоматически):

1. **tt-describe** (default, lean) — описание кадров через TeleTranscribe MCP
   `describe_image` tool (multimodal LLM каскад: NVIDIA NIM → Yandex → OpenRouter).
   Кадры → text-описания → семантический матч с фразами делает агент в чате
   (Claude как LLM-as-judge) либо лёгкий text-embedding API. Никаких локальных
   ML-зависимостей, ~300 МБ RAM вместо 2.5 ГБ (CLIP-PyTorch).
   **Требует:** MCP `teletranscribe.describe_image` (см. PATCH-промпт в репо TT)
   ИЛИ HTTP endpoint (пока его нет — нужен патч).

2. **clip-onnx** (optional, on-device без PyTorch) — CLIP-ViT-B-32 через
   onnxruntime. +15 МБ зависимостей, в 1.5× быстрее PyTorch на Intel CPU.
   Требует ручной конвертации модели — см. `helpers/clip_onnx.py`.
   Ставится: `uv sync --extra clip-onnx`.

3. **clip-pytorch** (legacy fallback) — sentence-transformers + torch.
   +2.5 ГБ зависимостей, на Intel CPU самый медленный путь (40-50с на 50 кадров).
   Ставится: `uv sync --extra clip-pytorch`.

АЛГОРИТМ (для всех backend'ов):
  1. Берём scribe-формат транскрипта аудио (из transcripts/voice.json).
  2. Группируем word-токены в фразы (pack_transcripts.group_into_phrases).
  3. Для каждого видео-исходника:
     a. PySceneDetect → список shots (helpers/scene_detect.py)
     b. Из каждого shot достаём middle-frame через ffmpeg → JPEG
  4. Семантический матч phrase ↔ shot:
     - tt-describe: каждый shot → текст-описание (MCP) → агент решает матч
     - clip-*: text+image embeddings → cosine similarity
  5. Выдаём EDL: [{audio_in, audio_out, video_source, video_in, video_out,
                   score, reason}]

Тяжёлые операции — кеш в edit/clip_cache/ или edit/descriptions/.

Usage:
    # Default (tt-describe — нужен MCP describe_image patch):
    python helpers/match_video_to_audio.py \\
        --audio-transcript edit/transcripts/voice.json \\
        --videos edit/inventory.json \\
        --out edit/audio_first_edl.json

    # Legacy CLIP (если установлен clip-pytorch extra):
    python helpers/match_video_to_audio.py ... --backend clip-pytorch
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Общие утилиты (для всех backend'ов)
# ─────────────────────────────────────────────────────────────────────────────

def load_phrases(transcript_path: Path) -> list[dict]:
    """Группируем word-токены в фразы (повторяем логику pack_transcripts.py)."""
    sys.path.insert(0, str(Path(__file__).parent))
    from pack_transcripts import group_into_phrases  # type: ignore
    data = json.loads(transcript_path.read_text())
    words = data.get("words") or []
    return group_into_phrases(words, silence_threshold=0.5)


def extract_middle_frame(video: Path, mid_time: float, out_jpg: Path,
                         scale: int = 336) -> None:
    """Сохраняет кадр в JPEG нужного размера (для CLIP / TT vision)."""
    cmd = [
        "ffmpeg", "-y", "-ss", f"{mid_time:.3f}",
        "-i", str(video), "-frames:v", "1",
        "-vf", f"scale={scale}:-2", "-q:v", "3",
        str(out_jpg),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def collect_shots(inventory: list[dict], cache_dir: Path) -> list[dict]:
    """Собираем shots из всех видео + извлекаем middle-frame в кеш.

    Returns: [{source_path, source_name, shot_in, shot_out, frame_path, shot_id}, ...]
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_shots: list[dict] = []

    for video_meta in inventory:
        if video_meta.get("kind") != "video":
            continue
        source_path = Path(video_meta["path"])
        if not source_path.exists():
            continue

        try:
            from scenedetect import detect, ContentDetector
            scenes = detect(str(source_path), ContentDetector(threshold=27.0))
        except ImportError:
            scenes = []

        if not scenes:
            # Один большой shot — режем по 5s
            dur = video_meta.get("duration_sec", 30.0)
            scenes_emul = [(float(i), min(float(i + 5), dur)) for i in range(0, int(dur), 5)]
            for shot_in, shot_out in scenes_emul:
                _add_shot(source_path, shot_in, shot_out, cache_dir, all_shots)
        else:
            for start, end in scenes:
                shot_in = start.get_seconds()
                shot_out = end.get_seconds()
                _add_shot(source_path, shot_in, shot_out, cache_dir, all_shots)

    return all_shots


def _add_shot(source_path: Path, shot_in: float, shot_out: float,
              cache_dir: Path, all_shots: list[dict]) -> None:
    mid = (shot_in + shot_out) / 2
    shot_id = f"{source_path.stem}_{shot_in:.2f}_{shot_out:.2f}"
    frame_path = cache_dir / f"{shot_id}.jpg"
    if not frame_path.exists():
        extract_middle_frame(source_path, mid, frame_path)
    all_shots.append({
        "shot_id": shot_id,
        "source_path": str(source_path),
        "source_name": source_path.stem,
        "shot_in": shot_in,
        "shot_out": shot_out,
        "frame_path": str(frame_path),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Backend 1: TT describe-image + LLM-judge
# ─────────────────────────────────────────────────────────────────────────────

TT_DESCRIBE_INSTRUCTION = """
Чтобы использовать tt-describe backend для аудио-first матчинга:

1. Для каждого shot в `_pending_shots.json` агент должен вызвать MCP-tool:
     mcp__teletranscribe__describe_image \\
       file_path=<frame_path> \\
       prompt="Опиши кратко содержимое кадра (объекты, действия, локация).
               Не более 30 слов, на русском."

   ⚠️ Если этого tool пока нет — нужен патч TT MCP.
   Спецификация патча — в `PATCH_TT_DESCRIBE_IMAGE_PROMPT.md`.

2. Сохрани результат в `descriptions/<shot_id>.txt` (одна строка — описание).

3. Запусти этот же скрипт повторно — он соберёт описания из кеша
   и сделает LLM-as-judge матч phrase ↔ description (вызовы Claude в чате).

4. На выходе — `audio_first_edl.json` с лучшим shot на каждую фразу.

Можно автоматизировать через цикл вызовов в начале сессии агента.
"""


def tt_describe_backend_prepare(
    phrases: list[dict],
    shots: list[dict],
    descriptions_dir: Path,
    out_pending: Path,
) -> None:
    """Этап 1: подготовить список shots, которые нужно описать через TT MCP.

    Записывает _pending_shots.json — список shots без описания в кеше.
    Агент потом вызывает MCP для каждого и сохраняет в descriptions/<id>.txt.
    """
    descriptions_dir.mkdir(parents=True, exist_ok=True)

    pending = []
    for shot in shots:
        desc_path = descriptions_dir / f"{shot['shot_id']}.txt"
        if not desc_path.exists():
            pending.append({
                "shot_id": shot["shot_id"],
                "frame_path": shot["frame_path"],
                "save_description_to": str(desc_path),
            })

    out_pending.write_text(json.dumps(pending, ensure_ascii=False, indent=2))

    print(f"Backend: tt-describe")
    print(f"Shots всего: {len(shots)}, без описания: {len(pending)}")
    if pending:
        print(f"\n→ {out_pending}")
        print("\nДальнейшие шаги:")
        print(TT_DESCRIBE_INSTRUCTION)
    else:
        print("\n✓ Все shots имеют описания. Запусти --judge-only для финального матчинга.")


def tt_describe_backend_judge(
    phrases: list[dict],
    shots: list[dict],
    descriptions_dir: Path,
    out_path: Path,
) -> None:
    """Этап 2: матчинг phrase ↔ description через LLM-judge (Claude в чате).

    Этот скрипт сам матчинг не делает — он только собирает данные и записывает
    `_judge_input.json` для агента. Агент в чате читает входной JSON,
    делает rank'инг по семантике и записывает финальный EDL.
    """
    descriptions: dict[str, str] = {}
    for shot in shots:
        desc_path = descriptions_dir / f"{shot['shot_id']}.txt"
        if desc_path.exists():
            descriptions[shot["shot_id"]] = desc_path.read_text(encoding="utf-8").strip()

    if not descriptions:
        sys.exit("Нет ни одного описания в кеше. Сначала запусти TT describe для shots.")

    judge_input = {
        "task": "Для каждой phrase подбери лучший shot по семантике описания. "
                "Минимизируй повторы (penalty 0.05 за каждое предыдущее использование). "
                "Выдай list [{audio_in, audio_out, video_source, video_in, video_out, "
                "score (0-1), reason}].",
        "phrases": [
            {"idx": i, "text": p["text"], "start": p["start"], "end": p["end"]}
            for i, p in enumerate(phrases)
        ],
        "shots": [
            {
                "shot_id": s["shot_id"],
                "source_name": s["source_name"],
                "shot_in": s["shot_in"],
                "shot_out": s["shot_out"],
                "description": descriptions.get(s["shot_id"], "(нет описания)"),
            }
            for s in shots
        ],
        "output_path": str(out_path),
    }

    judge_path = out_path.parent / "_judge_input.json"
    judge_path.write_text(json.dumps(judge_input, ensure_ascii=False, indent=2))

    print(f"Backend: tt-describe → LLM-judge")
    print(f"Phrases: {len(phrases)}, Shots с описаниями: {len(descriptions)}/{len(shots)}")
    print(f"\n→ Input для LLM-judge: {judge_path}")
    print(f"→ Ожидаемый output: {out_path}")
    print("\nДальнейшие шаги:")
    print("  Агент в чате читает _judge_input.json, делает rank'инг,")
    print(f"  записывает EDL в {out_path.name}.")


# ─────────────────────────────────────────────────────────────────────────────
# Backend 2: CLIP через PyTorch (legacy fallback)
# ─────────────────────────────────────────────────────────────────────────────

def clip_pytorch_backend(
    phrases: list[dict],
    shots: list[dict],
    cache_dir: Path,
    out_path: Path,
) -> None:
    """sentence-transformers + torch + CLIP-ViT-B-32. Тяжёлый, медленный путь."""
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        from PIL import Image
    except ImportError:
        sys.exit("clip-pytorch не установлен. `uv sync --extra clip-pytorch`")

    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Backend: clip-pytorch (Intel CPU — медленно, ~40-50с на 50 shots)")
    model = SentenceTransformer("sentence-transformers/clip-ViT-B-32")

    # Эмбеддинги картинок (с кешем)
    shot_embs = []
    for shot in shots:
        cache_file = cache_dir / f"{shot['shot_id']}.json"
        if cache_file.exists():
            emb = json.loads(cache_file.read_text())["emb"]
        else:
            img = Image.open(shot["frame_path"]).convert("RGB")
            emb = model.encode(img, convert_to_numpy=True, normalize_embeddings=True).tolist()
            cache_file.write_text(json.dumps({"emb": emb}))
        shot_embs.append(emb)

    shot_embs = np.array(shot_embs)  # (N, 512)

    edl_spans: list[dict] = []
    used_count = [0] * len(shots)
    for phrase in phrases:
        text_emb = model.encode(phrase["text"], convert_to_numpy=True, normalize_embeddings=True)
        sims = shot_embs @ text_emb
        adjusted = sims - 0.05 * np.array(used_count)
        best_idx = int(np.argmax(adjusted))
        used_count[best_idx] += 1

        shot = shots[best_idx]
        phrase_dur = phrase["end"] - phrase["start"]
        shot_dur = shot["shot_out"] - shot["shot_in"]
        if shot_dur > phrase_dur:
            mid = (shot["shot_in"] + shot["shot_out"]) / 2
            video_in = max(shot["shot_in"], mid - phrase_dur / 2)
            video_out = video_in + phrase_dur
        else:
            video_in = shot["shot_in"]
            video_out = shot["shot_out"]

        edl_spans.append({
            "audio_in": round(phrase["start"], 3),
            "audio_out": round(phrase["end"], 3),
            "video_source": shot["source_name"],
            "video_in": round(video_in, 3),
            "video_out": round(video_out, 3),
            "score": round(float(sims[best_idx]), 3),
            "phrase_text": phrase["text"][:80],
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(edl_spans, ensure_ascii=False, indent=2))
    print(f"✓ EDL-spans → {out_path} ({len(edl_spans)} спанов)")


# ─────────────────────────────────────────────────────────────────────────────
# Backend 3: CLIP через ONNX (lean optional)
# ─────────────────────────────────────────────────────────────────────────────

def clip_onnx_backend(
    phrases: list[dict],
    shots: list[dict],
    cache_dir: Path,
    out_path: Path,
) -> None:
    """ONNX Runtime CLIP — без PyTorch, в 1.5× быстрее на CPU."""
    try:
        from clip_onnx import CLIPOnnx  # type: ignore
    except ImportError:
        sys.exit(
            "clip-onnx не настроен. Нужно:\n"
            "  1. `uv sync --extra clip-onnx`\n"
            "  2. Конвертировать CLIP-ViT-B-32 в .onnx (см. helpers/clip_onnx.py --setup)\n"
            "  3. Положить в edit/models/clip-vit-b32.onnx"
        )

    # Реализация аналогична clip_pytorch но через CLIPOnnx.encode_image/text
    sys.exit("clip-onnx backend WIP — используй tt-describe или clip-pytorch")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audio-first: подбор видео-кадров под фразы аудио"
    )
    ap.add_argument("--audio-transcript", type=Path, required=True,
                    help="Scribe-format JSON транскрипт аудио (с word-timestamps)")
    ap.add_argument("--videos", type=Path, required=True,
                    help="inventory.json со списком видео-исходников")
    ap.add_argument("--out", type=Path, required=True,
                    help="Куда сохранить EDL-spans JSON")
    ap.add_argument("--backend",
                    choices=["tt-describe", "clip-pytorch", "clip-onnx"],
                    default="tt-describe",
                    help="Backend для матчинга (default: tt-describe — lean)")
    ap.add_argument("--judge-only", action="store_true",
                    help="(tt-describe) подготовить _judge_input.json без новых MCP-вызовов")
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="Папка для кеша (default: <out.parent>/match_cache/)")
    args = ap.parse_args()

    transcript_path = args.audio_transcript.resolve()
    inv_path = args.videos.resolve()
    out_path = args.out.resolve()

    if not transcript_path.exists():
        sys.exit(f"транскрипт не найден: {transcript_path}")
    if not inv_path.exists():
        sys.exit(f"inventory не найден: {inv_path}")

    cache_dir = args.cache_dir or out_path.parent / "match_cache"
    inventory = json.loads(inv_path.read_text())

    print(f"Загрузка фраз из {transcript_path.name}...")
    phrases = load_phrases(transcript_path)
    print(f"Фраз: {len(phrases)}")

    print(f"Сбор shots из {len([v for v in inventory if v.get('kind') == 'video'])} видео...")
    shots = collect_shots(inventory, cache_dir / "frames")
    print(f"Shots: {len(shots)}")

    if args.backend == "tt-describe":
        descriptions_dir = cache_dir / "descriptions"
        pending_path = cache_dir / "_pending_shots.json"
        if args.judge_only:
            tt_describe_backend_judge(phrases, shots, descriptions_dir, out_path)
        else:
            tt_describe_backend_prepare(phrases, shots, descriptions_dir, pending_path)
            # Если все уже описаны — сразу идём в judge
            if not json.loads(pending_path.read_text()):
                tt_describe_backend_judge(phrases, shots, descriptions_dir, out_path)
    elif args.backend == "clip-pytorch":
        clip_pytorch_backend(phrases, shots, cache_dir / "clip_embs", out_path)
    elif args.backend == "clip-onnx":
        clip_onnx_backend(phrases, shots, cache_dir / "onnx_embs", out_path)


if __name__ == "__main__":
    main()
