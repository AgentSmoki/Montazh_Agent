"""SRT (output-timeline) → ASS «у головы» (пресет beside_head, профиль NeuroBRO).

Идея: субтитры мелкие, без обводки, лежат в свободной зоне рядом с лицом — справа,
если лицо в левой половине кадра, и слева, если в правой. Высота — на уровне глаз.
Мягкая тень — отдельным слоем с \\blur (у libass нет размытой тени без обводки).
Одно слово во фразе можно подсветить акцентным цветом.

Положение лица берём из базового видео (после concat) через MediaPipe Face Detection
на середине каждой реплики. Сторона держится с гистерезисом, чтобы текст не прыгал.
Если свободной зоны нет (лицо во весь кадр) — fallback: тёмный текст на футболке
внизу по центру.

Usage (обычно зовётся из render.py при "subtitle_preset": "beside_head"):
    python helpers/ass_subs.py <base.mp4> <master.srt> -o <master.ass> \\
        [--font "Helvetica Neue"] [--font-file ~/Library/Fonts/HelveticaNeue-Roman.otf] \\
        [--size 44] [--accent "500,000,стартап"] [--accent-color D97757]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 1080, 1920
MARGIN = 40          # от края кадра
GAP = 34             # зазор между лицом и текстом
MIN_ZONE = 230       # уже — не влезет даже короткая строка → fallback
MAX_LINES = 4
Y_MIN, Y_MAX = int(H * 0.22), int(H * 0.52)
BEARD_PX = 130       # запас под бороду ниже рамки лица (режим place='chest')


# ---------- SRT -------------------------------------------------------------------------

def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    def ts(s: str) -> float:
        h, m, rest = s.strip().replace(".", ",").split(":")
        sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0
    cues = []
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        tl = next((l for l in lines if "-->" in l), None)
        if not tl:
            continue
        a, b = tl.split("-->")
        text = " ".join(l for l in lines[lines.index(tl) + 1:]).strip()
        if text:
            cues.append((ts(a), ts(b), text))
    return cues


def ass_ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ---------- лицо ------------------------------------------------------------------------

class FaceFinder:
    def __init__(self, video: Path):
        self.video = video
        self._seg = None
        try:
            from mediapipe.python.solutions import face_detection as fd
            from mediapipe.python.solutions import selfie_segmentation as ss
            self._fd = fd.FaceDetection(model_selection=0, min_detection_confidence=0.5)
            self._seg = ss.SelfieSegmentation(model_selection=1)
        except Exception as e:  # noqa: BLE001
            print(f"warning: mediapipe недоступен ({e}) — лицо считаем по центру", file=sys.stderr)
            self._fd = None
        self._tmp = Path(tempfile.mkdtemp(prefix="ass_face_"))
        self.head_top: float | None = None   # верх головы (с кепкой) в долях кадра, после bbox()
        self._fps: float | None = None
        self._cache: dict[int, Path] = {}    # номер кадра → jpg, заполняет prefetch()

    def prefetch(self, times: list[float]) -> None:
        """Достать кадры для всех моментов одним проходом ffmpeg (select по номерам кадров).

        Без этого bbox() запускает ffmpeg с -ss на каждую реплику: полсотни процессов,
        и каждый декодирует видео от ближайшего ключевого кадра (до 8 с). Один проход
        декодирует ролик один раз. Номер кадра — первый кадр с pts ≥ t, тот же, что
        отдаёт точный -ss. Видео с переменной частотой кадров — старый путь.
        """
        if self._fd is None or not times:
            return
        fps = _cfr_fps(self.video)
        if not fps:
            return
        idx = sorted({math.ceil(t * fps - 1e-6) for t in times if t >= 0})
        expr = "+".join(f"eq(n\\,{n})" for n in idx)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(self.video),
                        "-vf", f"select='{expr}',scale=540:-2", "-vsync", "vfr", "-q:v", "4",
                        str(self._tmp / "pf_%05d.jpg")],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        files = sorted(self._tmp.glob("pf_*.jpg"))
        if len(files) != len(idx):
            # часть кадров не извлеклась — сопоставление номеров ненадёжно, остаёмся на -ss
            for f in files:
                f.unlink(missing_ok=True)
            return
        self._fps = fps
        self._cache = dict(zip(idx, files))

    def bbox(self, t: float) -> tuple[float, float, float, float] | None:
        """(x0, y0, x1, y1) лица в долях кадра или None. Побочно: self.head_top —
        верхняя точка силуэта человека (кепка включена) по маске сегментации."""
        self.head_top = None
        if self._fd is None:
            return None
        fp = self._cache.get(math.ceil(t * self._fps - 1e-6)) if self._fps else None
        if fp is None:
            fp = self._tmp / f"f_{t:.2f}.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(self.video),
                            "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(fp)],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not fp.exists():
            return None
        import numpy as np
        from PIL import Image
        img = np.asarray(Image.open(fp).convert("RGB"))
        if self._seg is not None:
            try:
                m = self._seg.process(img).segmentation_mask
                rows = np.where((m > 0.5).any(axis=1))[0]
                if len(rows):
                    self.head_top = float(rows[0]) / m.shape[0]
            except Exception:
                self.head_top = None
        res = self._fd.process(img)
        if not res.detections:
            return None
        d = max(res.detections, key=lambda d: d.location_data.relative_bounding_box.width)
        b = d.location_data.relative_bounding_box
        return (max(0.0, b.xmin), max(0.0, b.ymin),
                min(1.0, b.xmin + b.width), min(1.0, b.ymin + b.height))

    def close(self):
        import shutil
        if self._fd is not None:
            self._fd.close()
        if self._seg is not None:
            self._seg.close()
        shutil.rmtree(self._tmp, ignore_errors=True)


def _cfr_fps(video: Path) -> float | None:
    """Частота кадров, если она постоянная (r_frame_rate == avg_frame_rate), иначе None."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=r_frame_rate,avg_frame_rate",
                              "-of", "default=nw=1:nk=1", str(video)],
                             capture_output=True, text=True, check=True).stdout.split()
        rates = [float(n) / float(d) for n, d in (r.split("/") for r in out[:2])]
        return rates[0] if len(rates) == 2 and rates[0] > 0 and abs(rates[0] - rates[1]) < 1e-3 else None
    except Exception:
        return None


