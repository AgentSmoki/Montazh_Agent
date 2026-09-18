"""Генерация фоновой музыки под ролик + подмешивание с ducking под голос.

Провайдеры (порядок автопереключения — DEFAULT_ORDER, настраивается). Ключи —
из .env/окружения, НИКОГДА не в коде. Провайдер без ключа пропускается.
  - sunoapi      SUNOAPI_ORG_KEY + SUNO_CALLBACK_URL   sunoapi.org — проверенный
                 рабочий путь (07-2026, 08-2026). callBackUrl нужен формально
                 (любой публичный https-URL), результат забираем поллингом.
  - elevenlabs   ELEVENLABS_API_KEY   REST, mp3 напрямую, без callback. С 07-2026 — 403.
  - apiframe     APIFRAME_KEY         apiframe.ai Suno-шлюз. Работал 06-2026, с 07-2026 — 403.
  Не реализованы (добавить в PROVIDERS при необходимости): fal (FAL_KEY),
  acedata (ACEDATA_SUNO_KEY).

ducking: музыка приглушается под речь через sidechaincompress (голос = ключ).
Это правильный приём вместо статичного -25dB: музыка громкая в паузах,
тихая под голосом. Уровень регулируется параметром.

CLI:
    # сгенерить трек:
    python helpers/music_gen.py generate "lo-fi tech ambient" --duration 56 \
        --out <edit>/music_bed.mp3 [--provider elevenlabs]
    # подмешать под готовое видео с ducking:
    python helpers/music_gen.py duck <video.mp4> <music.mp3> -o <out.mp4> [--music-db -12]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_paths import ffmpeg_bin


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for ln in env_path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            if k.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


# ---------- провайдеры генерации ---------------------------------------------

def gen_elevenlabs(prompt: str, duration_s: float, out_path: Path) -> bool:
    """ElevenLabs Music — POST /v1/music, отдаёт mp3 бинарём. Без callback."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return False
    ms = max(3000, min(600000, int(duration_s * 1000)))
    body = json.dumps({
        "prompt": prompt,
        "music_length_ms": ms,
        "force_instrumental": True,
        "model_id": "music_v1",
    }).encode()
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/music?output_format=mp3_44100_128",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "xi-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        if data[:3] == b"ID3" or len(data) > 10000:  # похоже на mp3
            out_path.write_bytes(data)
            return True
    except Exception as e:  # noqa: BLE001
        print(f"elevenlabs: {e}", file=sys.stderr)
    return False


