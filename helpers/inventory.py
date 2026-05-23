"""Инвентаризация исходников в <videos_dir>/sources/ (или в <videos_dir>/).

Запускает ffprobe по каждому медиа-файлу и собирает структуру для агента:
кол-во, длительности, разрешения, fps, аудио, ориентация (вертикаль/горизонталь/квадрат).

Это первый шаг любой сессии — агент читает результат и решает, какой режим
запускать (multi-clip montage / audio-first / highlight / format-mix).

Usage:
    python helpers/inventory.py <videos_dir>
    python helpers/inventory.py <videos_dir> --json   # машинно-читаемый вывод
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def ffprobe_streams(path: Path) -> dict:
    """ffprobe → dict со всеми потоками файла."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()[:200]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": "invalid ffprobe output"}


def aspect_class(width: int, height: int) -> str:
    if width == 0 or height == 0:
        return "unknown"
    ratio = width / height
    if 0.95 <= ratio <= 1.05:
        return "square"
    if ratio < 0.95:
        return "vertical"  # 9:16, 3:4
    return "horizontal"  # 16:9, 4:3


def summarize_one(path: Path) -> dict:
    data = ffprobe_streams(path)
    if "error" in data:
        return {"path": str(path), "error": data["error"]}

    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0.0))
    size_mb = int(fmt.get("size", 0)) / (1024 * 1024)

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        None,
    )

    result: dict = {
        "path": str(path),
        "name": path.name,
        "stem": path.stem,
        "ext": path.suffix.lower(),
        "duration_sec": round(duration, 2),
        "size_mb": round(size_mb, 1),
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "kind": "video" if video_stream else ("audio" if audio_stream else "unknown"),
    }

    if video_stream:
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        # avg_frame_rate приходит как "30/1" или "30000/1001"
        fr = video_stream.get("avg_frame_rate", "0/1")
        try:
            num, den = fr.split("/")
            fps = round(float(num) / float(den), 2) if float(den) != 0 else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0

        result.update({
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}",
            "aspect_class": aspect_class(width, height),
            "fps": fps,
            "video_codec": video_stream.get("codec_name"),
            "color_transfer": video_stream.get("color_transfer"),
            "is_hdr": video_stream.get("color_transfer") in {"smpte2084", "arib-std-b67"},
        })

    if audio_stream:
        result.update({
            "audio_codec": audio_stream.get("codec_name"),
            "sample_rate": int(audio_stream.get("sample_rate", 0)),
            "audio_channels": int(audio_stream.get("channels", 0)),
        })

    return result


def find_sources(videos_dir: Path) -> list[Path]:
    """sources/ имеет приоритет; если её нет — берём корень videos_dir."""
    sources_dir = videos_dir / "sources"
    base = sources_dir if sources_dir.is_dir() else videos_dir

    files: list[Path] = []
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() in (VIDEO_EXTS | AUDIO_EXTS):
            files.append(p)
    return files


def print_human(items: list[dict]) -> None:
    print(f"найдено {len(items)} исходников:\n")
    videos = [x for x in items if x.get("kind") == "video"]
    audios = [x for x in items if x.get("kind") == "audio"]
    errors = [x for x in items if "error" in x]

    if videos:
        print(f"  Видео ({len(videos)}):")
        for v in videos:
            asp = v.get("aspect_class", "?")
            hdr = " HDR" if v.get("is_hdr") else ""
            print(f"    • {v['name']}  {v['duration_sec']:>6.1f}s  "
                  f"{v.get('resolution', '?'):>10}  {v.get('fps', 0):>5.1f}fps  "
                  f"[{asp}]{hdr}  {v['size_mb']:.0f}MB")

    if audios:
        print(f"\n  Аудио ({len(audios)}):")
        for a in audios:
            print(f"    • {a['name']}  {a['duration_sec']:>6.1f}s  "
                  f"{a.get('audio_codec', '?')}  {a.get('sample_rate', 0)}Hz  "
                  f"{a['size_mb']:.0f}MB")

    if errors:
        print(f"\n  Ошибки ({len(errors)}):")
        for e in errors:
            print(f"    × {Path(e['path']).name}: {e['error']}")

    # Подсказка по режиму
    print("\nРекомендация по режиму:")
    n_video = len(videos)
    n_audio = len(audios)
    if n_audio >= 1 and n_video >= 1:
        print("  → audio-first (есть голосовое аудио + видео-исходники)")
    elif n_video == 1:
        print("  → highlight-mode (один длинный файл → нарезаем по сценарию)")
    elif 2 <= n_video <= 10:
        print("  → multi-clip montage (несколько коротких → собираем 1 финал)")
    elif n_video > 10:
        print("  → multi-clip montage с агрессивной фильтрацией")
    else:
        print("  → нет источников. Возможно generative-only режим (всё генерится через MCP)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Инвентаризация исходников через ffprobe")
    ap.add_argument("videos_dir", type=Path, help="Корневая папка проекта (с sources/ или с файлами в корне)")
    ap.add_argument("--json", action="store_true", help="Машинно-читаемый JSON-вывод")
    ap.add_argument("--out", type=Path, default=None,
                    help="Сохранить JSON в файл (по умолчанию <videos_dir>/edit/inventory.json)")
    args = ap.parse_args()

    videos_dir = args.videos_dir.resolve()
    if not videos_dir.is_dir():
        sys.exit(f"не директория: {videos_dir}")

    files = find_sources(videos_dir)
    items = [summarize_one(p) for p in files]

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))

    out_path = args.out or (videos_dir / "edit" / "inventory.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2))

    if not args.json:
        print_human(items)
        print(f"\nсохранено: {out_path}")


if __name__ == "__main__":
    main()
