"""Текст «за спиной»: слово/фраза уходит за человека (MediaPipe selfie segmentation).

Приём из советов блогеров: берём одно слово и убираем его немного за голову —
кадр перестаёт быть «унылым», текст читается как часть пространства.

Два режима:
  still  — макет на одном кадре (PNG). Быстро показать пользователю варианты.
  clip   — overlay-клип с альфой для EDL `overlays` (qtrle MOV, position topleft):
           в клипе лежат ТЕКСТ (там, где его не закрывает человек) + ВЫРЕЗАННЫЙ ЧЕЛОВЕК
           в зоне текста. Наложение на базу даёт эффект «текст за спиной».
           Вход/выход — fade + лёгкий подъём (совет «базовые анимации у всех наложений»).

Примеры:
  python helpers/text_behind.py still --frame edit/style/frame_wide.png \
      --text "СОСТОЯНИЕ" --size 190 --pos 540,760 --out edit/style/mock_D.png
  python helpers/text_behind.py clip --video sources/IMG_4509.mov --start 63.6 --duration 3.0 \
      --text "СОСТОЯНИЕ" --size 190 --pos 540,760 --out edit/animations/behind_state.mov
      [--vf "<та же геометрия, что у range в EDL>"] [--font <ttf>] [--color "#FFFFFF"] [--alpha 0.88]

Ограничения: маска «селфи»-модели держит человека в кадре целиком (голова, плечи, руки);
мелкие пряди и полупрозрачные края — через feather. На тёмном фоне с тёмной одеждой
качество ниже — проверяй кадрами. Модель работает на CPU, ~20–40 мс на кадр.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

W, H = 1080, 1920
FPS = 30
DEFAULT_FONT = "/Users/admin/Library/Fonts/Mont-Light.ttf"


# ---------- сегментация -----------------------------------------------------------

class PersonMask:
    """Обёртка над MediaPipe Selfie Segmentation. Возвращает soft-маску 0..1 (H×W)."""

    def __init__(self, feather: int = 3, threshold_soft: tuple[float, float] = (0.35, 0.75)):
        try:
            from mediapipe.python.solutions import selfie_segmentation as ss
        except Exception as e:  # noqa: BLE001
            sys.exit("Нужен mediapipe: `uv pip install --python .venv/bin/python mediapipe` "
                     f"(ошибка импорта: {e})")
        self._seg = ss.SelfieSegmentation(model_selection=1)
        self.feather = feather
        self.lo, self.hi = threshold_soft

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        res = self._seg.process(rgb)
        m = res.segmentation_mask.astype(np.float32)
        # растягиваем «серую» зону в 0..1, чтобы край был мягким, но уверенным
        m = np.clip((m - self.lo) / (self.hi - self.lo), 0.0, 1.0)
        if self.feather > 0:
            m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(self.feather)), dtype=np.float32) / 255.0
        return m

    def close(self):
        self._seg.close()


# ---------- текстовый слой -----------------------------------------------------------

def hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _draw_text(layer: Image.Image, text: str, f: ImageFont.FreeTypeFont, pos, fill, tracking: int,
               anchor: str) -> None:
    d = ImageDraw.Draw(layer)
    if tracking:
        widths = [f.getlength(ch) for ch in text]
        total = sum(widths) + tracking * (len(text) - 1)
        x = pos[0] - total / 2 if anchor[0] == "m" else pos[0]
        for ch, wch in zip(text, widths):
            d.text((x, pos[1]), ch, font=f, fill=fill, anchor="l" + anchor[1])
            x += wch + tracking
    else:
        d.text(pos, text, font=f, fill=fill, anchor=anchor)


def text_layer(text: str, font_path: str, size: int, pos: tuple[int, int],
               color: tuple[int, int, int], alpha: float, tracking: int = 0,
               anchor: str = "mm", shadow: float = 0.0) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """RGBA-слой с текстом (+ мягкая тень, если shadow>0) и bbox текста."""
    f = ImageFont.truetype(font_path, size)
    a = int(255 * alpha)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if shadow > 0:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _draw_text(sh, text, f, (pos[0], pos[1] + 6), (0, 0, 0, int(a * shadow)), tracking, anchor)
        sh = sh.filter(ImageFilter.GaussianBlur(12))
        layer.alpha_composite(sh)
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _draw_text(txt, text, f, pos, (*color, a), tracking, anchor)
    layer.alpha_composite(txt)
    bbox = txt.getbbox() or (0, 0, 0, 0)
    return layer, bbox


def compose_behind(frame_rgb: Image.Image, mask: np.ndarray, layer: Image.Image,
                   bbox: tuple[int, int, int, int], pad: int = 60) -> Image.Image:
    """Overlay-кадр RGBA: текст там, где нет человека, + человек в зоне текста."""
    tl = np.asarray(layer).astype(np.float32)
    m = mask[..., None]
    # текст гасим под человеком
    tl[..., 3] = tl[..., 3] * (1.0 - m[..., 0])
    # человек — только в расширенной зоне текста (страховка от рассинхрона с базой)
    zone = np.zeros((H, W), dtype=np.float32)
    x0, y0, x1, y1 = bbox
    zone[max(0, y0 - pad):min(H, y1 + pad), max(0, x0 - pad):min(W, x1 + pad)] = 1.0
    person_a = (m[..., 0] * zone * 255).astype(np.uint8)
    fr = np.asarray(frame_rgb.convert("RGB")).astype(np.uint8)
    person = np.dstack([fr, person_a])
    out = Image.alpha_composite(Image.fromarray(tl.astype(np.uint8), "RGBA"),
                                Image.fromarray(person, "RGBA"))
    return out


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


# ---------- режимы -----------------------------------------------------------------------

def run_still(args) -> None:
    frame = Image.open(args.frame).convert("RGB")
    if frame.size != (W, H):
        frame = frame.resize((W, H), Image.LANCZOS)
    pm = PersonMask(feather=args.feather)
    mask = pm(np.asarray(frame))
    pm.close()
    layer, bbox = text_layer(args.text, args.font, args.size, tuple(args.pos),
                             hex_to_rgb(args.color), args.alpha, args.tracking, shadow=args.shadow)
    over = compose_behind(frame, mask, layer, bbox)
    result = Image.alpha_composite(frame.convert("RGBA"), over)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    result.convert("RGB").save(args.out, quality=92)
    if args.mask_out:
        Image.fromarray((mask * 255).astype(np.uint8)).save(args.mask_out)
    print(f"✓ still → {args.out}  (bbox текста {bbox})")


def run_clip(args) -> None:
    dur = float(args.duration)
    n = max(2, int(round(dur * FPS)))
    tmp = Path(tempfile.mkdtemp(prefix="behind_"))
    try:
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        if args.vf:
            vf += "," + args.vf
        vf += f",fps={FPS}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{args.start:.3f}", "-i", args.video,
                        "-t", f"{dur:.3f}", "-vf", vf, str(tmp / "f_%05d.png")], check=True)
        frames = sorted(tmp.glob("f_*.png"))[:n]
        if not frames:
            sys.exit("ffmpeg не выдал кадров — проверь --video/--start")
        pm = PersonMask(feather=args.feather)
        out_dir = tmp / "out"
        out_dir.mkdir()
        base_pos = tuple(args.pos)
        fi, fo = int(args.fade * FPS), int(args.fade * FPS)
        for i, fp in enumerate(frames):
            frame = Image.open(fp).convert("RGB")
            mask = pm(np.asarray(frame))
            # вход: alpha 0→1 + подъём на 24px; выход: alpha 1→0
            k_in = ease_out_cubic(min(1.0, (i + 1) / max(1, fi))) if fi else 1.0
            left = len(frames) - 1 - i
            k_out = min(1.0, left / max(1, fo)) if fo else 1.0
            a = args.alpha * min(k_in, k_out)
            pos = (base_pos[0], int(base_pos[1] + 24 * (1 - k_in)))
            layer, bbox = text_layer(args.text, args.font, args.size, pos,
                                     hex_to_rgb(args.color), a, args.tracking, shadow=args.shadow)
            over = compose_behind(frame, mask, layer, bbox)
            over.save(out_dir / f"o_{i:05d}.png")
        pm.close()
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                        "-i", str(out_dir / "o_%05d.png"), "-c:v", "qtrle", "-pix_fmt", "argb",
                        args.out], check=True)
        print(f"✓ clip → {args.out}  ({len(frames)} кадров, {len(frames)/FPS:.2f} с)")
        print(f"  EDL: {{\"file\": \"{args.out}\", \"start_in_output\": <t>, "
              f"\"duration\": {len(frames)/FPS:.2f}, \"position\": \"topleft\"}}")
    finally:
        if not args.keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Текст за спиной (MediaPipe selfie segmentation)")
    sub = ap.add_subparsers(dest="mode", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--text", required=True)
    common.add_argument("--font", default=DEFAULT_FONT)
    common.add_argument("--size", type=int, default=180)
    common.add_argument("--pos", type=int, nargs=2, default=[540, 760], metavar=("X", "Y"),
                        help="центр текста (px) в кадре 1080×1920")
    common.add_argument("--color", default="#FFFFFF")
    common.add_argument("--alpha", type=float, default=0.88)
    common.add_argument("--tracking", type=int, default=0, help="доп. интервал между буквами, px")
    common.add_argument("--feather", type=int, default=3, help="мягкость края маски, px")
    common.add_argument("--shadow", type=float, default=0.0,
                        help="мягкая тень под текстом, 0..1 (0.5 — для светлых стен)")
    common.add_argument("--out", required=True)

    s = sub.add_parser("still", parents=[common])
    s.add_argument("--frame", required=True)
    s.add_argument("--mask-out", default=None)

    c = sub.add_parser("clip", parents=[common])
    c.add_argument("--video", required=True)
    c.add_argument("--start", type=float, required=True)
    c.add_argument("--duration", type=float, required=True)
    c.add_argument("--vf", default="", help="доп. фильтр геометрии как у range (crop/scale)")
    c.add_argument("--fade", type=float, default=0.25, help="вход/выход, с")
    c.add_argument("--keep-tmp", action="store_true")

    args = ap.parse_args()
    if args.mode == "still":
        run_still(args)
    else:
        run_clip(args)


if __name__ == "__main__":
    main()
