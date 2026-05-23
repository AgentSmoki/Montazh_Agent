"""HyperFrames runner — browser-native HTML/CSS/GSAP композиции.

Используется для:
- web-style анимаций (landing-page promo)
- кинетической типографики через GSAP
- transparent WebM-оверлеев с альфа-каналом
- mockup-to-video (берёт live website и превращает в видео)

Скаффолдится в slot-дире через:
  npx --yes hyperframes init . --example blank --non-interactive --skip-skills

Затем агент пишет HTML/CSS вручную и запускает рендер этим скриптом.

Usage:
    python helpers/overlays/hyperframes_runner.py \\
        --project-dir edit/animations/slot_04 \\
        --out edit/animations/slot_04/render.mp4

    # Прозрачный WebM (для оверлей-композиции с alpha):
    python helpers/overlays/hyperframes_runner.py \\
        --project-dir edit/animations/slot_04 \\
        --format webm \\
        --out edit/animations/slot_04/render.webm
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="HyperFrames CLI runner")
    ap.add_argument("--project-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--format", default="mp4", choices=["mp4", "webm"],
                    help="webm для прозрачного фона (alpha)")
    ap.add_argument("--lint", action="store_true",
                    help="Прогнать hyperframes lint+validate перед рендером")
    args = ap.parse_args()

    if not shutil.which("npx"):
        sys.exit("npx не найден. Установи Node.js >= 22 через `brew install node`")

    project_dir = args.project_dir.resolve()
    if not project_dir.exists():
        sys.exit(f"project-dir не найден: {project_dir}")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.lint:
        for sub in ("lint", "validate"):
            proc = subprocess.run(
                ["npx", "--yes", "hyperframes", sub, "."],
                cwd=project_dir,
            )
            if proc.returncode != 0:
                sys.exit(f"hyperframes {sub} failed (код {proc.returncode})")

    cmd = ["npx", "--yes", "hyperframes", "render", "."]
    cmd += ["-o", str(args.out.resolve())]
    if args.format == "webm":
        cmd += ["--format", "webm"]

    print(f"$ {' '.join(cmd)}  (cwd: {project_dir})")
    proc = subprocess.run(cmd, cwd=project_dir)
    if proc.returncode != 0:
        sys.exit(f"hyperframes render failed (код {proc.returncode})")

    print(f"✓ {args.out}")


if __name__ == "__main__":
    main()
