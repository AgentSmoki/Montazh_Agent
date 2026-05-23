"""Детект границ кадров (shots) в видео.

Два backend'а:
- `scenedetect` (default) — PySceneDetect ContentDetector + OpenCV.
  Поддерживает downscale_factor для 4-6× ускорения на длинных файлах.
- `ffmpeg` — встроенный scenecut filter `select='gt(scene,T)'`.
  В 2-3× быстрее (работает на уровне C-библиотек), не требует OpenCV.
  Полезен для lean-stack варианта (см. Gemini Deep Research, Block 5).

Используется в:
- multi-clip montage — границы shots в каждом клипе для выбора куском
- audio-first mode — кандидаты для matching по фразам аудио
- B-roll dedup — определение «уже видели похожий shot»

Usage:
    python helpers/scene_detect.py <video.mp4>
    python helpers/scene_detect.py <video.mp4> --engine scenedetect --downscale 4
    python helpers/scene_detect.py <video.mp4> --engine ffmpeg --threshold 0.4
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Backend 1: PySceneDetect (с downscale для ускорения)
# ─────────────────────────────────────────────────────────────────────────────

def detect_shots_scenedetect(
    video_path: Path,
    threshold: float = 27.0,
    min_scene_len_s: float = 0.5,
    downscale: int = 4,
) -> list[dict]:
    """PySceneDetect ContentDetector.

    downscale=4 — 4× меньше пикселей на frame → 4-6× быстрее, не теряя точность
    границ (различия видны и в 240p).
    """
    try:
        from scenedetect import detect, ContentDetector, open_video, SceneManager
    except ImportError:
        sys.exit("scenedetect не установлен. Запусти `uv sync`")

    if downscale and downscale > 1:
        video = open_video(str(video_path))
        video.set_downscale_factor(downscale)
        sm = SceneManager()
        sm.add_detector(
            ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len_s * 30))
        )
        sm.detect_scenes(video=video)
        scenes = sm.get_scene_list()
    else:
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


# ─────────────────────────────────────────────────────────────────────────────
# Backend 2: FFmpeg scenecut filter (lean, без OpenCV)
# ─────────────────────────────────────────────────────────────────────────────

def detect_shots_ffmpeg(
    video_path: Path,
    threshold: float = 0.4,
    min_scene_len_s: float = 0.5,
) -> list[dict]:
    """FFmpeg select='gt(scene,T)' — нативный scene detector C-уровня.

    threshold: 0.0-1.0, типично 0.3-0.5. Меньше → больше границ.
    Источник: ffmpeg docs, Gemini рекомендация Block 5.
    """
    cmd = [
        "ffmpeg", "-hide_banner",
        "-i", str(video_path),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 and "Error" in proc.stderr:
        sys.exit(f"ffmpeg ошибка: {proc.stderr[:300]}")

    # Парсим showinfo → выдёргиваем pts_time
    pts_times: list[float] = []
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            try:
                pts_times.append(float(m.group(1)))
            except ValueError:
                continue

    # Определяем длительность файла
    dur_proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    total_duration = float(dur_proc.stdout.strip() or "0.0")

    # Конструируем shots: каждый pts_time — это начало нового шота,
    # предыдущий заканчивается тут же. Первый шот начинается с 0.
    boundaries = [0.0] + sorted(pts_times) + [total_duration]
    out: list[dict] = []
    for i in range(len(boundaries) - 1):
        start_s = boundaries[i]
        end_s = boundaries[i + 1]
        dur = end_s - start_s
        if dur < min_scene_len_s:
            continue
        out.append({
            "idx": len(out),
            "start": round(start_s, 3),
            "end": round(end_s, 3),
            "duration": round(dur, 3),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Детект границ кадров (scenedetect или ffmpeg)")
    ap.add_argument("video", type=Path)
    ap.add_argument("--engine", choices=["scenedetect", "ffmpeg"], default="scenedetect",
                    help="Backend: scenedetect (default, нужен OpenCV) или ffmpeg (lean)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="ContentDetector threshold (default 27 для scenedetect, 0.4 для ffmpeg)")
    ap.add_argument("--min-len", type=float, default=0.5,
                    help="Минимальная длительность сцены в секундах")
    ap.add_argument("--downscale", type=int, default=4,
                    help="Downscale factor для scenedetect (1=без, 4=4×4 меньше пикселей, 4-6× быстрее)")
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

    if out_path.exists():
        cached = json.loads(out_path.read_text())
        print(f"cached: {out_path.name} ({len(cached)} shots)")
        return

    if args.engine == "scenedetect":
        threshold = args.threshold if args.threshold is not None else 27.0
        shots = detect_shots_scenedetect(video, threshold, args.min_len, args.downscale)
    else:
        threshold = args.threshold if args.threshold is not None else 0.4
        shots = detect_shots_ffmpeg(video, threshold, args.min_len)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(shots, indent=2))

    total = sum(s["duration"] for s in shots)
    print(f"{video.name}: {len(shots)} shots, суммарно {total:.1f}s (engine={args.engine})")
    print(f"сохранено: {out_path}")


if __name__ == "__main__":
    main()
