"""Кадры превью на стыках (±0.12 с) и в точках субтитров → листы для просмотра.
python helpers/verify_sheets.py <edit>/preview.mp4 <edit>/edl.json <edit>/verify/<имя>
"""
import json, subprocess, sys
from pathlib import Path

video, edl_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
edl = json.loads(edl_path.read_text())
# output-время границ ranges
bounds, t = [], 0.0
for r in edl["ranges"]:
    t += r["end"] - r["start"]
    bounds.append(round(t, 2))
total = bounds[-1]
bounds = bounds[:-1]

def grab(ts, label, path, w=180, h=320):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ts:.2f}", "-i", str(video), "-frames:v", "1",
                    "-vf", f"scale={w}:{h},drawtext=text='{label}':fontsize=20:fontcolor=yellow:x=6:y=6", str(path)],
                   check=True)

def sheet(paths, cols, name, w, h):
    if len(paths) == 1:  # xstack требует ≥2 входов
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(paths[0]), str(out / name)], check=True)
        return
    inputs = []
    for p in paths:
        inputs += ["-i", str(p)]
    layout = "|".join(f"{(i % cols) * w}_{(i // cols) * h}" for i in range(len(paths)))
    refs = "".join(f"[{i}]" for i in range(len(paths)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex",
                    f"{refs}xstack=inputs={len(paths)}:layout={layout}:fill=black", str(out / name)], check=True)

# 1. стыки: кадр до и после каждой границы
paths = []
for i, b in enumerate(bounds):
    for dt, tag in ((-0.12, "a"), (0.12, "b")):
        p = out / f"cut_{i:02d}{tag}.png"
        grab(max(0.0, b + dt), f"{b + dt:.2f}", p)
        paths.append(p)
# по 8 в ряд (4 стыка), листы по 32 кадра
for k in range(0, len(paths), 32):
    chunk = paths[k:k + 32]
    sheet(chunk, 8, f"cuts_{k // 32}.png", 180, 320)
# 2. субтитры/оверлеи: каждые 3 с
paths = []
ts = 0.5
while ts < total:
    p = out / f"sub_{ts:05.1f}.png"
    grab(ts, f"{ts:.1f}", p, 270, 480)
    paths.append(p)
    ts += 3.0
for k in range(0, len(paths), 16):
    sheet(paths[k:k + 16], 8, f"subs_{k // 16}.png", 270, 480)
print("total", total, "bounds", len(bounds), "sheets:", sorted(p.name for p in out.glob("*.png") if p.name.startswith(("cuts_", "subs_"))))
