"""
helpers/post_render_review.py — авто-санити-чек ГОТОВОГО рендера.

Зачем: после того как render.py выдал финальный файл, нужно убедиться, что он
не «битый» — нет чёрных кадров (потерянный видеослой/неверный overlay), нет
тишины или клиппинга в звуке, длительность и разрешение совпадают с ожидаемыми.

Что проверяет:
1. probe        — ffprobe → duration / width / height / fps / has_audio.
2. expected     — сверка с --expect-duration (±0.5 с) и --expect-res (WxH).
3. black frames — кадры на 5 позициях (1.0с, 25%, 50%, 75%, end-1.0с);
                  средняя яркость кадра < порога → «чёрный кадр».
4. audio        — ffmpeg volumedetect → mean/max dB; тишина (max < -50 dB)
                  или клиппинг (max >= -0.1 dB).

Идея проверки заимствована из AGPL-проекта OpenMontage (tools/analysis/visual_qa.py);
данная реализация написана с нуля, чужой код не копировался.

Интеграция в render.py (в самом конце, после получения out_path):
    import post_render_review as prr
    report = prr.review(out_path, expect={"duration": total_s, "res": (W, H)})
    if not report["ok"]:
        print("ВНИМАНИЕ, рендер с проблемами:", "; ".join(report["problems"]))

CLI:
    python3 helpers/post_render_review.py out.mp4
    python3 helpers/post_render_review.py out.mp4 --expect-duration 30 --expect-res 1080x1920
    python3 helpers/post_render_review.py out.mp4 --json
    python3 helpers/post_render_review.py out.mp4 --keep-frames --vision

Exit code: 0 — всё ok; 2 — найдены проблемы.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Бинари ffmpeg / ffprobe — через platform_paths, иначе fallback на PATH-имя.
# ─────────────────────────────────────────────────────────────────────────────

def _bin(name: str) -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import platform_paths as pp

        return pp.ffmpeg_bin(name)
    except Exception:
        return name


# Пороги (вынесены, чтобы caller мог переопределить осознанно).
BLACK_LUMA_THRESHOLD = 8.0      # средняя яркость кадра 0..255, ниже — «чёрный»
SILENCE_MAX_DB = -50.0          # max_volume ниже — считаем тишиной
CLIPPING_MAX_DB = -0.1          # max_volume не ниже — считаем клиппингом
DURATION_TOLERANCE_S = 0.5      # допуск по длительности


# ─────────────────────────────────────────────────────────────────────────────
# 1. probe
# ─────────────────────────────────────────────────────────────────────────────

def probe(video: Path) -> dict:
    """ffprobe → {duration, width, height, fps, has_audio}.

    Падает понятной русской ошибкой, если файла нет или ffprobe не смог его прочитать.
    """
    if not video.exists():
        sys.exit(f"Файл не найден: {video}")

    cmd = [
        _bin("ffprobe"), "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=index,codec_type,width,height,avg_frame_rate",
        "-of", "json", str(video),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("ffprobe не найден. Установи ffmpeg или задай FFPROBE_BIN.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffprobe не смог прочитать файл: {e.stderr.strip() or video}")

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"ffprobe вернул нечитаемый ответ для {video}")

    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    width = height = 0
    fps = 0.0
    has_audio = False
    for st in data.get("streams", []):
        ctype = st.get("codec_type")
        if ctype == "video" and width == 0:
            width = int(st.get("width") or 0)
            height = int(st.get("height") or 0)
            fps = _parse_fps(st.get("avg_frame_rate"))
        elif ctype == "audio":
            has_audio = True

    if width == 0 or height == 0:
        sys.exit(f"В файле нет видеопотока с размерами: {video}")

    return {
        "duration": round(duration, 3),
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "has_audio": has_audio,
    }


def _parse_fps(rate: str | None) -> float:
    """'30000/1001' → 29.97; '25/1' → 25.0; пустое/0 → 0.0."""
    if not rate or rate == "0/0":
        return 0.0
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def check_expected(info: dict, expect: dict | None) -> dict:
    """Сверка probe-данных с ожидаемыми. expect: {'duration': float, 'res': (w, h)}."""
    result: dict = {"checked": False, "problems": []}
    if not expect:
        return result
    result["checked"] = True

    exp_dur = expect.get("duration")
    if exp_dur is not None:
        diff = abs(info["duration"] - float(exp_dur))
        result["duration_diff"] = round(diff, 3)
        if diff > DURATION_TOLERANCE_S:
            result["problems"].append(
                f"длительность {info['duration']:.2f}с расходится с ожидаемой "
                f"{float(exp_dur):.2f}с (разница {diff:.2f}с > {DURATION_TOLERANCE_S}с)"
            )

    exp_res = expect.get("res")
    if exp_res:
        ew, eh = int(exp_res[0]), int(exp_res[1])
        if (info["width"], info["height"]) != (ew, eh):
            result["problems"].append(
                f"разрешение {info['width']}x{info['height']} не совпадает "
                f"с ожидаемым {ew}x{eh}"
            )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. чёрные кадры
# ─────────────────────────────────────────────────────────────────────────────

def _frame_positions(duration: float) -> list[float]:
    """5 позиций для скриншотов; клампим внутрь [0, duration]."""
    if duration <= 0:
        return [0.0]
    end = max(0.0, duration - 1.0)
    raw = [1.0, duration * 0.25, duration * 0.50, duration * 0.75, end]
    return [round(min(max(0.0, t), max(0.0, duration - 0.05)), 3) for t in raw]


def _extract_frame(video: Path, ts: float, dest: Path) -> bool:
    """Один кадр в dest (jpg). True — успех."""
    cmd = [
        _bin("ffmpeg"), "-v", "error", "-y",
        "-ss", f"{ts:.3f}", "-i", str(video),
        "-frames:v", "1", "-q:v", "3", str(dest),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return dest.exists() and dest.stat().st_size > 0


def _frame_luma(frame: Path) -> float | None:
    """Средняя яркость кадра 0..255.

    Сначала пробуем PIL (быстро, без второго ffmpeg-прохода). Если PIL нет —
    fallback на ffmpeg signalstats (YAVG из метаданных).
    """
    luma = _frame_luma_pil(frame)
    if luma is not None:
        return luma
    return _frame_luma_ffmpeg(frame)


def _frame_luma_pil(frame: Path) -> float | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(frame) as im:
            small = im.convert("L").resize((64, 64))
            px = list(small.getdata())
        return sum(px) / len(px) if px else 0.0
    except Exception:
        return None


def _frame_luma_ffmpeg(frame: Path) -> float | None:
    """ffmpeg signalstats → YAVG (средняя яркость) из stderr-метаданных."""
    cmd = [
        _bin("ffmpeg"), "-v", "error", "-i", str(frame),
        "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
        "-f", "null", "-",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    m = re.search(r"lavfi\.signalstats\.YAVG[=:]\s*([\d.]+)", res.stderr)
    return float(m.group(1)) if m else None


def review_frames(video: Path, duration: float, frame_dir: Path) -> dict:
    """Извлекает кадры на 5 позициях, считает яркость, помечает чёрные."""
    frame_dir.mkdir(parents=True, exist_ok=True)
    positions = _frame_positions(duration)
    frames: list[dict] = []
    black: list[float] = []

    for i, ts in enumerate(positions):
        dest = frame_dir / f"frame_{i:02d}_{ts:.2f}s.jpg"
        ok = _extract_frame(video, ts, dest)
        luma = _frame_luma(dest) if ok else None
        is_black = ok and luma is not None and luma < BLACK_LUMA_THRESHOLD
        if is_black:
            black.append(ts)
        frames.append({
            "position_s": ts,
            "path": str(dest) if ok else None,
            "luma": round(luma, 2) if luma is not None else None,
            "is_black": bool(is_black),
        })

    return {"frames": frames, "black_frames": black}


# ─────────────────────────────────────────────────────────────────────────────
# 3. уровни звука
# ─────────────────────────────────────────────────────────────────────────────

def audio_levels(video: Path, has_audio: bool) -> dict:
    """ffmpeg volumedetect → {mean_db, max_db, flags:[...]}.

    flags: 'нет аудиодорожки' | 'тишина' | 'клиппинг'.
    """
    if not has_audio:
        return {"mean_db": None, "max_db": None, "flags": ["нет аудиодорожки"]}

    cmd = [
        _bin("ffmpeg"), "-v", "info", "-i", str(video),
        "-af", "volumedetect", "-f", "null", "-",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        sys.exit("ffmpeg не найден. Установи ffmpeg или задай FFMPEG_BIN.")
    except subprocess.CalledProcessError as e:
        return {"mean_db": None, "max_db": None,
                "flags": [f"не удалось измерить звук: {e.stderr.strip()[:120]}"]}

    stderr = res.stderr
    mean_db = _grab_db(stderr, "mean_volume")
    max_db = _grab_db(stderr, "max_volume")

    flags: list[str] = []
    if max_db is None:
        flags.append("не удалось измерить звук")
    else:
        if max_db < SILENCE_MAX_DB:
            flags.append("тишина")
        if max_db >= CLIPPING_MAX_DB:
            flags.append("клиппинг")

    return {"mean_db": mean_db, "max_db": max_db, "flags": flags}


def _grab_db(text: str, key: str) -> float | None:
    """'... mean_volume: -23.4 dB' → -23.4."""
    m = re.search(rf"{re.escape(key)}:\s*(-?[\d.]+)\s*dB", text)
    return float(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Главная функция
# ─────────────────────────────────────────────────────────────────────────────

def review(
    video,
    expect: dict | None = None,
    frame_dir=None,
    keep_frames: bool = False,
) -> dict:
    """Полный санити-чек рендера.

    Args:
        video: путь к готовому файлу (str | Path).
        expect: {'duration': float_сек, 'res': (w, h)} — оба ключа опциональны.
        frame_dir: куда класть кадры; None → временная папка.
        keep_frames: оставить извлечённые кадры (иначе временные чистятся).

    Returns:
        dict с ключами: ok, probe, expected_check, frames, black_frames,
        audio, problems (список русских строк).
    """
    video = Path(video)
    info = probe(video)

    expected_check = check_expected(info, expect)

    # Папка под кадры: переданная / временная (которую сами чистим).
    tmp_obj = None
    if frame_dir is not None:
        fdir = Path(frame_dir)
        cleanup = False
    elif keep_frames:
        fdir = video.parent / f"{video.stem}_review_frames"
        cleanup = False
    else:
        tmp_obj = tempfile.TemporaryDirectory(prefix="render_review_")
        fdir = Path(tmp_obj.name)
        cleanup = True

    try:
        frames_res = review_frames(video, info["duration"], fdir)
        # Если папка временная — переносить нечего, копим список путей до очистки.
        frames = frames_res["frames"]
        black = frames_res["black_frames"]

        audio = audio_levels(video, info["has_audio"])

        problems: list[str] = []
        problems.extend(expected_check.get("problems", []))
        if black:
            pos = ", ".join(f"{t:.2f}с" for t in black)
            problems.append(f"чёрные кадры на позициях: {pos}")
        for flag in audio["flags"]:
            if flag in ("тишина", "клиппинг"):
                problems.append(f"звук: {flag}")

        ok = len(problems) == 0

        report = {
            "ok": ok,
            "video": str(video),
            "probe": info,
            "expected_check": expected_check,
            "frames": frames,
            "black_frames": black,
            "audio": audio,
            "problems": problems,
        }
        return report
    finally:
        if cleanup and tmp_obj is not None:
            # Если был --json/вывод, кадры уже отражены путями; чистим временную.
            tmp_obj.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_res(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", s)
    if not m:
        sys.exit(f"--expect-res должен быть в формате WxH, например 1080x1920 (получено: {s})")
    return int(m.group(1)), int(m.group(2))


def _print_human(report: dict) -> None:
    p = report["probe"]
    print(f"Файл: {report['video']}")
    print(f"  длительность: {p['duration']:.2f}с | {p['width']}x{p['height']} | "
          f"{p['fps']:.2f} fps | звук: {'есть' if p['has_audio'] else 'нет'}")

    a = report["audio"]
    if a["mean_db"] is not None or a["max_db"] is not None:
        print(f"  звук: mean {a['mean_db']} dB | max {a['max_db']} dB")

    print("  кадры (яркость 0..255):")
    for f in report["frames"]:
        mark = " ← ЧЁРНЫЙ" if f["is_black"] else ""
        luma = f["luma"] if f["luma"] is not None else "—"
        print(f"    {f['position_s']:>7.2f}с: {luma}{mark}")

    if report["problems"]:
        print("\nПРОБЛЕМЫ:")
        for pr in report["problems"]:
            print(f"  - {pr}")
        print("\nИТОГ: рендер с проблемами")
    else:
        print("\nИТОГ: рендер в порядке")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Авто-санити-чек готового рендера (чёрные кадры, тишина/клиппинг, длительность/разрешение)."
    )
    ap.add_argument("video", help="путь к готовому видеофайлу")
    ap.add_argument("--expect-duration", type=float, default=None,
                    help="ожидаемая длительность в секундах (допуск ±0.5с)")
    ap.add_argument("--expect-res", type=str, default=None,
                    help="ожидаемое разрешение WxH, например 1080x1920")
    ap.add_argument("--keep-frames", action="store_true",
                    help="оставить извлечённые кадры рядом с видео (для ручного просмотра)")
    ap.add_argument("--vision", action="store_true",
                    help="вернуть пути кадров для проверки vision-моделью оркестратором")
    ap.add_argument("--json", action="store_true",
                    help="машинный вывод (JSON) вместо человекочитаемого")
    args = ap.parse_args()

    expect: dict = {}
    if args.expect_duration is not None:
        expect["duration"] = args.expect_duration
    if args.expect_res:
        expect["res"] = _parse_res(args.expect_res)

    # При --vision кадры нужны оркестратору → не чистим их (как при --keep-frames).
    keep = args.keep_frames or args.vision

    report = review(Path(args.video), expect=expect or None, keep_frames=keep)

    if args.vision:
        # TODO (хук для агента-оркестратора): прогнать кадры через
        # mcp__teletranscribe__describe_image_batch для поиска артефактов,
        # обрезанного текста, кривых overlay. MCP здесь НЕ вызывается —
        # это делает оркестратор по этим путям.
        report["vision_frames"] = [f["path"] for f in report["frames"] if f["path"]]
        report["vision_todo"] = (
            "Оркестратор: прогони vision_frames через describe_image_batch "
            "для проверки артефактов и обрезанного текста."
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)

    sys.exit(0 if report["ok"] else 2)


if __name__ == "__main__":
    main()
