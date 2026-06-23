"""Простые PIL-overlays: TikTok-style 2-словные UPPERCASE-субтитры, бейджи, counters.

Это «дешёвый» runner — для всего, что можно сгенерить как PNG-последовательность
и склеить через ffmpeg в MP4 с прозрачным фоном (yuva420p).

Готовые пресеты (можно расширять):
- `tiktok_bold` — белый Helvetica Bold, чёрная обводка, 2-словные UPPERCASE
- `youtube_classic` — белый Roboto, чёрная подложка, sentence case
- `reels_animated` — пульсирующий fade-in, центрированно

Usage:
    python helpers/overlays/pil_subs.py --preset tiktok_bold \\
        --text "ПРИВЕТ ДРУЗЬЯ" --duration 2.0 --resolution 1080x1920 \\
        --out edit/animations/slot_01/render.mp4

Note: для финальных burn-in субтитров используется ffmpeg subtitles=... filter
(в render.py). Этот runner — для дополнительных декоративных карточек/бейджей.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


PRESETS = {
    "tiktok_bold": {
        "font_size_ratio": 0.06,  # от ширины кадра
        "color": (255, 255, 255),
        "stroke": (0, 0, 0),
        "stroke_width": 4,
        "case": "upper",
        "y_position": 0.50,
        "font_name": "Helvetica-Bold",
    },
    "youtube_classic": {
        "font_size_ratio": 0.04,
        "color": (255, 255, 255),
        "bg": (0, 0, 0, 180),
        "stroke_width": 0,
        "case": "sentence",
        "y_position": 0.85,
        "font_name": "Roboto-Bold",
    },
    "reels_animated": {
        "font_size_ratio": 0.055,
        "color": (255, 255, 255),
        "stroke": (0, 0, 0),
        "stroke_width": 6,
        "case": "upper",
        "y_position": 0.78,
        "font_name": "Helvetica-Bold",
        "bg": (0, 0, 0, 170),
        "animate": "fade_pulse",
    },
}


def find_font(font_name: str, size: int):
    """Кроссплатформенный поиск шрифта: сначала запрошенное имя в системных
    каталогах текущей ОС, затем жирный sans по умолчанию (Helvetica на macOS,
    Arial на Windows, DejaVu на Linux), в крайнем случае — PIL default."""
    import sys
    from PIL import ImageFont

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import platform_paths as pp

    # 1) точное имя пресета (например "Helvetica-Bold") как basename в font_dirs
    by_name = pp._find_in_font_dirs(
        [f"{font_name}.ttf", f"{font_name}.ttc", f"{font_name}.otf"]
    )
    # 2) дефолтный жирный sans под ОС
    fallback = pp.find_bold_sans()
    for path in (by_name, fallback):
        if path:
            try:
                return ImageFont.truetype(str(path), size, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def render_frame(text: str, width: int, height: int, preset: dict, frame_t: float = 0.0):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = int(width * preset["font_size_ratio"])
    font = find_font(preset.get("font_name", "Helvetica-Bold"), font_size)

    display_text = text.upper() if preset["case"] == "upper" else text

    bbox = draw.textbbox((0, 0), display_text, font=font, stroke_width=preset.get("stroke_width", 0))
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = int(height * preset["y_position"]) - text_h // 2

    # Фоновая подложка (если задана)
    if preset.get("bg"):
        pad = int(font_size * 0.4)
        draw.rectangle(
            [x - pad, y - pad, x + text_w + pad, y + text_h + pad],
            fill=preset["bg"],
        )

    # Текст с обводкой
    if preset.get("stroke_width", 0) > 0:
        draw.text(
            (x, y), display_text, font=font, fill=preset["color"],
            stroke_width=preset["stroke_width"], stroke_fill=preset["stroke"],
        )
    else:
        draw.text((x, y), display_text, font=font, fill=preset["color"])

    # Анимации
    if preset.get("animate") == "fade_pulse":
        # Пульсация прозрачности 0.7-1.0
        import math
        alpha = int(255 * (0.85 + 0.15 * math.sin(frame_t * 6)))
        alpha_img = img.split()[-1]
        alpha_img = alpha_img.point(lambda p: min(p, alpha))
        img.putalpha(alpha_img)

    return img


def make_png_sequence(text: str, duration: float, resolution: tuple[int, int],
                      preset: dict, fps: int, out_dir: Path) -> None:
    n_frames = int(duration * fps)
    for i in range(n_frames):
        t = i / fps
        img = render_frame(text, resolution[0], resolution[1], preset, t)
        img.save(out_dir / f"frame_{i:05d}.png")


def png_seq_to_mp4(in_dir: Path, fps: int, out_path: Path) -> None:
    """PNG sequence → MP4 с прозрачным альфа-каналом (yuva420p)."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(in_dir / "frame_%05d.png"),
        "-c:v", "qtrle",  # alpha-supporting codec в MOV-контейнере
        "-pix_fmt", "argb",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main() -> None:
    ap = argparse.ArgumentParser(description="PIL-overlay runner (PNG sequence → MP4)")
    ap.add_argument("--preset", choices=list(PRESETS.keys()), required=True)
    ap.add_argument("--text", required=True, help="Текст оверлея")
    ap.add_argument("--duration", type=float, required=True, help="Длительность в секундах")
    ap.add_argument("--resolution", default="1080x1920", help="WxH (default 1080x1920 вертикаль)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", type=Path, required=True, help="Путь к выходному MOV (с альфой)")
    args = ap.parse_args()

    try:
        w, h = map(int, args.resolution.split("x"))
    except Exception:
        sys.exit(f"Неверное разрешение: {args.resolution}")

    preset = PRESETS[args.preset]
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        make_png_sequence(args.text, args.duration, (w, h), preset, args.fps, tmp_path)
        png_seq_to_mp4(tmp_path, args.fps, args.out)

    print(f"✓ {args.out}  ({args.duration:.1f}s @ {args.fps}fps, preset={args.preset})")


if __name__ == "__main__":
    main()
