"""Manim runner — тонкая обёртка над `manim` CLI.

Используется для:
- математических равенств и диаграмм
- state-machine визуализаций
- graph morphs (один граф → другой)
- explainer-видео (3Blue1Brown стиль)

Полная палитра приёмов — в `skills/manim-video/` (15 reference-файлов от upstream).
Перед написанием Manim-сцены агент должен прочитать `skills/manim-video/SKILL.md`.

Этот runner не пишет Manim-код за тебя — он только запускает `manim` CLI
на уже написанном Python-файле сцены и возвращает MP4.

Usage:
    python helpers/overlays/manim_runner.py \\
        --scene-file edit/animations/slot_03/scene.py \\
        --scene-class MyAnimation \\
        --quality h \\
        --out edit/animations/slot_03/render.mp4
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


QUALITIES = {
    "l": ["-ql"],  # 480p15
    "m": ["-qm"],  # 720p30
    "h": ["-qh"],  # 1080p60
    "k": ["-qk"],  # 4k60
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Manim CLI runner")
    ap.add_argument("--scene-file", type=Path, required=True,
                    help="Python-файл со сценой (Scene-класс)")
    ap.add_argument("--scene-class", required=True,
                    help="Имя класса Scene внутри scene-file")
    ap.add_argument("--quality", choices=list(QUALITIES.keys()), default="h",
                    help="Качество рендера (l=480p, m=720p, h=1080p, k=4k)")
    ap.add_argument("--out", type=Path, required=True,
                    help="Куда положить готовый MP4 (manim рендерит в media/, мы перекладываем)")
    ap.add_argument("--transparent", action="store_true",
                    help="Прозрачный фон (для оверлей-композиции)")
    args = ap.parse_args()

    if not shutil.which("manim"):
        sys.exit("manim не установлен. `uv add manim --optional animations` "
                 "или `pip install manim`")

    if not args.scene_file.exists():
        sys.exit(f"scene-file не найден: {args.scene_file}")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    # Manim рендерит в media/ относительно текущей директории
    cwd = args.scene_file.parent
    cmd = ["manim", *QUALITIES[args.quality]]
    if args.transparent:
        cmd += ["-t"]
    cmd += [str(args.scene_file.name), args.scene_class]

    print(f"$ {' '.join(cmd)}  (cwd: {cwd})")
    proc = subprocess.run(cmd, cwd=cwd)
    if proc.returncode != 0:
        sys.exit(f"manim завершился с кодом {proc.returncode}")

    # Находим выхлоп
    media_dir = cwd / "media" / "videos" / args.scene_file.stem
    candidates = sorted(media_dir.glob(f"**/{args.scene_class}.mp4")) if media_dir.exists() else []
    if not candidates:
        sys.exit(f"не нашёл рендер в {media_dir}")

    rendered = candidates[0]
    shutil.copy(rendered, args.out)
    print(f"✓ {args.out}")


if __name__ == "__main__":
    main()
