"""
helpers/platform_paths.py — кроссплатформенное разрешение ОС, шрифтов и бинарей.

Единая точка правды про различия macOS / Windows / Linux для Montazh_Agent.
Используется pil_subs.py, timeline_view.py, render.py, env_doctor.py.

Принцип: код не хардкодит macOS-пути. Любое обращение к системным шрифтам или
к ffmpeg идёт через функции этого модуля, которые сами выбирают правильный путь
под текущую ОС.
"""
from __future__ import annotations

import functools
import os
import platform
import shutil
from pathlib import Path


@functools.lru_cache(maxsize=1)
def os_name() -> str:
    """Нормализованное имя ОС: 'windows' | 'macos' | 'linux' | 'unknown'."""
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    if s == "linux":
        return "linux"
    return "unknown"


def is_windows() -> bool:
    return os_name() == "windows"


def is_macos() -> bool:
    return os_name() == "macos"


def is_linux() -> bool:
    return os_name() == "linux"


@functools.lru_cache(maxsize=1)
def is_wsl() -> bool:
    """WSL — это Linux-ядро поверх Windows; ffmpeg ставится как на Linux."""
    if os_name() != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False


# -------- Шрифты -------------------------------------------------------------


def font_dirs() -> list[Path]:
    """Каталоги системных шрифтов под текущую ОС (только существующие)."""
    name = os_name()
    if name == "windows":
        win = os.environ.get("WINDIR", r"C:\Windows")
        local = os.environ.get("LOCALAPPDATA", "")
        cand = [Path(win) / "Fonts"]
        if local:
            cand.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return [d for d in cand if d.exists()]
    if name == "macos":
        cand = [
            "/System/Library/Fonts",
            "/System/Library/Fonts/Supplemental",
            "/Library/Fonts",
            str(Path.home() / "Library" / "Fonts"),
        ]
        return [Path(p) for p in cand if Path(p).exists()]
    # linux / unknown
    cand = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        str(Path.home() / ".fonts"),
        str(Path.home() / ".local" / "share" / "fonts"),
    ]
    return [Path(p) for p in cand if Path(p).exists()]


# Жирный sans-serif по умолчанию: что реально установлено «из коробки» на каждой ОС.
_BOLD_SANS = {
    "windows": ["arialbd.ttf", "segoeuib.ttf", "calibrib.ttf", "arial.ttf", "segoeui.ttf"],
    "macos": ["Helvetica.ttc", "HelveticaNeue.ttc", "Arial Bold.ttf", "Arial.ttf", "SFNS.ttf"],
    "linux": ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans.ttf"],
}
_MONO = {
    "windows": ["consola.ttf", "cour.ttf", "lucon.ttf"],
    "macos": ["Menlo.ttc", "SFNSMono.ttf", "Courier New.ttf"],
    "linux": ["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"],
}
# Цветные эмодзи: Apple = sbix-битмапы (PIL рисует только на строгих strike-размерах,
# 160px есть всегда), Noto = CBDT-битмапы (тоже ок), Segoe = COLR-векторы —
# Pillow их НЕ растеризует в цвете; для Windows Noto надо доустановить.
_EMOJI = {
    "macos": ["Apple Color Emoji.ttc"],
    "linux": ["NotoColorEmoji.ttf", "NotoColorEmoji-Regular.ttf"],
    "windows": ["NotoColorEmoji.ttf", "seguiemj.ttf"],
}


@functools.lru_cache(maxsize=64)
def _scan_index() -> dict[str, str]:
    """Один проход по font_dirs: {имя_файла_в_lowercase: абсолютный_путь}."""
    index: dict[str, str] = {}
    for d in font_dirs():
        try:
            for p in d.rglob("*.tt*"):  # ttf / ttc / otf-как-tt; покрывает основное
                index.setdefault(p.name.lower(), str(p))
        except Exception:
            continue
    return index


def _find_in_font_dirs(basenames: list[str]) -> Path | None:
    index = _scan_index()
    for bn in basenames:
        hit = index.get(bn.lower())
        if hit:
            return Path(hit)
    return None


def find_bold_sans(extra: list[str] | None = None) -> Path | None:
    """Путь к жирному sans-шрифту под текущую ОС (или None — caller падает на PIL default)."""
    names = list(extra or []) + _BOLD_SANS.get(os_name(), _BOLD_SANS["linux"])
    return _find_in_font_dirs(names)


def find_mono(extra: list[str] | None = None) -> Path | None:
    """Путь к моноширинному шрифту под текущую ОС."""
    names = list(extra or []) + _MONO.get(os_name(), _MONO["linux"])
    return _find_in_font_dirs(names)


def find_emoji_font(extra: list[str] | None = None) -> Path | None:
    """Путь к цветному эмодзи-шрифту под текущую ОС (или None — эмодзи-оверлеи недоступны)."""
    names = list(extra or []) + _EMOJI.get(os_name(), _EMOJI["linux"])
    return _find_in_font_dirs(names)


def libass_font_name() -> str:
    """
    Имя шрифта для force_style ffmpeg subtitles (libass резолвит ИМЯ через
    fontconfig на Linux / GDI на Windows / CoreText на macOS). Helvetica есть
    только на macOS — на Windows нужен Arial, на Linux DejaVu Sans.
    """
    return {"windows": "Arial", "macos": "Helvetica", "linux": "DejaVu Sans"}.get(
        os_name(), "sans-serif"
    )


# -------- Бинари -------------------------------------------------------------


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    """
    Путь к ffmpeg/ffprobe. Приоритет: переменная окружения (FFMPEG_BIN/FFPROBE_BIN)
    → PATH (shutil.which учитывает .exe на Windows) → голое имя (subprocess
    упадёт с понятной ошибкой, если не найдено).
    """
    env_key = {"ffmpeg": "FFMPEG_BIN", "ffprobe": "FFPROBE_BIN"}.get(name)
    if env_key and os.environ.get(env_key):
        return os.environ[env_key]
    found = shutil.which(name)
    return found if found else name


def has_tool(name: str) -> bool:
    """Есть ли инструмент в PATH (кроссплатформенно, с учётом .exe)."""
    return shutil.which(name) is not None


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            {
                "os": os_name(),
                "is_wsl": is_wsl(),
                "font_dirs": [str(d) for d in font_dirs()],
                "bold_sans": str(find_bold_sans() or ""),
                "mono": str(find_mono() or ""),
                "libass_font_name": libass_font_name(),
                "ffmpeg": ffmpeg_bin("ffmpeg"),
                "ffprobe": ffmpeg_bin("ffprobe"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
