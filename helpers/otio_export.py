"""Экспорт нашего JSON-EDL в OTIO (.otio) и совместимые форматы (FCPXML / EDL CMX3600).

OTIO (OpenTimelineIO от Pixar/ASWF) — единственный lossless EDL-формат, который
понимают DaVinci Resolve, Final Cut Pro, Premiere через адаптеры.

Hard Rule #16: при каждом сохранении нашего EDL — экспортируй .otio для бэкапа
и для возможности доработки в pro-NLE.

Usage:
    python helpers/otio_export.py <edl.json>                # → edl.otio
    python helpers/otio_export.py <edl.json> --format fcpxml  # → edl.fcpxml
    python helpers/otio_export.py <edl.json> --all          # все доступные форматы
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def edl_to_otio(edl: dict, fps: int = 24):
    try:
        import opentimelineio as otio
    except ImportError:
        sys.exit("OpenTimelineIO не установлен. `uv add OpenTimelineIO`")

    tl = otio.schema.Timeline(name=edl.get("name") or "montazh_agent_edit")
    video_track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    audio_track = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)

    sources = edl.get("sources", {})

    for r in edl.get("ranges", []):
        src_name = r["source"]
        src_path = sources.get(src_name, src_name)
        start = float(r["start"])
        end = float(r["end"])
        duration = end - start

        media_ref = otio.schema.ExternalReference(
            target_url=f"file://{src_path}",
            available_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(duration + start, fps),
            ),
        )
        clip_video = otio.schema.Clip(
            name=f"{src_name}_{start:.2f}-{end:.2f}",
            media_reference=media_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(start, fps),
                duration=otio.opentime.RationalTime(duration, fps),
            ),
        )
        # Метаданные
        meta = {
            "beat": r.get("beat"),
            "quote": r.get("quote"),
            "reason": r.get("reason"),
            "generated": r.get("need_broll", False),
        }
        clip_video.metadata.update({"montazh": {k: v for k, v in meta.items() if v is not None}})
        video_track.append(clip_video)

        # Дубль на аудио-трек
        clip_audio = clip_video.deepcopy()
        clip_audio.name += "_audio"
        audio_track.append(clip_audio)

    tl.tracks.append(video_track)
    tl.tracks.append(audio_track)
    return tl


def main() -> None:
    ap = argparse.ArgumentParser(description="Экспорт JSON-EDL → OTIO / FCPXML / EDL")
    ap.add_argument("edl", type=Path, help="Путь к edl.json")
    ap.add_argument("--format", default="otio",
                    choices=["otio", "fcpxml", "fcp7_xml", "cmx_3600", "all"],
                    help="Формат выхода (default: otio)")
    ap.add_argument("--fps", type=int, default=24, help="FPS таймлайна (default 24)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Путь выхода (по умолчанию: рядом с edl.json)")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"edl не найден: {edl_path}")

    edl = json.loads(edl_path.read_text())
    tl = edl_to_otio(edl, fps=args.fps)

    import opentimelineio as otio

    fmt_to_ext = {
        "otio": ".otio",
        "fcpxml": ".fcpxml",
        "fcp7_xml": ".xml",
        "cmx_3600": ".edl",
    }

    formats = list(fmt_to_ext.keys()) if args.format == "all" else [args.format]

    for fmt in formats:
        ext = fmt_to_ext[fmt]
        out_path = args.out or edl_path.with_suffix(ext)
        if args.format == "all":
            out_path = edl_path.with_suffix(ext)
        try:
            otio.adapters.write_to_file(tl, str(out_path))
            print(f"✓ {fmt:10} → {out_path}")
        except Exception as e:
            print(f"✗ {fmt:10}: {e}")


if __name__ == "__main__":
    main()
