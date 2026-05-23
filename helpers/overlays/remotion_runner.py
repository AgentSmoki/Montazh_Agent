"""Remotion runner — React-композиции через npx + remotion CLI.

Используется для:
- product UI motion (анимированные mock-ups интерфейсов)
- кинетическая типографика с реактивной композицией
- brand-системы с React-компонентами

Каждый Remotion-проект изолирован внутри edit/animations/slot_<id>/.
Скаффолдится через `npx create-video@latest` при первом использовании.

Этот runner — обёртка над уже подготовленным Remotion-проектом:
ожидает, что в slot-дире уже есть package.json и src/Composition.tsx.

Usage:
    python helpers/overlays/remotion_runner.py \\
        --project-dir edit/animations/slot_02 \\
        --composition MyOverlay \\
        --out edit/animations/slot_02/render.mp4
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Remotion CLI runner")
    ap.add_argument("--project-dir", type=Path, required=True,
                    help="Папка с Remotion-проектом (содержит package.json + src/)")
    ap.add_argument("--composition", required=True,
                    help="ID композиции в src/Root.tsx")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--codec", default="h264", choices=["h264", "h265", "vp8", "vp9", "prores"])
    ap.add_argument("--quality", type=int, default=80, help="0-100 (default 80)")
    args = ap.parse_args()

    if not shutil.which("npx"):
        sys.exit("npx не найден. Установи Node.js (>= 18) через `brew install node`")

    project_dir = args.project_dir.resolve()
    if not (project_dir / "package.json").exists():
        sys.exit(f"package.json не найден в {project_dir}. "
                 f"Скаффолд: `cd {project_dir} && npx create-video@latest .`")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "npx", "remotion", "render",
        "src/index.tsx" if (project_dir / "src/index.tsx").exists() else "src/index.ts",
        args.composition,
        str(args.out.resolve()),
        f"--codec={args.codec}",
        f"--jpeg-quality={args.quality}",
    ]

    print(f"$ {' '.join(cmd)}  (cwd: {project_dir})")
    proc = subprocess.run(cmd, cwd=project_dir)
    if proc.returncode != 0:
        sys.exit(f"remotion завершился с кодом {proc.returncode}")

    print(f"✓ {args.out}")


if __name__ == "__main__":
    main()
