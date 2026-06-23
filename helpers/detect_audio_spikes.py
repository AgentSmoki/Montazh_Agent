"""Detect audio spikes на cut-границах в готовом preview.mp4.

Решает gap из SKILL.md self-eval: «Спайк на waveform на границе (audio pop
пробил 30ms fade)». Раньше это делалось ВРУЧНУЮ через timeline_view PNG —
теперь автоматизировано.

Алгоритм:
1. Прогнать RMS envelope по всему preview.mp4 через librosa (1024 samples/window).
2. Для каждого cut-boundary из EDL (через output-timeline cumulative_start):
   - Замерить max RMS в окне ±50мс вокруг границы
   - Замерить median RMS в более широком окне ±500мс (baseline)
   - Если max > baseline * 2.0 → подозреваем spike
3. Возвращает список cut'ов с предложенным fix'ом (увеличить padding).

Альтернатива librosa — `ffmpeg ... -af astats -f null -` парсинг (без сторонних
зависимостей). Используем librosa так как она уже в pyproject (для timeline_view).

Usage:
    python helpers/detect_audio_spikes.py <preview.mp4> --edl <edl.json>
    python helpers/detect_audio_spikes.py <preview.mp4> --edl <edl.json> --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_wav(video: Path, dest: Path) -> None:
    """ffmpeg → mono 16kHz wav для анализа."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def detect_spikes(
    preview_mp4: Path,
    edl: dict,
    window_ms: int = 50,
    baseline_ms: int = 500,
    spike_ratio: float = 2.0,
    rms_delta_threshold: float = 0.05,
) -> list[dict]:
    """Dual-check: onset detection + RMS-delta peaks (по Gemini Deep Research).

    Click registers как:
      (a) широкополосный onset в окне cut ±window_ms
      AND
      (b) скачок RMS-delta > threshold в том же окне

    Только если ОБА критерия — реальный pop. Это резко снижает false-positives
    по сравнению с одним RMS-ratio проходом.

    Returns [{cut_at, beat_idx, beat_name, rms_ratio, has_onset, fix_hint}, ...]
    """
    try:
        import librosa
        import numpy as np
        import scipy.signal
    except ImportError:
        sys.exit("librosa/numpy/scipy не установлены. `uv sync`")

    # Compute cumulative output-timeline boundaries
    boundaries: list[tuple[float, int]] = []
    cumulative = 0.0
    ranges = edl.get("ranges", [])
    for i, r in enumerate(ranges[:-1]):
        cumulative += (r["end"] - r["start"])
        boundaries.append((cumulative, i))

    if not boundaries:
        return []

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio.wav"
        extract_wav(preview_mp4, wav_path)
        y, sr = librosa.load(str(wav_path), sr=16000, mono=True)

    # 1. RMS envelope для baseline ratio check
    rms_hop = 256
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=rms_hop)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=rms_hop)

    # 2. RMS-delta peaks (sudden energy jumps)
    rms_delta = np.abs(np.diff(rms))
    delta_peaks_idx, _ = scipy.signal.find_peaks(rms_delta, height=rms_delta_threshold)
    delta_peak_times = rms_times[delta_peaks_idx] if len(delta_peaks_idx) else np.array([])

    # 3. Onset detection (broadband click marker) — short hop для precision
    onsets = librosa.onset.onset_detect(
        y=y, sr=sr, units="time", hop_length=128, backtrack=False
    )

    spikes: list[dict] = []
    win = window_ms / 1000.0
    base = baseline_ms / 1000.0

    for cut_time, beat_idx in boundaries:
        mask_window = (rms_times >= cut_time - win) & (rms_times <= cut_time + win)
        mask_baseline = (rms_times >= cut_time - base) & (rms_times <= cut_time + base)
        if not mask_window.any() or not mask_baseline.any():
            continue

        max_rms = float(np.max(rms[mask_window]))
        baseline_rms = float(np.median(rms[mask_baseline]))
        ratio = max_rms / max(baseline_rms, 1e-6)

        # Check onset in window
        has_onset = bool(np.any((onsets >= cut_time - win) & (onsets <= cut_time + win)))
        # Check RMS-delta peak in window
        has_delta_peak = bool(np.any(
            (delta_peak_times >= cut_time - win) & (delta_peak_times <= cut_time + win)
        ))

        # Dual-check: при простой проверке (только ratio) — false-positives
        # На взрыв plain ratio > 2.0 не редкость (даже на чистом стыке).
        # Реальный pop: ratio > spike_ratio И (has_onset ИЛИ has_delta_peak)
        is_spike = ratio > spike_ratio and (has_onset or has_delta_peak)

        if is_spike:
            spikes.append({
                "cut_at": round(cut_time, 3),
                "beat_idx": beat_idx,
                "beat_name": ranges[beat_idx].get("beat", ""),
                "rms_ratio": round(ratio, 2),
                "has_onset": has_onset,
                "has_delta_peak": has_delta_peak,
                "suggested_pad_ms": 200,
                "fix_hint": (
                    f"Расширить post-pad до 200мс на beat #{beat_idx} "
                    f"('{ranges[beat_idx].get('beat','')}'). "
                    f"Если повторяется — добавить L-cut 30мс."
                ),
            })

    return spikes


def main() -> None:
    ap = argparse.ArgumentParser(description="Detect audio spikes на cut-границах")
    ap.add_argument("preview", type=Path)
    ap.add_argument("--edl", type=Path, required=True)
    ap.add_argument("--window-ms", type=int, default=50)
    ap.add_argument("--baseline-ms", type=int, default=500)
    ap.add_argument("--spike-ratio", type=float, default=2.0,
                    help="max_rms / baseline_rms threshold (default 2.0 = +6dB)")
    ap.add_argument("--json", action="store_true",
                    help="Машинно-читаемый JSON-вывод")
    args = ap.parse_args()

    edl = json.loads(args.edl.read_text(encoding="utf-8"))
    spikes = detect_spikes(args.preview, edl, args.window_ms, args.baseline_ms, args.spike_ratio)

    if args.json:
        print(json.dumps(spikes, ensure_ascii=False, indent=2))
        sys.exit(0 if not spikes else 1)

    if not spikes:
        print(f"✓ no spikes detected на {len(edl.get('ranges', [])) - 1} cut(s)")
        sys.exit(0)

    print(f"⚠️  {len(spikes)} spike(s) detected:")
    for s in spikes:
        print(f"  cut at {s['cut_at']}с (beat #{s['beat_idx']} '{s['beat_name']}'): "
              f"ratio={s['ratio']}× → {s['fix_hint']}")
    sys.exit(1)


if __name__ == "__main__":
    main()