# ---------- перенос строк по ширине ------------------------------------------------------------

def make_measure(font_file: str | None, size: int):
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(font_file, size) if font_file else None
    except Exception:
        f = None
    if f is None:
        return lambda s: len(s) * size * 0.55
    return lambda s: f.getlength(s)


def _merge_numbers(words: list[str]) -> list[str]:
    """«500 000.» — группы цифр склеиваем неразрывным пробелом, чтобы не рвать между строками."""
    out: list[str] = []
    for w in words:
        core = w.strip(".,!?;:«»\"—-()")
        prev = out[-1].strip(".,!?;:«»\"—-() ") if out else ""
        if out and core.isdigit() and prev.replace(" ", "").isdigit() and not out[-1][-1] in ".,!?;:":
            out[-1] = out[-1] + " " + w
        else:
            out.append(w)
    return out


def wrap_words(words: list[str], max_w: float, measure) -> list[str]:
    words = _merge_numbers(words)
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and measure(trial) > max_w:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


# ---------- сборка -------------------------------------------------------------------------

def _ass_color(hex6: str) -> str:
    """'D97757' → '&H005777D9&' (ASS = &HAABBGGRR)."""
    h = hex6.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def build_subs(base_video: Path, srt_path: Path, out_ass: Path, preset: str = "beside_head",
               font: str = "Helvetica Neue", font_file: str | None = None, size: int = 44,
               accent: list[str] | None = None, accent_color: str | None = None,
               accent_font: str | None = None, accent_size: int | None = None,
               corner_y: float = 0.80, force_windows: list | None = None,
               italic: bool = False, allow_top: bool = False, stable_y: bool = True,
               side: str | None = None, place: str = "head", chest_y: int = 1520,
               chest_color: str = "dark", verbose: bool = True) -> Path:
    """Пресеты:
      beside_head — белый у головы в свободной зоне (сторона/высота по лицу), мягкая тень.
      corner_dark — тёмный, в правом нижнем углу (просьба Богдана: не лезть на шею).
    Акцент (слово из `accent` или число): `accent_color` (hex) и/или `accent_font`
    (например «Pixelify Sans» или «PT Mono»), `accent_size` — кегль акцента.
    force_windows — [(t0, t1, 'bottom'|'corner')] принудительная позиция в окнах врезок
    (только для beside_head). italic — основной стиль курсивом (напр. Georgia Italic),
    акцентное слово тогда рисуется прямым (\\i0).
    side — 'right'|'left': сторона зафиксирована (Богдан 2026-09-08: «субтитры бегают
    справа-налево»), при нехватке места — кегль ×0.8, потом угол с той же стороны.
    place — 'head' (у головы) | 'chest' (на футболке под подбородком: по центру,
    `chest_y` — верх блока, `chest_color` 'dark' — графит без тени | 'white' — белый с плотной тенью).
    """
    global _ITALIC
    _ITALIC = 1 if italic else 0
    if preset == "corner_dark":
        return build_corner_dark(base_video, srt_path, out_ass, font=font, font_file=font_file,
                                 size=size, accent=accent, accent_color=accent_color,
                                 accent_font=accent_font, accent_size=accent_size,
                                 corner_y=corner_y, verbose=verbose)
    return build_beside_head(base_video, srt_path, out_ass, font=font, font_file=font_file,
                             size=size, accent=accent, accent_color=accent_color,
                             accent_font=accent_font, accent_size=accent_size,
                             force_windows=force_windows, allow_top=allow_top,
                             stable_y=stable_y, side=side, place=place, chest_y=chest_y,
                             chest_color=chest_color, verbose=verbose)


