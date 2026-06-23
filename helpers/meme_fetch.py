"""Поиск и загрузка видео/картинок-мемов под ролики.

Источник по умолчанию — KLIPY (бесплатно, коммерция ок, отдаёт mp4 напрямую).
Архитектура с заменяемым провайдером: добавить Vlipsy/Tenor — дописать функцию
в PROVIDERS и ключ в .env. Никаких ключей в коде — читаются из окружения/.env.

Два способа задать мем в сценарии (парсит parse_meme_cues.py):
  1. Эмодзи:  [мем:🤯]  → EMOJI_QUERIES['🤯'] = "mind blown"
  2. Текст:   [мем: кот печатает]  или  [meme: confused math lady]

Каждый скачанный мем кэшируется в <edit>/memes/<hash>.mp4 + manifest.json
(Hard Rule #13 — детерминизм генеративного/внешнего контента).

CLI:
    python helpers/meme_fetch.py "mind blown" --edit-dir <edit> --kind clips
    python helpers/meme_fetch.py "🤯" --edit-dir <edit>        # эмодзи → запрос
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


# ---------- env / ключи -------------------------------------------------------

def _load_env(edit_dir: Path | None = None) -> None:
    """Подтянуть .env из корня Montazh_Agent (и опц. из edit_dir) в os.environ.
    Не перетирает уже выставленные переменные окружения."""
    candidates = []
    # корень проекта = два уровня вверх от helpers/
    candidates.append(Path(__file__).resolve().parent.parent / ".env")
    if edit_dir:
        candidates.append(Path(edit_dir) / ".env")
    for env_path in candidates:
        if not env_path.exists():
            continue
        for ln in env_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k not in os.environ:
                os.environ[k] = v


# ---------- эмодзи → поисковый запрос ----------------------------------------
# Расширяемый словарь. Если эмодзи нет — парсер попросит текстовый запрос.
EMOJI_QUERIES: dict[str, str] = {
    "🤯": "mind blown",
    "😱": "shocked scared",
    "😂": "laughing hard",
    "🤣": "rolling laughing",
    "😎": "cool sunglasses deal with it",
    "🤔": "thinking hmm",
    "🙄": "eye roll annoyed",
    "😴": "bored sleeping",
    "🔥": "fire lit awesome",
    "💀": "dead dying laughing skull",
    "👀": "side eye looking",
    "🤡": "clown",
    "💸": "money flying spending",
    "🚀": "rocket to the moon",
    "🤷": "shrug i dont know",
    "👏": "slow clap applause",
    "🥳": "party celebration",
    "😬": "awkward grimace",
    "🤓": "nerd actually",
    "😏": "smug smirk",
    "🧠": "big brain galaxy",
    "✅": "done checkmark yes",
    "❌": "no nope wrong",
}


def query_from_cue(cue: str) -> str:
    """Преобразовать cue (эмодзи или текст) в поисковый запрос для провайдера."""
    cue = cue.strip()
    if cue in EMOJI_QUERIES:
        return EMOJI_QUERIES[cue]
    # одиночный эмодзи без словаря — вернём как есть (KLIPY ищет и по эмодзи)
    return cue


# ---------- провайдеры --------------------------------------------------------

def _http_get_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Montazh_Agent/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def klipy_search(query: str, kind: str = "clips", limit: int = 8,
                 rating: str = "pg-13") -> list[dict]:
    """KLIPY search. kind ∈ {'clips','gifs'}. Возвращает нормализованные кандидаты:
    [{provider, title, mp4, gif, width, height, source_url}, ...]

    clips:  data.data[].file.mp4 (строка) + file_meta.mp4.{width,height}
    gifs:   data.data[].file.{hd,md}.mp4.url (вложенно)
    """
    key = os.environ.get("KLIPY_API_KEY")
    if not key:
        raise RuntimeError("KLIPY_API_KEY не найден в окружении/.env")
    if kind not in ("clips", "gifs"):
        kind = "clips"
    q = urllib.parse.quote(query)
    url = (f"https://api.klipy.com/api/v1/{key}/{kind}/search"
           f"?q={q}&per_page={limit}&customer_id=montazh_agent&rating={rating}")
    data = _http_get_json(url)
    if not data.get("result"):
        return []
    items = (data.get("data") or {}).get("data") or []
    out: list[dict] = []
    for it in items:
        f = it.get("file") or {}
        mp4 = gif = None
        w = h = None
        if isinstance(f.get("mp4"), str):           # clips: плоская строка
            mp4 = f.get("mp4")
            gif = f.get("gif") if isinstance(f.get("gif"), str) else None
            fm = (it.get("file_meta") or {}).get("mp4") or {}
            w, h = fm.get("width"), fm.get("height")
        else:                                        # gifs: вложенно hd/md
            best = f.get("hd") or f.get("md") or {}
            mp4o = best.get("mp4") or {}
            gifo = best.get("gif") or {}
            mp4 = mp4o.get("url")
            gif = gifo.get("url")
            w, h = mp4o.get("width"), mp4o.get("height")
        if mp4 or gif:
            out.append({
                "provider": "klipy",
                "kind": kind,
                "title": it.get("title") or it.get("slug") or query,
                "mp4": mp4,
                "gif": gif,
                "width": w,
                "height": h,
                "source_url": it.get("url"),
            })
    return out


# Реестр провайдеров. Добавить Vlipsy/Tenor — дописать функцию и строку здесь.
PROVIDERS = {
    "klipy": klipy_search,
}


def search_meme(query: str, kind: str = "clips", limit: int = 8,
                provider_order: list[str] | None = None) -> list[dict]:
    """Искать мем по цепочке провайдеров до первого с результатами."""
    order = provider_order or ["klipy"]
    errors = []
    for prov in order:
        fn = PROVIDERS.get(prov)
        if not fn:
            continue
        try:
            res = fn(query, kind=kind, limit=limit)
            if res:
                return res
        except Exception as e:  # noqa: BLE001
            errors.append(f"{prov}: {e}")
    if errors:
        print("meme_fetch warnings:", "; ".join(errors), file=sys.stderr)
    return []


# ---------- скачивание + кэш + manifest --------------------------------------

def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Montazh_Agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())


def fetch_and_cache(cue: str, edit_dir: Path, kind: str = "clips",
                    prefer: str = "mp4", index: int = 0) -> dict | None:
    """Найти мем по cue, скачать лучший кандидат в <edit>/memes/, записать manifest.

    Возвращает {path, manifest_path, title, width, height} или None.
    `index` — какой из кандидатов взять (0 = первый/самый релевантный).
    `prefer` — 'mp4' (видео-мем) или 'gif'.
    """
    _load_env(edit_dir)
    query = query_from_cue(cue)
    candidates = search_meme(query, kind=kind)
    if not candidates:
        # для видео-мема пусто → пробуем gifs как запас
        if kind == "clips":
            candidates = search_meme(query, kind="gifs")
        if not candidates:
            print(f"meme_fetch: ничего не найдено по '{cue}' → '{query}'", file=sys.stderr)
            return None
    cand = candidates[min(index, len(candidates) - 1)]
    media_url = cand.get(prefer) or cand.get("mp4") or cand.get("gif")
    if not media_url:
        return None

    ext = ".mp4" if media_url.lower().split("?")[0].endswith("mp4") else \
          (".gif" if media_url.lower().split("?")[0].endswith("gif") else ".mp4")
    memes_dir = Path(edit_dir) / "memes"
    memes_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(media_url.encode()).hexdigest()[:16]
    dest = memes_dir / f"{h}{ext}"
    if not dest.exists():
        _download(media_url, dest)

    checksum = hashlib.sha256(dest.read_bytes()).hexdigest()
    manifest = {
        "cue": cue,
        "query": query,
        "provider": cand.get("provider"),
        "kind": cand.get("kind"),
        "title": cand.get("title"),
        "source_url": cand.get("source_url"),
        "media_url": media_url,
        "width": cand.get("width"),
        "height": cand.get("height"),
        "checksum_sha256": checksum,
        "file": dest.name,
    }
    manifest_path = memes_dir / f"{h}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return {
        "path": str(dest),
        "manifest_path": str(manifest_path),
        "title": cand.get("title"),
        "width": cand.get("width"),
        "height": cand.get("height"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Найти и скачать мем (KLIPY)")
    ap.add_argument("cue", help="эмодзи (🤯) или текстовый запрос ('confused math lady')")
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--kind", choices=["clips", "gifs"], default="clips")
    ap.add_argument("--prefer", choices=["mp4", "gif"], default="mp4")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--list", action="store_true", help="показать кандидатов, не скачивать")
    args = ap.parse_args()

    _load_env(args.edit_dir)
    if args.list:
        q = query_from_cue(args.cue)
        for i, c in enumerate(search_meme(q, kind=args.kind)):
            print(f"  [{i}] {c['title']}  {c.get('width')}x{c.get('height')}  {c.get('mp4') or c.get('gif')}")
        return
    res = fetch_and_cache(args.cue, args.edit_dir, kind=args.kind,
                          prefer=args.prefer, index=args.index)
    if res:
        print(f"✓ {res['path']}  ({res.get('width')}x{res.get('height')})  «{res['title']}»")
    else:
        sys.exit("✗ мем не найден")


if __name__ == "__main__":
    main()
