"""
helpers/env_doctor.py — первичная диагностика окружения Montazh_Agent под ОС.

Запускается агентом на Шаге 0 (старт сессии) и перед монтажём. Определяет ОС,
проверяет наличие критичных (ffmpeg, ffprobe, python>=3.10, Pillow) и
опциональных (manim, node/npx, шрифты, TT_API_KEY) инструментов и печатает
команды установки ПОД КОНКРЕТНУЮ ОС только для того, чего не хватает.

Использование:
    python helpers/env_doctor.py            # человекочитаемый отчёт (ru)
    python helpers/env_doctor.py --json     # машинный JSON для агента

Exit code: 0 — все критичные инструменты на месте; 1 — чего-то критичного нет.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import platform_paths as pp  # noqa: E402


# -------- Команды установки под ОС ------------------------------------------

INSTALL = {
    "windows": {
        "ffmpeg": "winget install Gyan.FFmpeg   (или: choco install ffmpeg / scoop install ffmpeg)",
        "python": "winget install Python.Python.3.12",
        "node": "winget install OpenJS.NodeJS.LTS",
        "pillow": "py -m pip install pillow",
        "manim": "py -m pip install manim   (нужен также MiKTeX для LaTeX-сцен)",
        "fonts": "Шрифты Arial/Segoe UI идут с Windows. Доп.: положить .ttf в %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts",
        "shell_note": "Шелл PowerShell/cmd: heredoc (<<EOF) НЕ работает — используй Set-Content / py -c.",
    },
    "macos": {
        "ffmpeg": "brew install ffmpeg",
        "python": "brew install python@3.12",
        "node": "brew install node",
        "pillow": "python3 -m pip install pillow",
        "manim": "brew install manim   (или python3 -m pip install manim)",
        "fonts": "Helvetica/Menlo идут с macOS. Доп. шрифты — в ~/Library/Fonts.",
        "shell_note": "Шелл zsh/bash: всё штатно.",
    },
    "linux": {
        "ffmpeg": "sudo apt install ffmpeg   (Fedora: sudo dnf install ffmpeg)",
        "python": "sudo apt install python3 python3-pip",
        "node": "sudo apt install nodejs npm",
        "pillow": "python3 -m pip install pillow",
        "manim": "python3 -m pip install manim   (+ sudo apt install texlive для LaTeX)",
        "fonts": "sudo apt install fonts-dejavu fonts-liberation",
        "shell_note": "Шелл bash: всё штатно.",
    },
}


def _install_hint(key: str) -> str:
    return INSTALL.get(pp.os_name(), INSTALL["linux"]).get(key, "")


# -------- Проверки -----------------------------------------------------------


def _version_of(bin_name: str, args: list[str] | None = None) -> str | None:
    path = shutil.which(bin_name)
    if not path:
        return None
    try:
        out = subprocess.run(
            [path] + (args or ["-version"]),
            capture_output=True,
            text=True,
            timeout=15,
        )
        first = (out.stdout or out.stderr).splitlines()
        return first[0].strip() if first else path
    except Exception:
        return path


def collect() -> dict:
    py_ok = sys.version_info >= (3, 10)
    ffmpeg_v = _version_of("ffmpeg")
    ffprobe_v = _version_of("ffprobe")

    try:
        import PIL  # noqa: F401

        pillow_ok = True
        pillow_v = getattr(__import__("PIL"), "__version__", "?")
    except Exception:
        pillow_ok = False
        pillow_v = None

    bold = pp.find_bold_sans()
    mono = pp.find_mono()

    env_path = Path(__file__).resolve().parents[1] / ".env"
    tt_key = bool(os.environ.get("TT_API_KEY"))
    if not tt_key and env_path.exists():
        try:
            tt_key = "TT_API_KEY=" in env_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass

    critical = {
        "python>=3.10": py_ok,
        "ffmpeg": ffmpeg_v is not None,
        "ffprobe": ffprobe_v is not None,
        "Pillow": pillow_ok,
    }

    return {
        "os": pp.os_name(),
        "os_release": platform.platform(),
        "arch": platform.machine(),
        "is_wsl": pp.is_wsl(),
        "python": sys.version.split()[0],
        "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC") or "?",
        "critical": critical,
        "ffmpeg_version": ffmpeg_v,
        "ffprobe_version": ffprobe_v,
        "pillow_version": pillow_v,
        "fonts": {
            "dirs": [str(d) for d in pp.font_dirs()],
            "bold_sans": str(bold) if bold else None,
            "mono": str(mono) if mono else None,
            "libass_name": pp.libass_font_name(),
        },
        "optional": {
            "manim": shutil.which("manim") is not None,
            "node/npx": shutil.which("npx") is not None,
        },
        "tt_api_key": tt_key,
        "ok": all(critical.values()),
    }


# -------- Отчёт --------------------------------------------------------------


def report(d: dict) -> str:
    L: list[str] = []
    ok_mark = "✅" if d["ok"] else "❌"
    L.append(f"{ok_mark} Montazh_Agent env-doctor — ОС: {d['os']} ({d['os_release']}), arch {d['arch']}")
    if d["is_wsl"]:
        L.append("   ⚠️  WSL: ffmpeg ставится как на Linux; пути к Windows-дискам через /mnt/c.")
    L.append(f"   python {d['python']} · shell {d['shell']}")
    L.append("")
    L.append("Критичное:")
    for name, ok in d["critical"].items():
        mark = "✅" if ok else "❌"
        ver = ""
        if name == "ffmpeg" and d["ffmpeg_version"]:
            ver = f" — {d['ffmpeg_version']}"
        elif name == "ffprobe" and d["ffprobe_version"]:
            ver = f" — {d['ffprobe_version']}"
        elif name == "Pillow" and d["pillow_version"]:
            ver = f" — {d['pillow_version']}"
        L.append(f"  {mark} {name}{ver}")
        if not ok:
            key = "python" if name.startswith("python") else ("pillow" if name == "Pillow" else name)
            hint = _install_hint(key)
            if hint:
                L.append(f"       → установить: {hint}")
    L.append("")
    f = d["fonts"]
    fmark = "✅" if f["bold_sans"] else "⚠️"
    L.append(f"Шрифты ({fmark}): libass='{f['libass_name']}'")
    L.append(f"  bold sans: {f['bold_sans'] or 'НЕ найден → PIL default'}")
    L.append(f"  mono:      {f['mono'] or 'НЕ найден → PIL default'}")
    if not f["bold_sans"]:
        L.append(f"       → {_install_hint('fonts')}")
    L.append("")
    L.append("Опциональное:")
    L.append(f"  {'✅' if d['optional']['manim'] else '—'} manim (диаграммы/математика)")
    L.append(f"  {'✅' if d['optional']['node/npx'] else '—'} node/npx (Remotion / HyperFrames оверлеи)")
    L.append(f"  {'✅' if d['tt_api_key'] else '❌'} TT_API_KEY (транскрипция — без него pipeline не запустится)")
    L.append("")
    L.append(f"Заметка по шеллу: {_install_hint('shell_note')}")
    if not d["ok"]:
        L.append("")
        L.append("❌ Не хватает критичных инструментов — установи их перед монтажём (команды выше).")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Диагностика окружения Montazh_Agent под ОС")
    ap.add_argument("--json", action="store_true", help="вывести машинный JSON вместо отчёта")
    args = ap.parse_args()

    d = collect()
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(report(d))
    return 0 if d["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
