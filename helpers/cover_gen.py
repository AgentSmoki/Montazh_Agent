#!/usr/bin/env python3
"""Обложка рилса: картинка через polza.ai (GPT Image 2.5 и другие) + заголовок-хук поверх.

Зачем: у каждого ролика серии своя тематическая обложка в едином стиле (персонаж, сцена под тему
ролика, крупный заголовок 3–6 слов с одним акцентным словом). Выход — PNG 1080×1920 в safe-zone
вертикали, рядом «сырая» генерация без текста и manifest с промптом, моделью и ценой.

Использование (из корня Montazh_Agent, ключ POLZA_API_KEY — в .env или ~/.claude/env_secrets/polza.env):
    python helpers/cover_gen.py --style neurobro \
        --scene "Aang works a night shift in a marketplace warehouse ..." \
        --headline "Иди работать на Ozon" --accent Ozon \
        --out test_sessions/neurobro_1/edit/covers/cover_08_4509.png

    # только перенабрать заголовок на уже сгенерированной картинке (бесплатно):
    python helpers/cover_gen.py --from-image edit/covers/cover_08_4509.raw.png \
        --headline "Хочешь всё и сразу?" --accent сразу --out edit/covers/cover_08_4509.png

    # референсы стиля (загружаются в хранилище polza на 24 ч и идут в поле images):
    python helpers/cover_gen.py ... --ref refs/aang_1.jpg --ref refs/aang_2.jpg

    # клип для вставки в начало ролика (0.5 с, без звука, 1080×1920 30 fps):
    python helpers/cover_gen.py ... --clip 0.5

Модели polza.ai с параметрами aspect_ratio / image_resolution (список — GET /models):
    openai/gpt-image-2.5-sunburst (по умолчанию), gpt-image-2-5-flare, openai/gpt-5.4-image-2,
    google/gemini-3.1-flash-image, bytedance/seedream-4.5. Цена 2K ≈ 7 ₽, 1K ≈ 4 ₽ (2026-09).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import platform_paths as pp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "https://polza.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-image-2.5-sunburst"
W, H = 1080, 1920
SAFE_TOP = 240          # шапка площадки (время, кнопки)
SAFE_SIDE = 90          # отступ от краёв; справа колонка реакций — держим 120+
SAFE_RIGHT = 130
POLL_EVERY = 4
POLL_MAX = 420

# ---------------------------------------------------------------------------
# Стили серии: персонаж + подача + типографика заголовка.
# Промпт для модели — по-английски (image-модели держат его стабильнее), заголовок — по-русски.
# ---------------------------------------------------------------------------
STYLES: dict[str, dict] = {
    "neurobro": {
        "character": (
            "The character is Aang from Avatar: The Last Airbender, grown up into a young adult and "
            "living in the modern world as an office worker: bald head with the blue arrow tattoo, "
            "big friendly grey eyes, thin eyebrows, calm confident half-smile; lean build; he wears a "
            "plain oversized white T-shirt, relaxed light-blue jeans and clean white sneakers "
            "(the modern office-casual look). No monk robes, no staff, no glider."
        ),
        "look": (
            "Rendering: the character is drawn in clean 2D anime cel-shading with crisp dark line art "
            "and flat soft colours, composited into a photorealistic real-world environment with natural "
            "light and a warm muted palette — like an animated character living inside a photo. "
            "Eye-level or slightly high camera, medium or full shot, the face clearly visible and "
            "looking at the viewer or just past it. No text, no letters, no logos, no watermark, "
            "no speech bubbles anywhere in the image."
        ),
        "composition": (
            "Vertical 9:16 poster. The character occupies the middle and lower two thirds of the frame; "
            "the top third of the frame stays calm and uncluttered (plain wall, ceiling, sky or soft "
            "bokeh) because a large headline will be typeset there later. Props and background tell "
            "the topic of the scene at a glance; one strong visual idea per image, nothing busy."
        ),
        "headline": {
            "fonts": ["Mont-Heavy.ttf", "Mont-Black.ttf", "HelveticaNeue-Bold.otf", "Arial Bold.ttf"],
            "size": 118,
            "color": "#FFFFFF",
            "accent": "#3F7FE0",     # синий стрелы Аанга — один цвет акцента на серию
            "uppercase": True,
            "line_spacing": 1.06,
            "scrim": 0.42,           # затемнение верха под текст (0 — выключить)
        },
    },
    "none": {
        "character": "",
        "look": "No text, no letters, no logos, no watermark in the image.",
        "composition": "Vertical 9:16 poster; keep the top third calm for a headline.",
        "headline": {
            "fonts": ["HelveticaNeue-Bold.otf", "Arial Bold.ttf"],
            "size": 118, "color": "#FFFFFF", "accent": "#FFD23F", "uppercase": True,
            "line_spacing": 1.06, "scrim": 0.42,
        },
    },
}


# ---------------------------------------------------------------------------
# Ключ и HTTP
# ---------------------------------------------------------------------------
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def polza_credentials() -> tuple[str, str]:
    """POLZA_API_KEY / POLZA_API_BASE_URL: окружение → .env проекта → ~/.claude/env_secrets/polza.env."""
    _load_env_file(ROOT / ".env")
    _load_env_file(Path.home() / ".claude" / "env_secrets" / "polza.env")
    key = os.environ.get("POLZA_API_KEY")
    if not key:
        sys.exit("POLZA_API_KEY не найден: положи его в .env проекта или ~/.claude/env_secrets/polza.env")
    base = os.environ.get("POLZA_API_BASE_URL", DEFAULT_BASE).rstrip("/")
    return key, base


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def upload_ref(path: Path, key: str, base: str) -> str:
    """Загрузить референс в хранилище polza (TEMP_UPLOAD, 24 ч) → URL для поля images."""
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        path.suffix.lower().lstrip("."), "application/octet-stream")   # без явного mime polza видит text/plain
    with path.open("rb") as f:
        r = requests.post(f"{base}/storage/upload", headers=_headers(key),
                          files={"file": (path.name, f, mime)}, data={"storagePolicy": "TEMP_UPLOAD"}, timeout=120)
    if r.status_code not in (200, 201):
        sys.exit(f"upload {path.name}: HTTP {r.status_code} {r.text[:400]}")
    url = r.json().get("url")
    if not url:
        sys.exit(f"upload {path.name}: в ответе нет url: {r.text[:400]}")
    return url


def _extract_urls(data) -> list[str]:
    if isinstance(data, dict):
        if data.get("url"):
            return [data["url"]]
        if isinstance(data.get("urls"), list):
            return [u for u in data["urls"] if u]
        if isinstance(data.get("images"), list):
            return _extract_urls(data["images"])
        if isinstance(data.get("data"), (list, dict)):
            return _extract_urls(data["data"])
        return []
    if isinstance(data, list):
        out: list[str] = []
        for it in data:
            if isinstance(it, str):
                out.append(it)
            else:
                out.extend(_extract_urls(it))
        return out
    if isinstance(data, str):
        return [data]
    return []


def generate(prompt: str, *, model: str, aspect: str, resolution: str, refs: list[str],
             n: int, key: str, base: str, log=print) -> tuple[list[bytes], dict]:
    """POST /media (async) → poll GET /media/{id} → скачать картинки. Возвращает (bytes[], meta)."""
    inp: dict = {"prompt": prompt, "aspect_ratio": aspect, "image_resolution": resolution, "n": n}
    if refs:
        inp["images"] = refs
    r = requests.post(f"{base}/media", headers={**_headers(key), "Content-Type": "application/json"},
                      json={"model": model, "input": inp, "async": True}, timeout=180)
    if r.status_code != 200:
        sys.exit(f"polza /media: HTTP {r.status_code} {r.text[:600]}")
    job = r.json()
    gen_id = job.get("id")
    status = job.get("status")
    log(f"  polza {model}: id={gen_id} status={status}")
    t0 = time.time()
    while status not in ("completed", "failed", "cancelled"):
        if time.time() - t0 > POLL_MAX:
            sys.exit(f"polza: генерация {gen_id} не завершилась за {POLL_MAX} с")
        time.sleep(POLL_EVERY)
        s = requests.get(f"{base}/media/{gen_id}", headers=_headers(key), timeout=60)
        if s.status_code != 200:
            log(f"  poll HTTP {s.status_code}: {s.text[:200]}")
            continue
        job = s.json()
        status = job.get("status")
    if status != "completed":
        sys.exit(f"polza: статус {status}: {json.dumps(job.get('error'), ensure_ascii=False)[:600]}")
    urls = _extract_urls(job.get("data"))
    if not urls:
        sys.exit(f"polza: completed, но картинок нет: {json.dumps(job, ensure_ascii=False)[:600]}")
    images: list[bytes] = []
    for u in urls:
        d = requests.get(u, timeout=180)
        if d.status_code != 200:
            sys.exit(f"скачивание {u}: HTTP {d.status_code}")
        images.append(d.content)
    usage = job.get("usage") or {}
    meta = {"id": gen_id, "model": model, "urls": urls, "cost_rub": usage.get("cost_rub", usage.get("cost")),
            "seconds": round(time.time() - t0, 1)}
    log(f"  готово за {meta['seconds']} с, {meta['cost_rub']} ₽, картинок: {len(images)}")
    return images, meta


# ---------------------------------------------------------------------------
# Картинка: кроп под 1080×1920, затемнение верха, заголовок
# ---------------------------------------------------------------------------
def fit_cover(img: Image.Image) -> Image.Image:
    """Масштаб с заполнением 1080×1920 и центральный кроп (режем края, не верх/низ, где возможно)."""
    img = img.convert("RGB")
    sw, sh = img.size
    k = max(W / sw, H / sh)
    nw, nh = round(sw * k), round(sh * k)
    img = img.resize((nw, nh), Image.LANCZOS)
    x0 = (nw - W) // 2
    y0 = (nh - H) // 2
    return img.crop((x0, y0, x0 + W, y0 + H))


def add_scrim(img: Image.Image, strength: float, until_y: int = 760) -> Image.Image:
    """Мягкий градиент сверху: strength у верхнего края → 0 к until_y. Держит белый текст на светлом фоне."""
    if strength <= 0:
        return img
    base = img.convert("RGBA")
    grad = Image.new("L", (1, until_y))
    for y in range(until_y):
        t = y / max(1, until_y - 1)
        grad.putpixel((0, y), int(255 * strength * (1 - t) ** 1.4))
    mask = Image.new("L", (W, H), 0)
    mask.paste(grad.resize((W, until_y)), (0, 0))
    black = Image.new("RGBA", (W, H), (8, 10, 14, 255))
    return Image.composite(black, base, mask).convert("RGB")


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    p = pp.find_bold_sans(extra=paths)
    if p is None:
        sys.exit("Жирный sans-шрифт не найден (platform_paths.find_bold_sans)")
    return ImageFont.truetype(str(p), size)


def _norm(word: str) -> str:
    return re.sub(r"[^\w₽$€%]+", "", word, flags=re.UNICODE).lower()


def _line_w(words: list[str], font: ImageFont.FreeTypeFont) -> float:
    return font.getlength(" ".join(words))


def balanced_split(words: list[str], n: int, font: ImageFont.FreeTypeFont) -> list[list[str]]:
    """Разбить слова на n строк так, чтобы самая широкая строка была как можно уже (перебор границ)."""
    if n <= 1 or len(words) <= n:
        return [words] if n <= 1 else [[w] for w in words]
    best, best_w = None, float("inf")

    def rec(start: int, left: int, acc: list[list[str]]):
        nonlocal best, best_w
        if left == 1:
            cand = acc + [words[start:]]
            w = max(_line_w(ln, font) for ln in cand)
            if w < best_w:
                best, best_w = cand, w
            return
        for end in range(start + 1, len(words) - left + 2):
            rec(end, left - 1, acc + [words[start:end]])

    rec(0, n, [])
    return best or [words]


def wrap_lines(words: list[str], font: ImageFont.FreeTypeFont, max_w: int) -> list[list[str]] | None:
    """Наименьшее число строк (до 3), при котором сбалансированная разбивка влезает; None — не влезает."""
    for n in (1, 2, 3):
        lines = balanced_split(words, n, font)
        if max(_line_w(ln, font) for ln in lines) <= max_w:
            return lines
    return None


def draw_headline(img: Image.Image, text: str, accent_words: list[str], spec: dict, *,
                  size: int | None = None, place: str = "top", y_top: int | None = None) -> Image.Image:
    """Заголовок по строкам (ручной перенос — «|» или перевод строки), акцентные слова цветом, мягкая тень."""
    size = size or spec["size"]
    uppercase = spec.get("uppercase", True)
    text = text.replace("\\n", "\n")
    manual = [ln.strip() for ln in re.split(r"[|\n]", text) if ln.strip()]
    max_w = W - SAFE_SIDE - SAFE_RIGHT
    accents = {_norm(a) for a in accent_words if _norm(a)}

    # подбор кегля: ручные строки — уменьшаем, пока самая широкая не влезет (минимум 0.72×);
    # авторазбивка — до 3 сбалансированных строк, кегль вниз только если и 3 строки не влезают
    src_words = [w.upper() if uppercase else w for w in (manual[0].split() if manual else text.split())]
    while True:
        font = _font(spec["fonts"], size)
        if len(manual) > 1:
            lines = [[w.upper() if uppercase else w for w in ln.split()] for ln in manual]
            fits = max(_line_w(ln, font) for ln in lines) <= max_w
        else:
            wrapped = wrap_lines(src_words, font, max_w)
            fits = wrapped is not None
            lines = wrapped or balanced_split(src_words, 3, font)
        if fits or size <= int(spec["size"] * 0.72):
            break
        size -= 6

    line_h = int(size * spec.get("line_spacing", 1.06))
    block_h = line_h * len(lines)
    if y_top is None:
        y_top = SAFE_TOP + 40 if place == "top" else int(H * 0.72) - block_h - 40

    base = img.convert("RGBA")
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td, sd = ImageDraw.Draw(text_layer), ImageDraw.Draw(shadow_layer)
    space_w = font.getlength(" ")
    for i, ln in enumerate(lines):
        words = list(ln)
        widths = [font.getlength(w) for w in words]
        total = sum(widths) + space_w * (len(words) - 1)
        x = (W - SAFE_RIGHT + SAFE_SIDE) / 2 - total / 2   # центр между safe-полями
        y = y_top + i * line_h
        for w, ww in zip(words, widths):
            color = spec["accent"] if _norm(w) in accents else spec["color"]
            sd.text((x + 3, y + 8), w, font=font, fill=(0, 0, 0, 215))
            td.text((x, y), w, font=font, fill=color, stroke_width=2, stroke_fill=(18, 18, 22, 200))
            x += ww + space_w
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(14))
    out = Image.alpha_composite(base, shadow_layer)
    out = Image.alpha_composite(out, text_layer)
    return out.convert("RGB")


# ---------------------------------------------------------------------------
# Клип для начала ролика
# ---------------------------------------------------------------------------
def make_clip(png: Path, seconds: float, fps: int = 30) -> Path:
    out = png.with_suffix(".mp4")
    cmd = [pp.ffmpeg_bin(), "-y", "-loop", "1", "-framerate", str(fps), "-i", str(png),
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-t", f"{seconds:.3f}", "-r", str(fps), "-pix_fmt", "yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "aac", "-b:a", "128k",
           "-shortest", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg клип упал: {r.stderr[-800:]}")
    return out


# ---------------------------------------------------------------------------
def build_prompt(style: dict, scene: str, extra: str = "") -> str:
    parts = [style["character"], "Scene: " + scene.strip(), style["look"], style["composition"]]
    if extra:
        parts.append(extra.strip())
    return "\n\n".join(p for p in parts if p)


def main() -> None:
    ap = argparse.ArgumentParser(description="Обложка рилса: генерация через polza.ai + заголовок-хук")
    ap.add_argument("--style", default="neurobro", choices=sorted(STYLES))
    ap.add_argument("--scene", help="сцена под тему ролика (по-английски, 1–4 предложения)")
    ap.add_argument("--extra", default="", help="дополнение к промпту (шутка, реквизит, настроение)")
    ap.add_argument("--headline", default="", help="заголовок 3–6 слов; «|» — ручной перенос строки")
    ap.add_argument("--accent", action="append", default=[], help="акцентное слово (можно несколько раз)")
    ap.add_argument("--headline-size", type=int, default=None)
    ap.add_argument("--place", default="top", choices=["top", "bottom"])
    ap.add_argument("--no-scrim", action="store_true", help="без затемнения верха под текст")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--resolution", default="2K", choices=["1K", "2K", "4K"])
    ap.add_argument("--n", type=int, default=1, help="вариантов за запрос (1–4); файлы получат суффикс _v2, _v3")
    ap.add_argument("--ref", action="append", default=[], help="референс стиля (файл) → поле images")
    ap.add_argument("--from-image", help="пропустить генерацию, взять готовую картинку")
    ap.add_argument("--clip", type=float, default=0.0, help="сделать mp4-клип такой длины рядом с PNG")
    ap.add_argument("--dry-run", action="store_true", help="показать промпт и выйти")
    ap.add_argument("--out", required=True, help="PNG 1080×1920 (например edit/covers/cover_08_4509.png)")
    a = ap.parse_args()

    style = STYLES[a.style]
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"created": datetime.now().isoformat(timespec="seconds"), "style": a.style,
                      "headline": a.headline, "accent": a.accent, "out": str(out)}

    raws: list[Path] = []
    if a.from_image:
        raws = [Path(a.from_image).resolve()]
        manifest["from_image"] = str(raws[0])
    else:
        if not a.scene:
            sys.exit("--scene обязателен (или --from-image для перенабора заголовка)")
        prompt = build_prompt(style, a.scene, a.extra)
        manifest.update({"model": a.model, "aspect": a.aspect, "resolution": a.resolution,
                         "scene": a.scene, "prompt": prompt})
        if a.dry_run:
            print(prompt)
            return
        key, base = polza_credentials()
        ref_urls: list[str] = []
        for r in a.ref:
            p = Path(r).resolve()
            if not p.exists():
                sys.exit(f"нет референса: {p}")
            u = upload_ref(p, key, base)
            ref_urls.append(u)
            print(f"  референс {p.name} → {u}")
        manifest["refs"] = [{"file": r, "url": u} for r, u in zip(a.ref, ref_urls)]
        images, meta = generate(prompt, model=a.model, aspect=a.aspect, resolution=a.resolution,
                                refs=ref_urls, n=max(1, min(4, a.n)), key=key, base=base)
        manifest["generation"] = meta
        for i, blob in enumerate(images):
            raw = out.with_name(out.stem + (f"_v{i + 1}" if i else "") + ".raw.png")
            Image.open(io.BytesIO(blob)).convert("RGB").save(raw, "PNG")
            raws.append(raw)

    outputs: list[Path] = []
    for i, raw in enumerate(raws):
        img = fit_cover(Image.open(raw))
        if a.headline:
            hs = style["headline"]
            if not a.no_scrim:
                img = add_scrim(img, hs.get("scrim", 0.4))
            img = draw_headline(img, a.headline, a.accent, hs, size=a.headline_size, place=a.place)
        dst = out if i == 0 else out.with_name(f"{out.stem}_v{i + 1}{out.suffix}")
        img.save(dst, "PNG", optimize=True)
        outputs.append(dst)
        if a.clip > 0:
            print(f"  клип → {make_clip(dst, a.clip)}")
    manifest["raw"] = [str(p) for p in raws]
    manifest["outputs"] = [str(p) for p in outputs]
    manifest["sha256"] = hashlib.sha256(outputs[0].read_bytes()).hexdigest()
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("cover →", " ".join(str(p) for p in outputs))


if __name__ == "__main__":
    main()