def _accent_tags(accent_color: str | None, accent_font: str | None, accent_size: int | None) -> str:
    tags = ""
    if accent_font:
        tags += f"\\fn{accent_font}"
        if _ITALIC:
            tags += "\\i0"   # акцентное слово прямым, даже если основной стиль курсив
    if accent_size:
        tags += f"\\fs{accent_size}"
    if accent_color:
        tags += f"\\c{_ass_color(accent_color)}"
    return tags


def _make_deco(accent_set: set[str], tags: str):
    def deco(w: str) -> str:
        core = w.strip(".,!?;:«»\"—-()").lower()
        is_num = bool(core) and (core.isdigit() or bool(re.fullmatch(r"[\d\s]+\d", core)))
        if tags and core and (core in accent_set or is_num):
            return f"{{{tags}}}{w}{{\\r}}"
        return w
    return deco


def build_corner_dark(base_video: Path, srt_path: Path, out_ass: Path,
                      font: str = "Helvetica Neue", font_file: str | None = None, size: int = 44,
                      accent: list[str] | None = None, accent_color: str | None = None,
                      accent_font: str | None = None, accent_size: int | None = None,
                      corner_y: float = 0.80, verbose: bool = True) -> Path:
    """Тёмный текст в правом нижнем углу: \\an3 (правый-нижний якорь), до 3 строк."""
    cues = parse_srt(srt_path)
    measure = make_measure(font_file, size)
    accent_set = {a.lower().strip() for a in (accent or []) if a.strip()}
    deco = _make_deco(accent_set, _accent_tags(accent_color, accent_font, accent_size))
    header = _header(font, size)
    events: list[str] = []
    x, y = W - 60, int(H * corner_y)
    for (t0, t1, text) in cues:
        lines = wrap_words(text.split(), W * 0.55, measure)[:3]
        txt = "\\N".join(" ".join(deco(w) for w in ln.split()) for ln in lines)
        plain = "\\N".join(lines)
        events.append(f"Dialogue: 0,{ass_ts(t0)},{ass_ts(t1)},SubDarkGlow,,0,0,0,,"
                      f"{{\\an3\\pos({x},{y})\\blur10}}{plain}")
        events.append(f"Dialogue: 1,{ass_ts(t0)},{ass_ts(t1)},SubDark,,0,0,0,,"
                      f"{{\\an3\\pos({x},{y})}}{txt}")
    out_ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    if verbose:
        print(f"ass_subs: {len(cues)} cues → {out_ass.name} (пресет corner_dark, {font} {size}px, "
              f"угол x={x} y={y})")
    return out_ass


_ITALIC = 0  # выставляется build_subs(italic=True) → 1; читается _header/_accent_tags


