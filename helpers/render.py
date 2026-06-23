"""Render a video from an EDL.

Implements the HEURISTICS render pipeline in the correct order:

  1. Per-segment extract with color grade + 30ms audio fades baked in
  2. Lossless -c copy concat into base.mp4
  3. If overlays or subtitles: single filter graph that overlays animations
     (with PTS shift so frame 0 lands at the overlay window start)
     and applies `subtitles` filter LAST → final.mp4

Optionally builds a master SRT from the per-source transcripts + EDL
output-timeline offsets, applies the proven force_style (2-word
UPPERCASE chunks, Helvetica 18 Bold, MarginV=35).

Usage:
    python helpers/render.py <edl.json> -o final.mp4
    python helpers/render.py <edl.json> -o preview.mp4 --preview
    python helpers/render.py <edl.json> -o final.mp4 --build-subtitles
    python helpers/render.py <edl.json> -o final.mp4 --no-subtitles
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from grade import get_preset, auto_grade_for_clip  # same directory
except Exception:
    def get_preset(name: str) -> str:
        return ""

    def auto_grade_for_clip(video, start=0.0, duration=None, verbose=False):  # type: ignore
        return "eq=contrast=1.03:saturation=0.98", {}


# -------- Subtitle style (bold-overlay, proven at 1920×1080 and 1080×1920) --
#
# MarginV is NOT taste — it is a platform safe-zone rule.
# TikTok / IG Reels / Shorts UI (caption, username, music, right-rail actions)
# covers roughly the bottom ~25–30% of a 1080×1920 frame. Captions placed near
# the bottom edge get clipped or obscured by the UI. libass auto-scales the
# render canvas relative to PlayResY=288, so MarginV=90 lands the caption
# baseline roughly 30% up from the bottom on any aspect — clear of the UI on
# every major vertical-video platform. Do not drop this below ~75 without a
# specific reason.
SUB_FORCE_STYLE = (
    "FontName=Helvetica,FontSize=15,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=1,Outline=1,Shadow=0,"
    "Alignment=2,MarginV=90"
)
# Подобрано с Богданом: FontSize=15 (компактнее), Outline=1 (тоньше обводка).
# Italic НЕ форсим — естественный наклон шрифта оставлен по его просьбе.

# -------- Helpers ------------------------------------------------------------


def run(cmd: list[str], quiet: bool = False) -> None:
    if not quiet:
        print(f"  $ {' '.join(str(c) for c in cmd[:6])}{' …' if len(cmd) > 6 else ''}")
    subprocess.run(cmd, check=True)


def resolve_grade_filter(grade_field: str | None) -> str:
    """The EDL's 'grade' field can be a preset name, a raw ffmpeg filter, or 'auto'.

    Returns the filter string to embed into the per-segment -vf chain.
    For 'auto', returns the sentinel "__AUTO__" which is resolved per-segment.
    """
    if not grade_field:
        return ""
    if grade_field == "auto":
        return "__AUTO__"
    # Preset names are short identifiers, filter strings contain '=' or ','.
    if re.fullmatch(r"[a-zA-Z0-9_\-]+", grade_field):
        try:
            return get_preset(grade_field)
        except KeyError:
            print(f"warning: unknown preset '{grade_field}', using as raw filter")
            return grade_field
    return grade_field


def resolve_path(maybe_path: str, base: Path) -> Path:
    """Resolve a path that may be absolute or relative to `base`."""
    p = Path(maybe_path)
    if p.is_absolute():
        return p
    return (base / p).resolve()


# -------- HDR → SDR tone mapping (HLG / PQ sources) --------------------------
#
# iPhone defaults to HLG HDR in Rec.2020 (and many mirrorless cameras ship PQ).
# If the source is HDR and we only downconvert bit depth (yuv420p10le → yuv420p)
# without tone-mapping, the output is 8-bit but still carries HLG/PQ transfer
# metadata. Players that honor the metadata (screen recorders, most social
# upload re-encodes) interpret 8-bit values in an HDR container and the result
# looks oversaturated / blown out. QuickTime on macOS can hide this locally —
# screen recording and uploaded renders cannot.
#
# Fix: detect HDR via color_transfer and prepend a zscale+tonemap chain to the
# vf graph so the output is clean Rec.709 SDR.

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (HDR10) and HLG

TONEMAP_CHAIN = (
    "zscale=t=linear:npl=100,"
    "format=gbrpf32le,"
    "zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,"
    "format=yuv420p"
)


def is_hdr_source(video: Path) -> bool:
    """Return True if the source uses a PQ or HLG transfer function."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_transfer",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() in HDR_TRANSFERS
    except subprocess.CalledProcessError:
        return False