def gen_sunoapi_org(prompt: str, duration_s: float, out_path: Path,
                    callback_url: str | None = None) -> bool:
    """sunoapi.org — требует callBackUrl. Если его нет — провайдер недоступен локально.
    Передай --callback (публичный URL вебхука), иначе вернёт False."""
    key = os.environ.get("SUNOAPI_ORG_KEY")
    if not key:
        return False
    cb = callback_url or os.environ.get("SUNO_CALLBACK_URL")
    if not cb:
        print("sunoapi.org: нужен callBackUrl (--callback или SUNO_CALLBACK_URL)",
              file=sys.stderr)
        return False
    body = json.dumps({
        "customMode": False, "instrumental": True,
        "prompt": prompt, "model": "V4_5", "callBackUrl": cb,
    }).encode()
    # Cloudflare перед sunoapi.org отдаёт код 1010 на «неживой» User-Agent
    # (поймано в сессии Urist 2026-07-03) — шлём браузерный.
    ua = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
    req = urllib.request.Request(
        "https://api.sunoapi.org/api/v1/generate", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", **ua})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        task_id = (resp.get("data") or {}).get("taskId")
        if not task_id:
            print(f"sunoapi.org: нет taskId — {resp}", file=sys.stderr)
            return False
        # poll
        poll = f"https://api.sunoapi.org/api/v1/generate/record-info?taskId={task_id}"
        for _ in range(40):
            time.sleep(6)
            pr = urllib.request.Request(poll, headers={"Authorization": f"Bearer {key}", **ua})
            with urllib.request.urlopen(pr, timeout=30) as r:
                pd = json.loads(r.read().decode())
            st = (pd.get("data") or {}).get("status")
            if st == "SUCCESS":
                songs = ((pd.get("data") or {}).get("response") or {}).get("sunoData") or []
                if songs and songs[0].get("audioUrl"):
                    _dl(songs[0]["audioUrl"], out_path)
                    return True
            if st in ("FAILED", "ERROR"):
                print(f"sunoapi.org: задача {st}", file=sys.stderr)
                return False
    except Exception as e:  # noqa: BLE001
        print(f"sunoapi.org: {e}", file=sys.stderr)
    return False


def gen_apiframe(prompt: str, duration_s: float, out_path: Path,
                style: str = "lo-fi, ambient, chill, instrumental") -> bool:
    """apiframe.ai Suno — POST /v2/music/generate → jobId, poll GET /v2/jobs/{id}.

    Подтверждено живым запросом: header X-API-Key, async (HTTP 202 + jobId),
    fetch через GET /v2/jobs/{jobId} (status QUEUED→PROCESSING→ ...).
    Suno генерит 2 трека; берём первый audioUrl. duration_s не задаётся напрямую
    (Suno V4.5 сам ~2-4 мин) — обрежем под ролик при ducking (-shortest)."""
    key = os.environ.get("APIFRAME_KEY")
    if not key:
        return False
    body = json.dumps({
        "prompt": prompt, "model": "suno",
        "sunoParams": {"model_version": "V4_5PLUS", "style": style},
    }).encode()
    req = urllib.request.Request(
        "https://api.apiframe.ai/v2/music/generate", data=body, method="POST",
        headers={"X-API-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        job = resp.get("jobId") or resp.get("id")
        if not job:
            print(f"apiframe: нет jobId — {resp}", file=sys.stderr)
            return False
        poll = f"https://api.apiframe.ai/v2/jobs/{job}"
        for _ in range(60):  # до ~6 мин
            time.sleep(6)
            pr = urllib.request.Request(poll, headers={"X-API-Key": key})
            with urllib.request.urlopen(pr, timeout=30) as r:
                pd = json.loads(r.read().decode())
            st = (pd.get("status") or "").upper()
            if st in ("COMPLETED", "SUCCESS", "FINISHED", "DONE"):
                url = _extract_audio_url(pd)
                if url:
                    _dl(url, out_path)
                    return True
                print(f"apiframe: готово, но нет audioUrl — {str(pd)[:300]}", file=sys.stderr)
                return False
            if st in ("FAILED", "ERROR", "CANCELLED"):
                print(f"apiframe: задача {st}", file=sys.stderr)
                return False
    except Exception as e:  # noqa: BLE001
        print(f"apiframe: {e}", file=sys.stderr)
    return False


def _extract_audio_url(pd: dict):
    """Достать первый audio URL из ответа apiframe (структура output варьируется)."""
    out = pd.get("output") or pd.get("result") or pd.get("data") or {}
    # варианты: output.audioUrl / output[0].audio_url / output.tracks[0].url
    if isinstance(out, dict):
        for k in ("audioUrl", "audio_url", "url", "mp3", "audio"):
            if isinstance(out.get(k), str):
                return out[k]
        for listkey in ("tracks", "songs", "items", "clips"):
            arr = out.get(listkey)
            if isinstance(arr, list) and arr:
                for k in ("audioUrl", "audio_url", "url", "mp3"):
                    if isinstance(arr[0].get(k), str):
                        return arr[0][k]
    if isinstance(out, list) and out:
        for k in ("audioUrl", "audio_url", "url", "mp3"):
            if isinstance(out[0].get(k), str):
                return out[0][k]
    return None


def _dl(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Montazh_Agent/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())


PROVIDERS = {
    "sunoapi": gen_sunoapi_org,
    "elevenlabs": gen_elevenlabs,
    "apiframe": gen_apiframe,
}
# Какой ключ нужен провайдеру — без него провайдер пропускается сразу,
# вместо пустого сетевого запроса и невнятной ошибки.
PROVIDER_KEYS = {
    "sunoapi": "SUNOAPI_ORG_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "apiframe": "APIFRAME_KEY",
}
# Порядок по умолчанию — от проверенного к сомнительным (состояние 2026-09):
# sunoapi.org работает (сессии Urist 07-2026, BMW 08-2026); ElevenLabs и
# apiframe с 07-2026 отдают 403. Порядок переопределяется --provider.
DEFAULT_ORDER = ["sunoapi", "elevenlabs", "apiframe"]
# fal/acedata — добавить при необходимости (функция в PROVIDERS + имя ключа в PROVIDER_KEYS)


def generate(prompt: str, duration_s: float, out_path: Path,
             order: list[str] | None = None, **kw) -> bool:
    _load_env()
    order = order or DEFAULT_ORDER
    for prov in order:
        fn = PROVIDERS.get(prov)
        if not fn:
            print(f"music: неизвестный провайдер '{prov}' — доступны: "
                  f"{', '.join(PROVIDERS)}", file=sys.stderr)
            continue
        key_name = PROVIDER_KEYS.get(prov)
        if key_name and not os.environ.get(key_name):
            print(f"music: '{prov}' пропущен — нет {key_name} в .env")
            continue
        print(f"music: пробую провайдер '{prov}'…")
        try:
            if fn(prompt, duration_s, out_path, **({} if prov != "sunoapi" else
                  {"callback_url": kw.get("callback_url")})):
                print(f"✓ музыка от '{prov}' → {out_path.name}")
                return True
        except Exception as e:  # noqa: BLE001
            print(f"{prov}: {e}", file=sys.stderr)
    print("✗ ни один музыкальный провайдер не сработал — проверь ключи в .env. "
          "Проверенный путь: SUNOAPI_ORG_KEY + SUNO_CALLBACK_URL (любой публичный "
          "https-URL, результат забирается поллингом). Код 1010 от sunoapi.org = "
          "Cloudflare режет User-Agent.", file=sys.stderr)
    return False


# ---------- ducking (sidechaincompress) --------------------------------------

def duck_under_voice(video_path: Path, music_path: Path, out_path: Path,
                     music_gain_db: float = -12.0, ratio: float = 8.0,
                     memes: list[dict] | None = None) -> bool:
    """Подмешать music_path в аудио video_path с ducking под голос видео.

    Голос видео = sidechain-ключ: когда есть речь, музыка автоматически
    приседает. music_gain_db — базовая громкость музыки (тише голоса).
    Музыка зацикливается/обрезается под длину видео.

    memes: список {file, start, duration, gain_db} — звук мема подмешивается
    в свой момент; на время мема МУЗЫКА глушится (Богдан: «звук мема вместо
    музыки, голос остаётся»). Реализуем через volume-энвелоп музыки = 0 в
    окне мема + добавление меm-аудио с adelay.
    """
    memes = memes or []
    inputs = ["-i", str(video_path), "-i", str(music_path)]
    for m in memes:
        inputs += ["-i", str(m["file"])]

    parts = []
    # музыка: зацикл + базовая громкость; если есть мемы — глушим в их окнах
    music_chain = f"[1:a]aloop=loop=-1:size=2e9,volume={music_gain_db}dB"
    if memes:
        # volume=0 внутри каждого окна мема (enable), иначе как есть
        cond = "+".join(f"between(t,{float(m['start']):.3f},{float(m['start'])+float(m['duration']):.3f})"
                        for m in memes)
        music_chain += f",volume=0:enable='{cond}'"
    parts.append(music_chain + "[mus]")
    parts.append("[0:a]asplit=2[voc][sc]")
    parts.append(f"[mus][sc]sidechaincompress=threshold=0.03:ratio={ratio}:attack=5:release=300[ducked]")

    mix_inputs = "[voc][ducked]"
    for j, m in enumerate(memes):
        idx = 2 + j  # 0=video,1=music
        delay_ms = int(float(m["start"]) * 1000)
        gain = float(m.get("gain_db", 0.0))
        parts.append(
            f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume={gain}dB[meme{j}]"
        )
        mix_inputs += f"[meme{j}]"
    n_mix = 2 + len(memes)
    parts.append(f"{mix_inputs}amix=inputs={n_mix}:duration=first:dropout_transition=0:normalize=0[aout]")

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"ducking music под голос → {out_path.name} (music {music_gain_db}dB, "
          f"ratio {ratio}, memes={len(memes)})")
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if p.returncode != 0:
        print(p.stderr.decode()[-1000:], file=sys.stderr)
        return False
    return True


# ---------- выбор самого энергичного окна трека ------------------------------

# ebur128 печатает в stderr строки вида:
#   [Parsed_ebur128_0 @ 0x...] t: 1.2  TARGET:-23 LUFS  M: -23.4 S: ... I: ... LRA: ...
# где t — время (сек), M — momentary loudness (LUFS, ~окно 400мс, шаг ~100мс).
# M: может писаться вплотную (M:-120.7) или с пробелом (M: -62.2); между t и M
# стоит блок TARGET — поэтому ловим t и M отдельными группами в одной строке.
_T_RE = re.compile(r"\bt:\s*([-\d.]+)")
_M_RE = re.compile(r"\bM:\s*(-?[\d.]+|-?inf|nan)")


def _measure_momentary(music_path: Path) -> list[tuple[float, float]]:
    """Прогнать ebur128 по треку, вернуть [(t_sec, momentary_lufs), ...].

    Очень тихие участки ebur128 отдаёт как -inf/-120 — нормализуем к -120 dB."""
    cmd = [
        ffmpeg_bin("ffmpeg"), "-nostats", "-hide_banner",
        "-i", str(music_path),
        "-filter_complex", "ebur128=peak=none",
        "-f", "null", "-",
    ]
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    samples: list[tuple[float, float]] = []
    for ln in p.stderr.decode(errors="ignore").splitlines():
        if "M:" not in ln:
            continue
        mt = _T_RE.search(ln)
        mm = _M_RE.search(ln)
        if not (mt and mm):
            continue
        t = float(mt.group(1))
        try:
            val = float(mm.group(1))
        except ValueError:
            val = -120.0  # -inf / nan
        if val != val or val < -120.0:  # nan / -inf
            val = -120.0
        samples.append((t, val))
    return samples


def _track_duration(music_path: Path) -> float:
    """Длительность трека в секундах через ffprobe."""
    cmd = [
        ffmpeg_bin("ffprobe"), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(music_path),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(p.stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


def find_best_window(music_path: Path, clip_len_sec: float) -> dict:
    """Найти offset (сек), с которого окно длиной clip_len_sec самое «энергичное».

    Алгоритм: ebur128 даёт momentary loudness (LUFS) примерно каждые 100мс.
    Считаем скользящее среднее громкости по окну clip_len_sec и берём начало
    окна с максимумом — так избегаем тихого интро.

    Возвращает dict:
        offset      — секунды, с которых стартовать музыку
        need_loop   — True если трек короче clip_len (нужен loop, offset=0)
        track_len   — длительность трека
        score_lufs  — средняя громкость лучшего окна (для отладки)
    """
    music_path = Path(music_path)
    if not music_path.exists():
        sys.exit(f"Музыкальный файл не найден: {music_path}")
    if clip_len_sec <= 0:
        sys.exit("Длительность окна должна быть положительной (--duration)")

    track_len = _track_duration(music_path)
    if track_len and track_len < clip_len_sec:
        return {"offset": 0.0, "need_loop": True,
                "track_len": track_len, "score_lufs": None}

    samples = _measure_momentary(music_path)
    if not samples:
        sys.exit("Не удалось измерить громкость трека (ebur128 не дал данных) — "
                 "проверь файл и установку ffmpeg")

    # Если измеренная длина меньше окна — тоже рекомендуем loop.
    measured_len = samples[-1][0]
    if measured_len < clip_len_sec:
        return {"offset": 0.0, "need_loop": True,
                "track_len": track_len or measured_len, "score_lufs": None}

    times = [t for t, _ in samples]
    vals = [v for _, v in samples]
    n = len(samples)

    best_offset = 0.0
    best_score = float("-inf")
    # Каждый старт окна = одна точка измерения; правую границу ищем бинарно по t.
    import bisect
    for i in range(n):
        start_t = times[i]
        end_t = start_t + clip_len_sec
        if end_t > times[-1]:
            break  # окно выходит за трек
        j = bisect.bisect_right(times, end_t)
        window = vals[i:j]
        if not window:
            continue
        score = sum(window) / len(window)
        if score > best_score:
            best_score = score
            best_offset = start_t

    return {"offset": round(best_offset, 3), "need_loop": False,
            "track_len": track_len, "score_lufs": round(best_score, 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Генерация фоновой музыки + ducking")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("prompt")
    g.add_argument("--duration", type=float, default=56.0)
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--provider", default=None, help="форсировать провайдера")
    g.add_argument("--callback", default=None, help="callBackUrl для sunoapi.org")

    d = sub.add_parser("duck")
    d.add_argument("video", type=Path)
    d.add_argument("music", type=Path)
    d.add_argument("-o", "--out", type=Path, required=True)
    d.add_argument("--music-db", type=float, default=-12.0)
    d.add_argument("--ratio", type=float, default=8.0)
    d.add_argument("--meme", action="append", default=[],
                   help="звук мема: 'file.mp4@START:DUR[:GAINdB]' (можно несколько)")

    bw = sub.add_parser("bestwindow",
                        help="найти offset самого энергичного окна трека")
    bw.add_argument("music", type=Path)
    bw.add_argument("--duration", type=float, required=True,
                    help="длина окна (сек) = длительность клипа")
    bw.add_argument("--json", action="store_true", help="вывести dict как JSON")

    args = ap.parse_args()
    if args.cmd == "generate":
        order = [args.provider] if args.provider else None
        ok = generate(args.prompt, args.duration, args.out, order=order,
                      callback_url=args.callback)
        sys.exit(0 if ok else 1)
    elif args.cmd == "duck":
        memes = []
        for spec in args.meme:
            # 'file@START:DUR[:GAIN]'
            fp, rest = spec.rsplit("@", 1)
            bits = rest.split(":")
            m = {"file": fp, "start": float(bits[0]), "duration": float(bits[1])}
            if len(bits) > 2:
                m["gain_db"] = float(bits[2])
            memes.append(m)
        ok = duck_under_voice(args.video, args.music, args.out,
                              music_gain_db=args.music_db, ratio=args.ratio,
                              memes=memes)
        sys.exit(0 if ok else 1)
    elif args.cmd == "bestwindow":
        res = find_best_window(args.music, args.duration)
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            print(f"offset={res['offset']}")
            print(f"need_loop={res['need_loop']}")
            if res["need_loop"]:
                print(f"трек короче окна ({res['track_len']:.1f}с < "
                      f"{args.duration:.1f}с) — стартуй с 0 и зацикли музыку")
            else:
                print(f"score_lufs={res['score_lufs']}  track_len={res['track_len']:.1f}с")
        sys.exit(0)


if __name__ == "__main__":
    main()