def _header(font: str, size: int) -> str:
    it = _ITALIC
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,{it},0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: SubShadow,{font},{size},&H66000000,&H00FFFFFF,&H00000000,&H00000000,0,{it},0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: SubDark,{font},{size},&H00221E1E,&H00FFFFFF,&H00000000,&H00000000,0,{it},0,0,100,100,0,0,1,0,0,2,0,0,0,1
Style: SubDarkGlow,{font},{size},&H55FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,{it},0,0,100,100,0,0,1,0,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_beside_head(base_video: Path, srt_path: Path, out_ass: Path,
                      font: str = "Helvetica Neue", font_file: str | None = None,
                      size: int = 44, accent: list[str] | None = None,
                      accent_color: str | None = None, accent_font: str | None = None,
                      accent_size: int | None = None,
                      force_windows: list[tuple[float, float, str]] | None = None,
                      allow_top: bool = False, stable_y: bool = True,
                      side: str | None = None, place: str = "head", chest_y: int = 1520,
                      chest_color: str = "dark", verbose: bool = True) -> Path:
    """force_windows: [(t0, t1, mode)] — окна, где позиция задаётся принудительно
    (mode 'bottom' — белым внизу по центру, напр. поверх полнокадровой врезки;
    'corner' — тёмным в правом нижнем углу). Реплика попадает в окно, если
    пересекается с ним больше чем наполовину."""
    cues = parse_srt(srt_path)
    finder = FaceFinder(base_video)
    measure = make_measure(font_file, size)
    accent_set = {a.lower().strip() for a in (accent or []) if a.strip()}
    deco = _make_deco(accent_set, _accent_tags(accent_color, accent_font, accent_size))
    force_windows = force_windows or []

    def forced_mode(t0: float, t1: float) -> str | None:
        for (w0, w1, mode) in force_windows:
            ov = min(t1, w1) - max(t0, w0)
            if ov > 0 and ov >= 0.5 * (t1 - t0):
                return mode
        return None

    header = _header(font, size)
    events: list[str] = []
    side_fixed = side if side in ("right", "left") else None
    prev_side = side_fixed or "right"
    prev_y: int | None = None
    log: list[str] = []
    small = int(size * 0.8)
    measure_s = make_measure(font_file, small)
    # кадры для всех реплик одним проходом; середины считаются так же, как в цикле ниже
    mids = []
    for idx, (t0, t1, _text) in enumerate(cues):
        if idx + 1 < len(cues):
            t1 = min(cues[idx + 1][0] - 0.02, t1 + 0.35)
        mids.append((t0 + t1) / 2)
    finder.prefetch(mids)
    # динамика: кусок держится до следующего (не дольше +0.35 с), вход/выход fade
    FAD = "\\fad(80,60)"
    for idx, (t0, t1, text) in enumerate(cues):
        if idx + 1 < len(cues):
            t1 = min(cues[idx + 1][0] - 0.02, t1 + 0.35)
        mode = forced_mode(t0, t1)
        if place == "chest" and mode is None:
            # На футболке под подбородком: одно место на весь ролик, по центру, до 2 строк.
            # Если подбородок в этом куске ниже chest_y — блок опускаем под него.
            words = text.split()
            lines = wrap_words(words, int(W * 0.72), measure)
            fs_tag = ""
            if len(lines) > 2:
                lines = wrap_words(words, int(W * 0.72), measure_s)[:2]
                fs_tag = f"\\fs{small}"
            txt = "\\N".join(" ".join(deco(w) for w in ln.split(" ")) for ln in lines)
            plain = "\\N".join(lines)
            bb = finder.bbox((t0 + t1) / 2)
            y = chest_y
            # рамка лица MediaPipe кончается на подбородке, борода ниже ещё на ~120 px;
            # при наклоне головы опускаем блок под бороду, но не ниже 86 % высоты
            if bb is not None and bb[3] * H + BEARD_PX > y:
                y = int(min(bb[3] * H + BEARD_PX, H * 0.86))
            x = W // 2
            if chest_color == "white":
                events.append(f"Dialogue: 0,{ass_ts(t0)},{ass_ts(t1)},SubShadow,,0,0,0,,"
                              f"{{\\an8\\pos({x + 2},{y + 5}){fs_tag}\\alpha&H22&\\blur12{FAD}}}{plain}")
                events.append(f"Dialogue: 1,{ass_ts(t0)},{ass_ts(t1)},Sub,,0,0,0,,"
                              f"{{\\an8\\pos({x},{y}){fs_tag}{FAD}}}{txt}")
            else:
                events.append(f"Dialogue: 0,{ass_ts(t0)},{ass_ts(t1)},SubDarkGlow,,0,0,0,,"
                              f"{{\\an8\\pos({x},{y}){fs_tag}\\blur10{FAD}}}{plain}")
                events.append(f"Dialogue: 1,{ass_ts(t0)},{ass_ts(t1)},SubDark,,0,0,0,,"
                              f"{{\\an8\\pos({x},{y}){fs_tag}{FAD}}}{txt}")
            log.append(f"  [{t0:6.2f}-{t1:6.2f}] CHEST-{chest_color} y={y} lines={len(lines)}"
                       f"{' small' if fs_tag else ''} | {text[:40]}")
            continue
        if mode == "bottom":
            lines = wrap_words(text.split(), W - 2 * MARGIN - 120, measure)[:2]
            txt = "\\N".join(" ".join(deco(w) for w in ln.split(" ")) for ln in lines)
            plain = "\\N".join(lines)
            y = int(H * 0.965)
            events.append(f"Dialogue: 0,{ass_ts(t0)},{ass_ts(t1)},SubShadow,,0,0,0,,"
                          f"{{\\an2\\pos({W // 2 + 2},{y + 4})\\blur9{FAD}}}{plain}")
            events.append(f"Dialogue: 1,{ass_ts(t0)},{ass_ts(t1)},Sub,,0,0,0,,"
                          f"{{\\an2\\pos({W // 2},{y}){FAD}}}{txt}")
            log.append(f"  [{t0:6.2f}-{t1:6.2f}] BOTTOM (forced) | {text[:40]}")
            continue
        mid = (t0 + t1) / 2
        bb = finder.bbox(mid)
        if bb is None:
            fx0, fy0, fx1, fy1 = 0.28, 0.12, 0.72, 0.55
        else:
            fx0, fy0, fx1, fy1 = bb
        fcx = (fx0 + fx1) / 2
        zone_right = W - MARGIN - (fx1 * W + GAP)
        zone_left = fx0 * W - GAP - MARGIN
        if side_fixed:
            # сторона зафиксирована: никаких переключений, при нехватке места — кегль ×0.8,
            # затем угол с той же стороны
            side = side_fixed
            zone = zone_right if side == "right" else zone_left
            other = -1.0
        else:
            # сторона с гистерезисом: держим прежнюю, пока лицо близко к центру
            if fcx < 0.46:
                side = "right"
            elif fcx > 0.54:
                side = "left"
            else:
                side = prev_side
            zone = zone_right if side == "right" else zone_left
            # если выбранная сторона узкая, а другая заметно шире — переключаемся
            other = zone_left if side == "right" else zone_right
            if zone < MIN_ZONE and other > zone * 1.5:
                side = "left" if side == "right" else "right"
                zone = other
        prev_side = side

        words = text.split()
        # порог зоны — по самому длинному слову куска (динамические куски короткие),
        # но не меньше 150 px; так короткие реплики остаются у головы, а не прыгают в угол
        longest = max((measure(w) for w in _merge_numbers(words)), default=0.0)
        need = max(150.0, longest + 10)
        if zone < need and other >= need and other > zone:
            side = "left" if side == "right" else "right"
            zone = other
            prev_side = side
        # если и так не влезает — пробуем кегль 0.8× (короткое слово у головы лучше угла)
        fs_tag = ""
        if zone < need:
            longest_s = max((measure_s(w) for w in _merge_numbers(words)), default=0.0)
            if zone >= max(140.0, longest_s + 8):
                need = max(140.0, longest_s + 8)
                fs_tag = f"\\fs{small}"
        if zone >= need:
            # не режем текст: если строк больше MAX_LINES — уменьшаем кегль и переносим заново
            lines = wrap_words(words, zone, measure_s if fs_tag else measure)
            if len(lines) > MAX_LINES and not fs_tag:
                lines = wrap_words(words, zone, measure_s)
                fs_tag = f"\\fs{small}"
            y = int(min(max((fy0 + fy1) / 2 * H, Y_MIN), Y_MAX))
            # стабильная высота: держим прежнюю, пока лицо не ушло дальше 140 px
            if stable_y and prev_y is not None and abs(y - prev_y) < 140:
                y = prev_y
            prev_y = y
            if side == "right":
                x = W - MARGIN; an = 6
            else:
                x = MARGIN; an = 4
            txt = "\\N".join(" ".join(deco(w) for w in ln.split(" ")) for ln in lines)
            plain = "\\N".join(lines)
            events.append(f"Dialogue: 0,{ass_ts(t0)},{ass_ts(t1)},SubShadow,,0,0,0,,"
                          f"{{\\an{an}\\pos({x + 2},{y + 4}){fs_tag}\\blur9{FAD}}}{plain}")
            events.append(f"Dialogue: 1,{ass_ts(t0)},{ass_ts(t1)},Sub,,0,0,0,,"
                          f"{{\\an{an}\\pos({x},{y}){fs_tag}{FAD}}}{txt}")
            log.append(f"  [{t0:6.2f}-{t1:6.2f}] {side:5s} zone={zone:4.0f} y={y:4d} "
                       f"lines={len(lines)}{' small' if fs_tag else ''} | {text[:40]}")
        elif allow_top and (finder.head_top if finder.head_top is not None else fy0 - 0.12) * H >= 150:
            # запас №2 (выключен по умолчанию — Богдан: «над кепкой слишком далеко, субтитры
            # должны быть примерно в одном месте»): НАД головой, белым на стене, по центру.
            # Верх головы — из маски силуэта (кепка включена), не из рамки лица.
            top_zone = (finder.head_top if finder.head_top is not None else fy0 - 0.12) * H
            lines = wrap_words(words, W - 2 * MARGIN, measure_s if top_zone < 220 else measure)[:2]
            fs_top = f"\\fs{small}" if top_zone < 220 else ""
            txt = "\\N".join(" ".join(deco(w) for w in ln.split(" ")) for ln in lines)
            plain = "\\N".join(lines)
            y = int(max(70, top_zone - 36))
            events.append(f"Dialogue: 0,{ass_ts(t0)},{ass_ts(t1)},SubShadow,,0,0,0,,"
                          f"{{\\an2\\pos({W // 2 + 2},{y + 4}){fs_top}\\blur9{FAD}}}{plain}")
            events.append(f"Dialogue: 1,{ass_ts(t0)},{ass_ts(t1)},Sub,,0,0,0,,"
                          f"{{\\an2\\pos({W // 2},{y}){fs_top}{FAD}}}{txt}")
            log.append(f"  [{t0:6.2f}-{t1:6.2f}] TOP (zone {zone:.0f}, над головой {top_zone:.0f}px) | {text[:40]}")
        else:
            # запас №3 (ни сбоку, ни сверху): БЕЛЫМ с тенью в правом нижнем углу.
            # Тёмный угол (corner_dark) — отдельный пресет, в этой серии не используется.
            lines = wrap_words(words, W * 0.55, measure)[:3]
            txt = "\\N".join(" ".join(deco(w) for w in ln.split(" ")) for ln in lines)
            plain = "\\N".join(lines)
            # угол — с той же стороны, что и основная позиция (при side='left' — левый нижний)
            if side == "left":
                x, y, an = 60, int(H * 0.86), 1
            else:
                x, y, an = W - 60, int(H * 0.86), 3
            # на белой футболке тень плотнее (\alpha&H22& ≈ 87 %), иначе белое на белом тонет
            events.append(f"Dialogue: 0,{ass_ts(t0)},{ass_ts(t1)},SubShadow,,0,0,0,,"
                          f"{{\\an{an}\\pos({x + 2},{y + 5})\\alpha&H22&\\blur12{FAD}}}{plain}")
            events.append(f"Dialogue: 1,{ass_ts(t0)},{ass_ts(t1)},Sub,,0,0,0,,"
                          f"{{\\an{an}\\pos({x},{y}){FAD}}}{txt}")
            log.append(f"  [{t0:6.2f}-{t1:6.2f}] CORNER-white-{side} (zone {zone:.0f}) | {text[:40]}")
    finder.close()
    out_ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    if verbose:
        print(f"ass_subs: {len(cues)} cues → {out_ass.name} (пресет beside_head, {font} {size}px)")
        for ln in log:
            print(ln)
    return out_ass


def main() -> None:
    ap = argparse.ArgumentParser(description="SRT → ASS «у головы»")
    ap.add_argument("base_video", type=Path)
    ap.add_argument("srt", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--preset", default="beside_head", choices=["beside_head", "corner_dark"])
    ap.add_argument("--font", default="Helvetica Neue")
    ap.add_argument("--font-file", default=None, help="ttf/otf для измерения ширины строк")
    ap.add_argument("--size", type=int, default=44)
    ap.add_argument("--accent", default="", help="слова через запятую, подсветить акцентом")
    ap.add_argument("--accent-color", default=None, help="hex, напр. 000000")
    ap.add_argument("--accent-font", default=None, help="напр. 'Pixelify Sans' или 'PT Mono'")
    ap.add_argument("--accent-size", type=int, default=None)
    args = ap.parse_args()
    build_subs(args.base_video, args.srt, args.out, preset=args.preset, font=args.font,
               font_file=args.font_file, size=args.size,
               accent=[a for a in args.accent.split(",") if a],
               accent_color=args.accent_color, accent_font=args.accent_font,
               accent_size=args.accent_size)


if __name__ == "__main__":
    main()