def is_portrait_source(video: Path) -> bool:
    """Return True if the video's height > width (portrait / vertical)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True,
        )
        w, h = map(int, out.stdout.strip().split(","))
        return h > w
    except Exception:
        return False


# -------- Per-segment extraction (Rule 2 + Rule 3) --------------------------


FPS = 24  # вывод фиксирован 24fps (см. -r ниже) — push-in считает кадры по нему


def build_geometry_vf(
    portrait: bool, draft: bool, effect: str, duration: float
) -> str:
    """Вернуть vf-цепочку геометрии: COVER-scale к точному кадру ИЛИ push-in.

    ВАЖНО: все сегменты приводятся к ОДИНАКОВОМУ размеру (1080×1920 портрет /
    1920×1080 ландшафт) через force_original_aspect_ratio=increase + crop.
    Раньше было scale=-2:1920 → источники 1072×1920 и preprocessed 1080×1920
    давали РАЗНУЮ ширину, и lossless concat (-c copy) их склеивал криво.
    Cover-crop убирает этот латентный баг.

    effect="pushin" — медленный Ken-Burns 1.0→1.12 (establish→деталь) для
    `screen_read`-битов: даёт глазу осесть и прочитать текст на экране,
    вместо резкого статичного зума. Пред-апскейл 2× убирает дрожание zoompan.
    """
    if portrait:
        W, H = (720, 1280) if draft else (1080, 1920)
    else:
        W, H = (1280, 720) if draft else (1920, 1080)

    if effect == "pushin":
        n = max(2, int(round(duration * FPS)))
        return (
            f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
            f"crop={W*2}:{H*2},"
            f"zoompan=z='min(1+0.12*on/{n-1}\\,1.12)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={W}x{H}:fps={FPS}"
        )
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"


def extract_segment(
    source: Path,
    seg_start: float,
    duration: float,
    grade_filter: str,
    out_path: Path,
    preview: bool = False,
    draft: bool = False,
    effect: str = "",
) -> None:
    """Extract a cut range as its own MP4 with grade + 30ms audio fades baked in.

    `-ss` before `-i` for fast accurate seeking. All segments are normalized to
    a single frame size (cover-crop) so lossless concat is glitch-free.
    `effect="pushin"` applies a slow Ken-Burns zoom for screen_read beats.

    Quality ladder:
      - final (default): 1080p libx264 fast CRF 20
      - preview:         1080p libx264 medium CRF 22 (evaluable for QC)
      - draft:           720p libx264 ultrafast CRF 28 (cut-point check only)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    portrait = is_portrait_source(source)

    vf_parts: list[str] = []
    if is_hdr_source(source):
        vf_parts.append(TONEMAP_CHAIN)
    vf_parts.append(build_geometry_vf(portrait, draft, effect, duration))
    if grade_filter:
        vf_parts.append(grade_filter)
    vf = ",".join(vf_parts)

    # 30ms audio fades at both edges (Rule 3) — prevent pops.
    # curve=hsin (half-sine = hanning) сглаживает фазу лучше чем default tri.
    # По Gemini Deep Research: tri-curve оставляет click'и на zero-crossing.
    fade_out_start = max(0.0, duration - 0.03)
    af = (f"afade=t=in:st=0:d=0.03:curve=hsin,"
          f"afade=t=out:st={fade_out_start:.3f}:d=0.03:curve=hsin")

    # Кодек: draft → VideoToolbox (3-5× быстрее libx264 на Intel macOS),
    # preview/final → libx264 (мягче на субтитрах и лицах, особенно на старых
    # Intel CPU, где QSV даёт мыло на низких битрейтах).
    # Источник: Gemini Deep Research stack-исследование, май 2026.
    if draft:
        codec_args = [
            "-c:v", "h264_videotoolbox",
            "-b:v", "10M",   # на Intel constant-quality не работает, используем CBR
            "-allow_sw", "1",  # fallback на soft если hw недоступен
        ]
    elif preview:
        codec_args = ["-c:v", "libx264", "-preset", "medium", "-crf", "22"]
    else:
        codec_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seg_start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-af", af,
        *codec_args,
        "-pix_fmt", "yuv420p", "-r", "24",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def extract_all_segments(
    edl: dict,
    edit_dir: Path,
    preview: bool,
    draft: bool = False,
) -> list[Path]:
    """Extract every EDL range into edit_dir/clips_graded/seg_NN.mp4.
    Returns the ordered list of segment paths.

    If the EDL `grade` is "auto", analyze each segment range with
    `auto_grade_for_clip` and apply a per-segment subtle correction.
    Otherwise, apply the same preset/raw filter to every segment.
    """
    resolved = resolve_grade_filter(edl.get("grade"))
    is_auto = resolved == "__AUTO__"
    clips_dir = edit_dir / (
        "clips_draft" if draft else ("clips_preview" if preview else "clips_graded")
    )
    clips_dir.mkdir(parents=True, exist_ok=True)

    ranges = edl["ranges"]
    sources = edl["sources"]

    seg_paths: list[Path] = []
    print(f"extracting {len(ranges)} segment(s) → {clips_dir.name}/")
    if is_auto:
        print("  (auto-grade per segment: analyzing each range)")
    for i, r in enumerate(ranges):
        src_name = r["source"]
        src_path = resolve_path(sources[src_name], edit_dir)
        start = float(r["start"])
        end = float(r["end"])
        duration = end - start
        out_path = clips_dir / f"seg_{i:02d}_{src_name}.mp4"

        if is_auto:
            seg_filter, _stats = auto_grade_for_clip(src_path, start=start, duration=duration, verbose=False)
        else:
            seg_filter = resolved

        effect = r.get("effect") or ""
        note = r.get("beat") or r.get("note") or ""
        eff_tag = f"  [{effect}]" if effect else ""
        print(f"  [{i:02d}] {src_name}  {start:7.2f}-{end:7.2f}  ({duration:5.2f}s)  {note}{eff_tag}")
        if is_auto:
            print(f"        grade: {seg_filter or '(none)'}")
        extract_segment(src_path, start, duration, seg_filter, out_path,
                        preview=preview, draft=draft, effect=effect)
        seg_paths.append(out_path)

    return seg_paths


