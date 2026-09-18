"""Дрейф звука превью относительно ожидаемой склейки по EDL (кросс-корреляция окнами).
python helpers/check_av_drift.py <edit>/preview.mp4 <edit>/edl.json  (источники резолвятся относительно папки EDL)
"""
import json, subprocess, sys
from pathlib import Path
import numpy as np

sr = 16000
prev_path, edl_path = Path(sys.argv[1]), Path(sys.argv[2])
edl = json.loads(edl_path.read_text())
edit_dir = edl_path.parent


def load(p):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(p), "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


srcs = {k: load(edit_dir / v if not Path(v).is_absolute() else v) for k, v in edl["sources"].items()}
prev = load(prev_path)
fps = int(edl.get("fps", 30))
parts = []
for r in edl["ranges"]:
    a = srcs[r["source"]]
    # render.py квантует длительность range'а до целых кадров (quantize_ranges_to_frames) —
    # ожидаемую склейку строим так же, иначе сумма округлений выглядит как дрейф
    n = max(1, int(round((r["end"] - r["start"]) * fps)))
    seg = a[int(r["start"] * sr):int(r["start"] * sr) + int(round(n / fps * sr))]
    parts.append(seg)
exp = np.concatenate(parts)
print(f"ожидаемо {len(exp)/sr:.3f}с  превью {len(prev)/sr:.3f}с")


def lag(t, half=1.0, search=0.8):
    a = exp[int((t - half) * sr):int((t + half) * sr)]
    b = prev[int(max(0, t - half - search) * sr):int((t + half + search) * sr)]
    if len(a) < sr or len(b) <= len(a):
        return None, 0
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    c = np.correlate(b, a, mode="valid")
    k = int(np.argmax(c))
    return (k / sr - min(search, t - half)), float(c[k] / len(a))


total = len(exp) / sr
ts = [t for t in range(3, int(total) - 2, 6)]
worst = 0.0
for t in ts:
    l, q = lag(t)
    if l is None:
        continue
    worst = max(worst, abs(l))
    print(f"t={t:3d}  lag={l:+.3f}s  corr={q:.2f}")
print(f"макс. |дрейф| = {worst:.3f}с")
