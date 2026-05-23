"""Детект границ кадров (shots) в видео через PySceneDetect.

Используется в двух местах:
1. multi-clip montage — найти все shots в каждом клипе, чтобы LLM мог выбирать целиком shot-ом.
2. audio-first mode — кандидаты для подбора под фразы (см. match_video_to_audio.py).

Дёшево: ContentDetector с threshold=27 (default). Для длинных файлов — кешируется.

Usage:
    python helpers/scene_detect.py <video.mp4>
    python helpers/scene_detect.py <video.mp4> --threshold 30 --min-len 1.0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def detect_shots(video_path: Path, threshold: float = 27.0,
                 min_scene_len_s: float = 0.5) -> list[dict]:
    """Возвращает список shots: [{idx, start, end, duration}, ...]"""
    try:
        from scenedetect import detect, ContentDetector
    except ImportError:
        sys.exit("scenedetect не установлен. `uv add scenedetect[opencv]`")

    scenes = detect(
        str(video_path),
        ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len_s * 30)),
    )

    out: list[dict] = []
    for i, (start, end) in enumerate(scenes):
        start_s = start.get_seconds()
        end_s = end.get_seconds()
        out.append({
            "idx": i,
            "start": round(start_s, 3),
            "end": round(end_s, 3),
            "duration": round(end_s - start_s, 3),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Детект границ кадров через PySceneDetect")
    ap.add_argument("video", type=Path)
    ap.add_argument("--threshold", type=float, default=27.0,
                    help="ContentDetector threshold (default 27)")
    ap.add_argument("--min-len", type=float, default=0.5,
                    help="Минимальная длительность сцены в секундах")
    ap.add_argument("--out", type=Path, default=None,
                    help="JSON-вывод (по умолчанию <edit>/shots/<stem>.json)")
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"видео не найдено: {video}")

    out_path = args.out
    if out_path is None:
        edit_dir = video.parent / "edit"
        out_path = edit_dir / "shots" / f"{video.stem}.json"

    # Кеш
    if out_path.exists():
        cached = json.loads(out_path.read_text())
        print(f"cached: {out_path.name} ({len(cached)} shots)")
        return

    shots = detect_shots(video, args.threshold, args.min_len)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(shots, indent=2))

    total = sum(s["duration"] for s in shots)
    print(f"{video.name}: {len(shots)} shots, суммарно {total:.1f}s")
    print(f"сохранено: {out_path}")


if __name__ == "__main__":
    main()
