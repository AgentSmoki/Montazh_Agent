"""Audio-first match: для каждой фразы в аудио подобрать подходящий shot из видео.

Используется когда пользователь записал отдельно голосовое аудио и отдельно
несколько видео-съёмок без синхронной речи. Агент укладывает аудио как timeline
основу и подбирает видео-кадры под смысл каждой фразы.

Алгоритм:
  1. Берём scribe-формат транскрипта аудио (из transcripts/voice.json).
  2. Группируем word-токены в фразы (используем pack_transcripts.group_into_phrases).
  3. Для каждого видео-исходника:
     a. PySceneDetect → список shots
     b. Из каждого shot достаём middle-frame через ffmpeg → JPEG → CLIP-эмбеддинг
  4. Для каждой фразы:
     a. Embedding текста фразы через тот же CLIP (text encoder)
     b. cosine_similarity(phrase_emb, shot_emb) → ranking
     c. Выбираем top-1 shot, который ещё не использовался (или с уценкой за повтор)
  5. Выдаём EDL: [{audio_in, audio_out, video_source, video_in, video_out, score, reason}]

Тяжёлая операция — кеш CLIP-эмбеддингов в edit/clip_cache/.

Usage:
    python helpers/match_video_to_audio.py \
        --audio-transcript edit/transcripts/voice.json \
        --videos edit/inventory.json \
        --out edit/audio_first_edl.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def load_phrases(transcript_path: Path) -> list[dict]:
    """Группируем word-токены в фразы (повторяем логику pack_transcripts.py)."""
    sys.path.insert(0, str(Path(__file__).parent))
    from pack_transcripts import group_into_phrases  # type: ignore
    data = json.loads(transcript_path.read_text())
    words = data.get("words") or []
    return group_into_phrases(words, silence_threshold=0.5)


def extract_middle_frame(video: Path, mid_time: float, out_jpg: Path) -> None:
    """Сохраняет кадр в JPEG (для CLIP-эмбеддинга)."""
    cmd = [
        "ffmpeg", "-y", "-ss", f"{mid_time:.3f}",
        "-i", str(video), "-frames:v", "1",
        "-vf", "scale=336:-2", "-q:v", "3",
        str(out_jpg),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def get_clip_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit("sentence-transformers не установлен. `uv add sentence-transformers`")
    # clip-ViT-B-32 — компактная, выдаёт 512-d эмбеддинги и для текста, и для картинки
    return SentenceTransformer("sentence-transformers/clip-ViT-B-32")


def embed_image(model, img_path: Path):
    from PIL import Image
    img = Image.open(img_path).convert("RGB")
    return model.encode(img, convert_to_numpy=True, normalize_embeddings=True)


def embed_text(model, text: str):
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True)


def match_phrases_to_shots(
    phrases: list[dict],
    inventory: list[dict],
    cache_dir: Path,
) -> list[dict]:
    import numpy as np

    cache_dir.mkdir(parents=True, exist_ok=True)
    model = get_clip_model()

    # Собираем все shots из всех видео + считаем эмбеддинги
    print(f"подсчёт CLIP-эмбеддингов для {len([x for x in inventory if x.get('kind') == 'video'])} видео...")
    all_shots: list[dict] = []  # каждый: {source_path, source_name, shot_in, shot_out, emb}

    for video_meta in inventory:
        if video_meta.get("kind") != "video":
            continue
        source_path = Path(video_meta["path"])
        if not source_path.exists():
            continue

        # PySceneDetect
        from scenedetect import detect, ContentDetector
        scenes = detect(str(source_path), ContentDetector(threshold=27.0))
        if not scenes:
            # Один большой shot на весь файл, разбиваем по 5s
            dur = video_meta.get("duration_sec", 30.0)
            for i in range(0, int(dur), 5):
                shot_in = float(i)
                shot_out = min(float(i + 5), dur)
                scenes_emul = [(shot_in, shot_out)]
                for shot_in, shot_out in scenes_emul:
                    process_shot(source_path, shot_in, shot_out, model, cache_dir, all_shots)
        else:
            for start, end in scenes:
                shot_in = start.get_seconds()
                shot_out = end.get_seconds()
                process_shot(source_path, shot_in, shot_out, model, cache_dir, all_shots)

    if not all_shots:
        sys.exit("не найдено ни одного shot для матчинга")
    print(f"всего shots: {len(all_shots)}")

    # Стек эмбеддингов
    shot_embs = np.array([s["emb"] for s in all_shots])  # (N, 512)

    # Для каждой фразы — top shot по cosine
    edl_spans: list[dict] = []
    used_count = [0] * len(all_shots)

    for phrase in phrases:
        text = phrase["text"]
        text_emb = embed_text(model, text)  # (512,)
        sims = shot_embs @ text_emb  # cosine = dot, т.к. нормализованы

        # Штраф за повторы
        adjusted = sims - 0.05 * np.array(used_count)
        best_idx = int(np.argmax(adjusted))
        used_count[best_idx] += 1

        shot = all_shots[best_idx]
        phrase_dur = phrase["end"] - phrase["start"]
        shot_dur = shot["shot_out"] - shot["shot_in"]
        # Берём из shot ровно столько сколько фразы (с серединой shot'а)
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
            "phrase_text": text[:80],
        })

    return edl_spans


def process_shot(source_path, shot_in, shot_out, model, cache_dir, all_shots):
    """Извлекаем middle frame, считаем эмбеддинг, кешируем."""
    cache_key = f"{source_path.stem}_{shot_in:.2f}_{shot_out:.2f}"
    cache_file = cache_dir / f"{cache_key}.json"
    if cache_file.exists():
        emb = json.loads(cache_file.read_text())["emb"]
        all_shots.append({
            "source_path": str(source_path),
            "source_name": source_path.stem,
            "shot_in": shot_in,
            "shot_out": shot_out,
            "emb": emb,
        })
        return

    mid = (shot_in + shot_out) / 2
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        extract_middle_frame(source_path, mid, tmp_path)
        emb = embed_image(model, tmp_path).tolist()
        cache_file.write_text(json.dumps({"emb": emb}))
        all_shots.append({
            "source_path": str(source_path),
            "source_name": source_path.stem,
            "shot_in": shot_in,
            "shot_out": shot_out,
            "emb": emb,
        })
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audio-first: подбор видео-кадров под фразы аудио")
    ap.add_argument("--audio-transcript", type=Path, required=True,
                    help="Scribe-format JSON транскрипт аудио (с word-timestamps)")
    ap.add_argument("--videos", type=Path, required=True,
                    help="inventory.json со списком видео-исходников")
    ap.add_argument("--out", type=Path, required=True, help="Куда сохранить EDL-spans JSON")
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="Папка для кеша CLIP-эмбеддингов (default: <out.parent>/clip_cache/)")
    args = ap.parse_args()

    transcript_path = args.audio_transcript.resolve()
    inv_path = args.videos.resolve()
    out_path = args.out.resolve()

    if not transcript_path.exists():
        sys.exit(f"транскрипт не найден: {transcript_path}")
    if not inv_path.exists():
        sys.exit(f"inventory не найден: {inv_path}")

    cache_dir = args.cache_dir or out_path.parent / "clip_cache"
    inventory = json.loads(inv_path.read_text())
    phrases = load_phrases(transcript_path)
    print(f"фраз: {len(phrases)}")

    spans = match_phrases_to_shots(phrases, inventory, cache_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spans, ensure_ascii=False, indent=2))
    print(f"\n✓ EDL-spans → {out_path}  ({len(spans)} спанов)")


if __name__ == "__main__":
    main()