# -------- Lossless concat ----------------------------------------------------


def concat_segments(segment_paths: list[Path], out_path: Path, edit_dir: Path) -> None:
    """Lossless concat via the concat demuxer. No re-encode."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = edit_dir / "_concat.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in segment_paths))

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"concat → {out_path.name}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    concat_list.unlink(missing_ok=True)


# -------- Master SRT (Rule 5) ------------------------------------------------


PUNCT_BREAK = set(".,!?;:")


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_in_range(transcript: dict, t_start: float, t_end: float) -> list[dict]:
    out: list[dict] = []
    for w in transcript.get("words", []):
        if w.get("type") != "word":
            continue
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if we <= t_start or ws >= t_end:
            continue
        out.append(w)
    return out


def build_master_srt(edl: dict, edit_dir: Path, out_path: Path) -> None:
    """Build an output-timeline SRT from per-source transcripts.

    - 2-word chunks (break on any punctuation in between)
    - UPPERCASE text
    - Output times computed as word.start - segment_start + segment_offset
    """
    transcripts_dir = edit_dir / "transcripts"
    sources = edl["sources"]

    # Резолвер stem'а транскрипта — тот же, что в snap/padding (учитывает
    # transcript-override для HOOK/CTA/зум и sources-mapping). Без него субтитры
    # для preprocessed-битов молча пропадали (искали HOOK.json вместо IMG_3521.json).
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from snap_to_word import resolve_transcript_stem  # type: ignore
    except Exception:
        def resolve_transcript_stem(r, sm):  # type: ignore
            ov = r.get("transcript")
            if ov:
                return Path(sm[ov]).stem if ov in sm else Path(ov).stem
            m = sm.get(r.get("source"))
            return Path(m).stem if m else r.get("source")

    entries: list[tuple[float, float, str]] = []
    seg_offset = 0.0

    for r in edl["ranges"]:
        src_name = r["source"]
        seg_start = float(r["start"])
        seg_end = float(r["end"])
        seg_duration = seg_end - seg_start
        offset = float(r.get("src_offset", 0.0))

        stem = resolve_transcript_stem(r, sources)
        tr_path = transcripts_dir / f"{stem}.json"
        if not tr_path.exists():
            print(f"  no transcript for {src_name} (stem {stem}), skipping captions")
            seg_offset += seg_duration
            continue

        transcript = json.loads(tr_path.read_text())
        # окно в transcript-time (с учётом src_offset)
        words_in_seg = _words_in_range(transcript, seg_start + offset, seg_end + offset)

        # Group into 2-word chunks, break on punctuation
        chunks: list[list[dict]] = []
        current: list[dict] = []
        for w in words_in_seg:
            text = (w.get("text") or "").strip()
            if not text:
                continue
            current.append(w)
            # Break if the current text ends in punctuation or we hit 2 words
            ends_in_punct = bool(text) and text[-1] in PUNCT_BREAK
            if len(current) >= 2 or ends_in_punct:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)

        for chunk in chunks:
            # chunk-времена в transcript-time; переводим в range-time (−offset),
            # клампим к окну сегмента, затем в output-timeline (+seg_offset).
            w_start = chunk[0].get("start", seg_start + offset) - offset
            w_end = chunk[-1].get("end", seg_end + offset) - offset
            local_start = max(seg_start, w_start)
            local_end = min(seg_end, w_end)
            out_start = max(0.0, local_start - seg_start) + seg_offset
            out_end = max(0.0, local_end - seg_start) + seg_offset
            if out_end <= out_start:
                out_end = out_start + 0.4
            text = " ".join((w.get("text") or "").strip() for w in chunk)
            text = re.sub(r"\s+", " ", text).strip()
            # Strip trailing punctuation for cleaner uppercase look
            text = text.rstrip(",;:")
            text = text.upper()
            entries.append((out_start, out_end, text))

        seg_offset += seg_duration

    # Sort and write as SRT
    entries.sort(key=lambda e: e[0])
    lines: list[str] = []
    for i, (a, b, t) in enumerate(entries, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(a)} --> {_srt_timestamp(b)}")
        lines.append(t)
        lines.append("")
    out_path.write_text("\n".join(lines))
    print(f"master SRT → {out_path.name} ({len(entries)} cues)")


# -------- Loudness normalization (social-ready audio) -----------------------


# Social-media standard: -14 LUFS integrated, -1 dBTP peak, LRA 11 LU.
# Matches YouTube / Instagram / TikTok / X / LinkedIn normalization targets.
LOUDNORM_I = -14.0
LOUDNORM_TP = -1.0
LOUDNORM_LRA = 11.0


def measure_loudness(video_path: Path) -> dict[str, str] | None:
    """Run ffmpeg loudnorm first pass and parse the JSON measurement.

    Returns a dict with measured_i, measured_tp, measured_lra, measured_thresh,
    target_offset, or None if measurement failed.
    """
    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(video_path),
        "-af", filter_str,
        "-vn", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # loudnorm prints the JSON to stderr at the end of the run
    stderr = proc.stderr

    # Find the JSON block — loudnorm output contains a `{ ... }` block
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    needed = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not needed.issubset(data.keys()):
        return None
    return data


def apply_loudnorm_two_pass(
    input_path: Path,
    output_path: Path,
    preview: bool = False,
) -> bool:
    """Run two-pass loudnorm on input_path, write normalized copy to output_path.

    Returns True on success, False if measurement failed (caller should fall
    back to copying the input unchanged).

    In preview mode, skips the measurement pass and uses a one-pass approximation
    for speed. Final mode always does the proper two-pass.
    """
    if preview:
        # One-pass approximation — faster, slightly less accurate.
        filter_str = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", filter_str,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(output_path),
        ]
        print(f"  loudnorm (1-pass preview) → {output_path.name}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True

    # Full two-pass
    print(f"  loudnorm pass 1: measuring {input_path.name}")
    measurement = measure_loudness(input_path)
    if measurement is None:
        print("  loudnorm measurement failed — falling back to 1-pass")
        return apply_loudnorm_two_pass(input_path, output_path, preview=True)

    print(f"    measured: I={measurement['input_i']} LUFS  "
          f"TP={measurement['input_tp']}  LRA={measurement['input_lra']}")

    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        f":measured_I={measurement['input_i']}"
        f":measured_TP={measurement['input_tp']}"
        f":measured_LRA={measurement['input_lra']}"
        f":measured_thresh={measurement['input_thresh']}"
        f":offset={measurement['target_offset']}"
        f":linear=true"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-c:v", "copy",
        "-af", filter_str,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ]
    print(f"  loudnorm pass 2: normalizing → {output_path.name}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return True


# -------- Final compositing (Rule 1 + Rule 4) -------------------------------


def _parse_srt_ts(ts: str) -> float:
    ts = ts.strip().replace(".", ",")
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _strip_srt_windows(srt_path: Path, windows: list[tuple[float, float]]) -> Path:
    """Вернуть путь к копии SRT без cue'ов, пересекающих любое из окон windows.
    Нужно чтобы субтитр не рисовался поверх мема (subtitles-фильтр не умеет
    timeline-enable, поэтому режем на уровне самого SRT)."""
    blocks = [b for b in srt_path.read_text(encoding="utf-8").split("\n\n") if b.strip()]
    kept: list[str] = []
    for b in blocks:
        lines = b.splitlines()
        ts_line = next((l for l in lines if "-->" in l), None)
        if not ts_line:
            continue
        a, bb = ts_line.split("-->")
        cs, ce = _parse_srt_ts(a), _parse_srt_ts(bb)
        if any(cs < w_end and ce > w_start for w_start, w_end in windows):
            continue  # пересекает окно мема — выкидываем
        kept.append(b)
    # перенумеровать
    out_lines: list[str] = []
    for i, b in enumerate(kept, 1):
        bl = b.splitlines()
        # первая строка — номер; заменим
        if bl and bl[0].strip().isdigit():
            bl[0] = str(i)
        else:
            bl = [str(i)] + bl
        out_lines.append("\n".join(bl))
    out_path = srt_path.with_name(srt_path.stem + "_mememuted.srt")
    out_path.write_text("\n\n".join(out_lines) + "\n", encoding="utf-8")
    return out_path


def build_final_composite(
    base_path: Path,
    overlays: list[dict],
    subtitles_path: Path | None,
    out_path: Path,
    edit_dir: Path,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> None:
    """Final pass: base → overlays (PTS-shifted) → subtitles LAST → out.

    Overlay-поля:
      - start_in_output, duration (обязательны)
      - position: 'topleft' (default, PIL-PNG на весь кадр) | 'center' |
        'lower' (нижняя треть, под лицом — для мемов, чтобы не загораживать
        лицо и не налезать на субтитры; Богдан: «мем ниже лица и субтитров»)
      - scale_w: доля ширины кадра (0..1).
      - mute_subs: true → субтитры НЕ рисуются в окне этого оверлея
        (чтобы мем-картинка не перекрывалась подписью).

    Аудио мема (если есть) подмешивается отдельно на этапе ducking
    (music_gen.py duck ... --meme), не здесь.

    If there are no overlays and no subtitles, just copy base to out.
    """
    has_overlays = bool(overlays)
    has_subs = subtitles_path is not None and subtitles_path.exists()

    if not has_overlays and not has_subs:
        # Nothing to do — just rename/copy base to final name
        run(["ffmpeg", "-y", "-i", str(base_path), "-c", "copy", str(out_path)], quiet=True)
        return

    inputs: list[str] = ["-i", str(base_path)]
    for ov in overlays:
        ov_path = resolve_path(ov["file"], edit_dir)
        inputs += ["-i", str(ov_path)]

    filter_parts: list[str] = []
    # PTS-shift (+ optional scale) every overlay so its frame 0 lands at start_in_output
    for idx, ov in enumerate(overlays, start=1):
        t = float(ov["start_in_output"])
        chain = f"[{idx}:v]setpts=PTS-STARTPTS+{t}/TB"
        scale_w = ov.get("scale_w")
        if scale_w:
            tw = int(canvas_w * float(scale_w))
            tw -= tw % 2  # even width for yuv420p
            chain += f",scale={tw}:-2"
        filter_parts.append(chain + f"[a{idx}]")

    # Chain overlays on top of base
    # position:
    #   center → по центру
    #   lower  → нижняя треть, центр по X, низ кадра минус safe-zone субтитров
    #            (мем НАД субтитрами и НИЖЕ лица). y = H*0.60 ориентир.
    #   topleft→ 0:0 (полноэкранные PIL-PNG)
    POS_XY = {
        "center": "(W-w)/2:(H-h)/2",
        "lower": "(W-w)/2:H*0.60",
        "topleft": "0:0",
    }
    current = "[0:v]"
    for idx, ov in enumerate(overlays, start=1):
        t = float(ov["start_in_output"])
        dur = float(ov["duration"])
        end = t + dur
        xy = POS_XY.get(ov.get("position", "topleft"), "0:0")
        next_label = f"[v{idx}]"
        filter_parts.append(
            f"{current}[a{idx}]overlay={xy}:enable='between(t,{t:.3f},{end:.3f})'{next_label}"
        )
        current = next_label

    # Subtitles LAST — Rule 1. Окна оверлеев с mute_subs: субтитры в эти
    # интервалы не показываем (мем-картинку не перекрывать подписью).
    # subtitles-фильтр НЕ поддерживает timeline enable → удаляем cue'и из SRT.
    if has_subs:
        mute_windows = [(float(o["start_in_output"]),
                         float(o["start_in_output"]) + float(o["duration"]))
                        for o in overlays if o.get("mute_subs")]
        srt_to_use = subtitles_path
        if mute_windows:
            srt_to_use = _strip_srt_windows(subtitles_path, mute_windows)
        subs_abs = str(srt_to_use.resolve()).replace(":", r"\:").replace("'", r"\'")
        filter_parts.append(
            f"{current}subtitles='{subs_abs}':force_style='{SUB_FORCE_STYLE}'[outv]"
        )
        out_label = "[outv]"
    else:
        # Rename the last overlay output to [outv] for consistency
        if has_overlays:
            filter_parts.append(f"{current}null[outv]")
            out_label = "[outv]"
        else:
            out_label = "[0:v]"

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", out_label,
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"compositing → {out_path.name}")
    print(f"  overlays: {len(overlays)}, subtitles: {'yes' if has_subs else 'no'}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


# -------- Main ---------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a video from an EDL")
    ap.add_argument("edl", type=Path, help="Path to edl.json")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output video path")
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: 1080p, medium, CRF 22 — evaluable for QC, faster than final.",
    )
    ap.add_argument(
        "--draft",
        action="store_true",
        help="Draft mode: 720p, ultrafast, CRF 28 — cut-point verification only.",
    )
    ap.add_argument(
        "--build-subtitles",
        action="store_true",
        help="Build master.srt from transcripts + EDL offsets before compositing",
    )
    ap.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Skip subtitles even if the EDL references one",
    )
    ap.add_argument(
        "--no-loudnorm",
        action="store_true",
        help="Skip audio loudness normalization. Default is on (-14 LUFS, -1 dBTP, LRA 11).",
    )
    # Word-boundary safety (по Gemini Deep Research)
    ap.add_argument(
        "--no-snap",
        action="store_true",
        help="Skip word-boundary snap pre-pass (use если transcripts/ нет)",
    )
    ap.add_argument(
        "--no-pad",
        action="store_true",
        help="Skip smart padding pre-pass",
    )
    ap.add_argument(
        "--no-spike-check",
        action="store_true",
        help="Skip audio-spike detection post-pass",
    )
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"edl not found: {edl_path}")

    edl = json.loads(edl_path.read_text())
    edit_dir = edl_path.parent
    out_path = args.output.resolve()
    sys.path.insert(0, str(Path(__file__).parent))

    # === EDL validation (fail-fast) ===
    try:
        from validate_edl import validate_edl  # type: ignore
        errors, warnings = validate_edl(edl, edit_dir)
        for w in warnings:
            print(f"⚠️  EDL: {w}")
        if errors:
            print("\n❌ EDL невалиден — рендер остановлен:")
            for e in errors:
                print(f"   {e}")
            sys.exit(1)
    except ImportError as e:
        print(f"warning: validate_edl недоступен ({e})")

    # === Word-boundary safety pre-pass ===
    transcripts_dir = edit_dir / "transcripts"
    if transcripts_dir.is_dir():
        if not args.no_snap:
            try:
                from snap_to_word import snap_edl  # type: ignore
                print("\n=== Snap to word-boundaries ===")
                edl = snap_edl(edl, transcripts_dir, verbose=True)
            except ImportError as e:
                print(f"warning: snap_to_word недоступен ({e})")
        # thought-boundary guard — после snap (отражает реальные точки реза)
        try:
            from check_thought_boundaries import check_thought_cuts  # type: ignore
            print("\n=== Thought-boundary guard ===")
            tw = check_thought_cuts(edl, transcripts_dir)
            if not tw:
                print("✓ все резы на завершённой мысли")
            else:
                print(f"⚠️  {len(tw)} рез(ов) посреди мысли/синтагмы:")
                for w in tw:
                    print(f"  [{w['beat_idx']:02d}] {w['source']} '{w['beat']}' "
                          f"end={w['end']}с: …{w['last_word']} | {w['next_word']}…")
                    for rs in w["reasons"]:
                        print(f"        – {rs}")
        except ImportError as e:
            print(f"warning: check_thought_boundaries недоступен ({e})")
        if not args.no_pad:
            try:
                from apply_padding import apply_smart_padding  # type: ignore
                print("\n=== Smart asymmetric padding ===")
                edl = apply_smart_padding(edl, transcripts_dir, verbose=True)
            except ImportError as e:
                print(f"warning: apply_padding недоступен ({e})")
    else:
        print(f"warning: {transcripts_dir} не найден — skip word-boundary safety")

    # 1. Extract per-segment (auto-grade per range if EDL grade is "auto")
    segment_paths = extract_all_segments(
        edl, edit_dir, preview=args.preview, draft=args.draft
    )

    # 2. Concat → base
    if args.draft:
        base_name = "base_draft.mp4"
    elif args.preview:
        base_name = "base_preview.mp4"
    else:
        base_name = "base.mp4"
    base_path = edit_dir / base_name
    concat_segments(segment_paths, base_path, edit_dir)

    # 3. Subtitles: build if requested, resolve final path
    subs_path: Path | None = None
    if not args.no_subtitles:
        if args.build_subtitles:
            subs_path = edit_dir / "master.srt"
            build_master_srt(edl, edit_dir, subs_path)
        elif edl.get("subtitles"):
            subs_path = resolve_path(edl["subtitles"], edit_dir)
            if not subs_path.exists():
                print(f"warning: subtitles path in EDL does not exist: {subs_path}")
                subs_path = None

    # 4. Composite (overlays + subtitles LAST) → intermediate (pre-loudnorm) path
    overlays = edl.get("overlays") or []
    # canvas из EDL.resolution ("1080x1920") — для центрирования/масштаба мемов
    res = str(edl.get("resolution", "1080x1920")).lower().replace("х", "x")
    try:
        cw, ch = (int(x) for x in res.split("x")[:2])
    except Exception:
        cw, ch = 1080, 1920
    if args.no_loudnorm:
        # Composite directly to final output
        build_final_composite(base_path, overlays, subs_path, out_path, edit_dir,
                              canvas_w=cw, canvas_h=ch)
    else:
        # Composite to a temp file, then run loudnorm → final output
        tmp_composite = out_path.with_suffix(".prenorm.mp4")
        build_final_composite(base_path, overlays, subs_path, tmp_composite, edit_dir,
                              canvas_w=cw, canvas_h=ch)
        print("loudness normalization → social-ready (-14 LUFS / -1 dBTP / LRA 11)")
        apply_loudnorm_two_pass(tmp_composite, out_path, preview=args.draft)

    # === Audio-spike detection post-pass ===
    if not args.no_spike_check and out_path.exists():
        try:
            from detect_audio_spikes import detect_spikes  # type: ignore
            print("\n=== Audio-spike detection (onset + RMS-delta) ===")
            spikes = detect_spikes(out_path, edl)
            if not spikes:
                print(f"✓ no spikes detected на {len(edl.get('ranges', []))-1} cut(s)")
            else:
                print(f"⚠️  {len(spikes)} potential spike(s):")
                for s in spikes:
                    print(f"  cut at {s['cut_at']}с (beat #{s['beat_idx']} '{s['beat_name']}'): "
                          f"ratio={s['rms_ratio']}× onset={s['has_onset']} delta_peak={s['has_delta_peak']}")
                    print(f"    → {s['fix_hint']}")
        except ImportError as e:
            print(f"warning: detect_audio_spikes недоступен ({e})")
        except Exception as e:
            print(f"warning: spike detection упало ({e})")
        tmp_composite.unlink(missing_ok=True)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\ndone: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
