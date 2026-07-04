#!/usr/bin/env python3
"""Эмодзи-акцент как overlay-клип с альфой (pop-in → hold → fade-out).

Зачем: динамика в talking-head рилз — эмодзи появляется точно на слове-обозначении
(«юрист» → ⚖, «внизу» → 👇). Выход — полнокадровый qtrle MOV с прозрачностью,
готовый для EDL `overlays` (position="topleft").

Использование:
    python helpers/emoji_overlay.py "⚖" --duration 2.2 --center 850,520 \
        --out edit/animations/emoji/weights.mov
    # затем в EDL:
    # {"file": "animations/emoji/weights.mov", "start_in_output": 25.2,
    #  "duration": 2.2, "position": "topleft"}

Тайминг payoff (SKILL.md): start_in_output считай по ПОСТ-snap таймлайну —
cum-старт сегмента из лога render.py + (word.start − segment.start).

Ограничения PIL: цветные эмодзи рисуются только из bitmap-шрифтов (Apple sbix /
Noto CBDT) на их родном strike-размере; ZWJ-секвенции (👨‍⚖️) не собираются —
используй одиночные codepoint'ы (⚖, 🛡, 📩, ✅, 👇...).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from platform_paths import find_emoji_font  # noqa: E402

# Родные strike-размеры bitmap-эмодзи (Apple sbix: 160 есть всегда; Noto CBDT: 128/136)
_STRIKE_SIZES = (160, 137, 136, 128, 96, 64)

POP_FRAMES = 8    # pop-in 0.27с @30fps: scale 0.3→1.0 + fade-in, ease-out-cubic
FADE_FRAMES = 9   # fade-out 0.30с @30fps


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _load_font():
    from PIL import ImageFont

    font_path = find_emoji_font()
    if font_path is None:
        sys.exit("Цветной эмодзи-шрифт не найден (Apple Color Emoji / NotoColorEmoji). "
                 "На Windows/Linux установи Noto Color Emoji и повтори.")
    for size in _STRIKE_SIZES:
        try:
            f = ImageFont.truetype(str(font_path), size)
            f.getbbox("⚖")
            return f
        except Exception:
            continue
    sys.exit(f"Шрифт {font_path} не дал ни одного рабочего strike-размера {_STRIKE_SIZES}.")


def render_emoji_clip(
    emoji: str,
    duration: float,
    out_path: Path,
    center: tuple[int, int] = (850, 560),
    display_px: int = 200,
    resolution: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    fade_out: bool = True,
) -> Path:
    """PNG-секвенция pop-in анимации → qtrle MOV с альфой. Возвращает out_path."""
    from PIL import Image, ImageDraw

    font = _load_font()
    W, H = resolution
    cx, cy = center

    canvas = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((200, 200), emoji, font=font,
                                embedded_color=True, anchor="mm")
    bbox = canvas.getbbox()
    if bbox is None:
        sys.exit(f"Эмодзи {emoji!r} отрисовался пустым — вероятно ZWJ-секвенция "
                 "или глифа нет в шрифте. Возьми одиночный codepoint.")
    base = canvas.crop(bbox)

    n = max(2, round(duration * fps))
    seq = Path(tempfile.mkdtemp(prefix="emoji_seq_"))
    try:
        for i in range(n):
            frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            if i < POP_FRAMES:
                k = _ease_out_cubic((i + 1) / POP_FRAMES)
                scale, alpha = 0.3 + 0.7 * k, k
            else:
                scale, alpha = 1.0, 1.0
            left = n - 1 - i
            if fade_out and left < FADE_FRAMES:
                alpha = min(alpha, left / FADE_FRAMES)
            size = max(2, int(display_px * scale))
            ratio = size / max(base.size)
            em = base.resize((max(1, int(base.size[0] * ratio)),
                              max(1, int(base.size[1] * ratio))), Image.LANCZOS)
            if alpha < 1.0:
                em.putalpha(em.getchannel("A").point(lambda p: int(p * alpha)))
            frame.paste(em, (cx - em.size[0] // 2, cy - em.size[1] // 2), em)
            frame.save(seq / f"frame_{i:05d}.png")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps),
             "-i", str(seq / "frame_%05d.png"),
             "-c:v", "qtrle", "-pix_fmt", "argb", str(out_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    finally:
        shutil.rmtree(seq, ignore_errors=True)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Эмодзи-акцент → alpha-overlay MOV")
    ap.add_argument("emoji", help="Одиночный эмодзи (⚖ 🛡 📩 ✅ 👇 💬 ...)")
    ap.add_argument("--duration", type=float, required=True, help="Длительность, сек")
    ap.add_argument("--out", type=Path, required=True, help="Путь к выходному .mov")
    ap.add_argument("--center", default="850,560",
                    help="Центр эмодзи 'x,y' (default 850,560 — справа от головы; "
                         "для screen-битов возьми 540,350)")
    ap.add_argument("--size", type=int, default=200, help="Размер, px (default 200)")
    ap.add_argument("--resolution", default="1080x1920", help="WxH кадра")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-fade-out", action="store_true",
                    help="Без fade-out (клип обрывается резом)")
    args = ap.parse_args()

    cx, cy = (int(v) for v in args.center.split(","))
    w, h = (int(v) for v in args.resolution.lower().split("x"))
    out = render_emoji_clip(
        args.emoji, args.duration, args.out,
        center=(cx, cy), display_px=args.size,
        resolution=(w, h), fps=args.fps, fade_out=not args.no_fade_out,
    )
    print(f"✓ {args.emoji} → {out}  ({args.duration}s, центр {cx},{cy})")


if __name__ == "__main__":
    main()
