"""Каталог форматов и pipeline'ов «контент-завода».

Извлечён из созвона Богдан × Дмитрий (2026-05-23, длительность ~51 мин),
где Дмитрий описал свою систему производства контента.

Главный принцип: «контент-завод» = набор агентов + сценарии под каждый формат.
На входе — тема/бриф/референс; на выходе — либо готовый ролик, либо набор
исходников для быстрого ручного монтажа.

Эти пресеты используются:
- агентом в mode dispatch (см. SKILL.md «Mode dispatch»)
- helpers/format_recommender.py для генерации подсказок пользователю
- helpers/broll_generator.py для выбора генеративных моделей под формат

Каждый пресет — словарь с полями:
  name             — название формата
  description      — короткое описание
  target_audience  — кому подходит
  duration_range   — типичная длительность (sec)
  aspect           — соотношение сторон
  pipeline         — последовательность шагов
  models           — какие MCP-вызовы (Higgsfield / Fal.ai / ElevenLabs / TT)
  budget_usd       — оценка стоимости одного ролика (median)
  hand_off_mode    — "auto_render" (полный авто-рендер) или "raw_sources"
                     (выдать исходники + EDL для ручной склейки в DaVinci/CapCut)
  cta_required     — нужен ли CTA в конце (важно для конверсии в воронку)
"""
from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# ПРЕСЕТЫ ФОРМАТОВ (извлечены из созвона)
# ─────────────────────────────────────────────────────────────────────────────

PRESETS: dict[str, dict[str, Any]] = {

    # ────────── 1. Полностью генеративный (без живых съёмок) ──────────
    "pure_neural": {
        "name": "Полностью нейронный (картинки + анимация)",
        "description": (
            "Тема → сценарий → раскадровка → точки → картинки → анимация → "
            "озвучка → финал. Никаких живых съёмок. Подходит для абстрактных "
            "тем, объяснений, виральных миниатюр."
        ),
        "target_audience": "broad",
        "duration_range": (15, 60),
        "aspect": "9:16",
        "pipeline": [
            "scenario_agent: разбить тему на 5-12 точек/кадров",
            "storyboard_agent: для каждой точки — текстовое описание кадра",
            "image_gen: каждая точка → картинка (Nano Banana Pro / Z-Image / FLUX 2)",
            "animation: каждая картинка → 3-6s клип (Kling 3.0 / Wan 2.6 / Grok для скорости)",
            "tts: озвучка (TeleTranscribe-TTS [свой] / ElevenLabs / Suno fallback)",
            "render: lossless concat + 30ms fades + subs LAST",
            "cta_overlay: добавить CTA-карточку в финал (Hard Rule контент-завода)",
        ],
        "models": {
            "image": ["nano-banana-pro", "z-image", "flux-2"],
            "video": ["kling-3.0", "wan-2.6", "grok-video"],
            "tts": ["tt-tts-own", "elevenlabs"],
        },
        "budget_usd": 0.80,
        "hand_off_mode": "auto_render",
        "cta_required": True,
    },

    # ────────── 2. Нейроблогер (персонаж рассказывает от лица) ──────────
    "neuro_blogger": {
        "name": "Нейроблогер (девочка / парень / динозавр / горилла / банка крема)",
        "description": (
            "Берём готового персонажа (или генерим под бриф) и от его лица "
            "ведём подачу. Lipsync на сгенерированную голову. Удобно "
            "крутить разные ниши с разной 'личностью'."
        ),
        "target_audience": "по нише персонажа",
        "duration_range": (20, 90),
        "aspect": "9:16",
        "pipeline": [
            "character_select: выбрать/сгенерить персонажа (Nano Banana Pro)",
            "script: написать монолог от лица персонажа",
            "tts: озвучка с подобранным под персонажа голосом (ElevenLabs voice_id)",
            "lipsync: LatentSync (OSS) или Sync.so (hosted) на character image + audio",
            "broll_inserts: 30% времени — context-кадры (Kling/Wan) для разнообразия",
            "render: per-segment extract + subs + CTA",
        ],
        "models": {
            "image": ["nano-banana-pro"],
            "lipsync": ["latentsync", "sync.so", "hedra"],
            "tts": ["elevenlabs"],
            "video": ["kling-3.0"],
        },
        "budget_usd": 1.20,
        "hand_off_mode": "auto_render",
        "cta_required": True,
    },

    # ────────── 3. Сюжетно-хайповый (привязка к большим зданиям) ──────────
    "story_hype_iconic": {
        "name": "Сюжетный хайп с привязкой к достопримечательностям",
        "description": (
            "Live-съёмка реального места (Эйфелева башня, Волгоград, любой "
            "knowable landmark) + нейронка добавляет туда трансформера / "
            "инопланетянина из 'Войны миров' / гигантского динозавра. "
            "Очень виральный формат, набирает миллионы — но СЛАБАЯ конверсия "
            "в лиды (Богдан: 'забил, но никаких переходов')."
        ),
        "target_audience": "виральный, для роста подписчиков",
        "duration_range": (5, 20),
        "aspect": "9:16",
        "pipeline": [
            "live_capture: пользователь снимает кадр с достопримечательностью",
            "scene_brief: описать что добавить (трансформер? пришельцы?)",
            "video_extend: image-to-video с last-frame conditioning (Veo 3.1)",
            "compositing: ffmpeg overlay (PTS-shifted, Hard Rule #4)",
            "color_match: per-segment grade для бесшовности",
            "subs: яркие, минимум текста, эмодзи",
            "(CTA не обязателен — это не lead-gen формат, а top-of-funnel)",
        ],
        "models": {
            "video_extend": ["veo-3.1-fast", "kling-3.0", "wan-2.6"],
            "tts": [],  # обычно молча или с музыкой
        },
        "budget_usd": 1.50,  # дороже из-за Veo
        "hand_off_mode": "auto_render",
        "cta_required": False,  # виральный фор, не lead-gen
    },

    # ────────── 4. Экспертный (говорящая голова + слайды/инфографика) ──────────
    "expert_with_infographics": {
        "name": "Экспертный: live talking-head + слайды/инфографика",
        "description": (
            "Самый сильный для lead-gen. Снимаешь себя на тему → накладываешь "
            "поверх своей речи инфографику, скетчи 'нарисованные карандашом', "
            "data-визуализации (как у TED-talk). Кадры чередуются: ты — "
            "инфографика — ты. Лучшая конверсия в воронку."
        ),
        "target_audience": "целевая по продукту, экспертная",
        "duration_range": (30, 180),
        "aspect": "9:16 (или 1:1 / 16:9 для длинных)",
        "pipeline": [
            "live_capture: твоя съёмка (talking head)",
            "transcribe_mcp: транскрипция через TeleTranscribe (word-timestamps)",
            "highlight_extract: выделить пункты для инфографики",
            "infographic_gen: PIL/Manim/Remotion overlay per пункт",
            "alternate_cuts: ты ↔ инфографика, ритм 3-7s",
            "render: subs LAST, CTA в конце",
        ],
        "models": {
            "overlays": ["manim", "remotion", "pil_subs", "hyperframes"],
            "tts": [],  # своя речь
        },
        "budget_usd": 0.30,  # дёшево, потому что нет генерации видео
        "hand_off_mode": "auto_render",
        "cta_required": True,
    },

    # ────────── 5. Чистая говорящая голова ──────────
    "pure_talking_head": {
        "name": "Чистая говорящая голова (минимум монтажа)",
        "description": (
            "Самый простой и базовый формат. Сел — наговорил — субтитры — "
            "выложил. Дмитрий: 'самый дешёвый, кстати, тоже заходит'. "
            "Подходит для регулярного контента, низкого порога входа."
        ),
        "target_audience": "своя аудитория, регулярный",
        "duration_range": (15, 120),
        "aspect": "9:16",
        "pipeline": [
            "live_capture: одна запись",
            "transcribe_mcp: ТТ word-timestamps",
            "auto_cut: убрать паузы/паразиты (см. auto-editor подход)",
            "subs_burn: bold-overlay стиль, 2-словные UPPERCASE",
            "(опц.) CTA в конце",
        ],
        "models": {},
        "budget_usd": 0.05,  # практически бесплатно
        "hand_off_mode": "auto_render",
        "cta_required": True,
    },

    # ────────── 6. Live + нейронка (микс) ──────────
    "live_plus_neural_mix": {
        "name": "Live-съёмки + нейронные вставки (mixed)",
        "description": (
            "У тебя несколько живых видео-съёмок (talking head или action) "
            "+ ты доклеиваешь сгенерированные кадры (B-roll, эмоции, "
            "context-вставки). Гибрид #1 и #4."
        ),
        "target_audience": "разная",
        "duration_range": (30, 90),
        "aspect": "9:16",
        "pipeline": [
            "inventory: несколько live-видео + опц. голосовой track",
            "mode_decision: multi-clip montage или audio-first",
            "transcribe_mcp_all: все live-источники через TT",
            "edl_draft: LLM выбирает highlights по сценарию",
            "broll_gaps: для каждого 'нужен context-кадр' → MCP-вызов "
            "(Higgsfield Kling/Wan/Hailuo)",
            "manifest.json для каждого generated (Hard Rule #13)",
            "render: per-segment + overlays + subs + CTA",
        ],
        "models": {
            "video": ["kling-3.0", "wan-2.6", "hailuo-02"],
            "lipsync_if_needed": ["latentsync"],
        },
        "budget_usd": 0.60,
        "hand_off_mode": "auto_render",
        "cta_required": True,
    },

    # ────────── 7. Анджелина-стиль (фото-приколы) ──────────
    "photo_animation_skit": {
        "name": "Фото-приколы / диалог с собой (Анджелина-стиль)",
        "description": (
            "Берём 2+ фото человека (своих или знаменитостей), оживляем, "
            "ставим диалог между двумя версиями (взрослый-ребёнок, "
            "ты-ты_молодой). Сильный виральный формат, миллионы просмотров. "
            "По Богдану — 'не дают лидов, чисто рост'."
        ),
        "target_audience": "виральный",
        "duration_range": (10, 25),
        "aspect": "9:16",
        "pipeline": [
            "photo_pair: 2-3 фото (родное + сгенерённая 'молодая версия')",
            "dialog_script: 2-3 реплики между ними",
            "tts: разные голоса (ElevenLabs voice_id для каждого 'себя')",
            "image_to_video: каждая фото → 3-5s клип (Kling / Wan)",
            "lipsync: на каждый клип (LatentSync)",
            "shot_reverse_shot: монтаж по правилам диалога (cut on action)",
            "subs: emoji-rich",
        ],
        "models": {
            "image_gen": ["nano-banana-pro"],
            "video": ["kling-3.0", "wan-2.6"],
            "lipsync": ["latentsync", "sync.so"],
            "tts": ["elevenlabs"],
        },
        "budget_usd": 1.80,
        "hand_off_mode": "auto_render",
        "cta_required": False,
    },

    # ────────── 8. Raw-sources (для ручного монтажа в CapCut/DaVinci) ──────────
    "raw_sources_for_manual_edit": {
        "name": "Чистые исходники для ручного монтажа",
        "description": (
            "Богдан: 'программный монтаж даёт нестыковки — лучше выдавать "
            "сгенерированные/обработанные исходники, а финальный монтаж "
            "делает человек в CapCut/DaVinci с эффектами и звуком'. "
            "Этот режим — для тех кто хочет контроль и качество выше, чем "
            "может выдать FFmpeg auto-pipeline."
        ),
        "target_audience": "профессиональные монтажёры",
        "duration_range": (0, 0),  # длительность определяется монтажёром
        "aspect": "любой",
        "pipeline": [
            "scenario_agent: разбивка на N задач",
            "generate_assets: B-roll, инфографика, TTS, lipsync — всё как файлы",
            "organize: каждый asset с manifest.json и осмысленным именем",
            "export_otio: edit.otio с draft-таймлайном для импорта в Resolve/FCP",
            "package: zip-bundle <project>_raw.zip с README для монтажёра",
        ],
        "models": "любые из других пресетов",
        "budget_usd": "переменная (зависит от объёма ассетов)",
        "hand_off_mode": "raw_sources",
        "cta_required": False,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# СТРУКТУРА «КОНТЕНТ-ЗАВОДА» (3 слоя из транскрипта Дмитрия)
# ─────────────────────────────────────────────────────────────────────────────

ARCHITECTURE_LAYERS = {
    "layer_1_neurons": {
        "title": "Слой 1 — Нейронки",
        "description": "Базовые модели для генерации (можно подменять)",
        "current_stack": {
            "image": ["nano-banana-pro", "z-image", "flux-2", "imagen-4"],
            "video": ["kling-3.0", "wan-2.6", "veo-3.1-fast", "hailuo-02",
                      "grok-video", "seedance-2.0"],
            "tts": ["tt-tts-own (Дмитрий)", "elevenlabs"],
            "music": ["suno", "udio"],
            "lipsync": ["latentsync", "sync.so", "hedra"],
        },
        "swap_cost": "low — модели меняются за минуты в helpers/broll_generator.py",
    },

    "layer_2_system": {
        "title": "Слой 2 — Система производства",
        "description": (
            "Агентная оркестрация. Самопиcные agents (OpenClaw / Claude Code) "
            "выполняют последовательные шаги: scenario → storyboard → asset_gen "
            "→ assemble → upload. На вход — команда + бриф, на выходе — готовый "
            "файл (или upload на Google Drive)."
        ),
        "current_implementation": (
            "Montazh_Agent (Claude Code skill) + parallel sub-agents через "
            "Agent tool. См. helpers/* и SKILL.md."
        ),
        "alternatives": ["OpenClaw", "n8n + LangChain", "Make.com"],
    },

    "layer_3_formats": {
        "title": "Слой 3 — Форматы (главное)",
        "description": (
            "Каждый формат — отдельный pipeline + presets + voice/style guide. "
            "Самая важная часть, потому что вариаций бесконечно много. См. "
            "PRESETS словарь в этом файле."
        ),
        "current_count": len(PRESETS),
        "extendable": True,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# ПРАВИЛА КОНВЕРСИИ (из созвона: «миллионы просмотров без переходов = ничто»)
# ─────────────────────────────────────────────────────────────────────────────

CONVERSION_RULES = [
    {
        "rule": "Целевая аудитория > вирусность",
        "explanation": (
            "Лучше 1k просмотров от ЦА с 200 переходами, чем 1M просмотров "
            "от 'всех подряд' с 0 переходами. Делать контент под нишу продукта."
        ),
    },
    {
        "rule": "CTA в конце обязателен для lead-gen форматов",
        "explanation": (
            "Без CTA пользователь не знает что делать дальше. Стандартные CTA: "
            "'Получи гайд по ссылке в шапке', 'Зайди в бота — расшифрую твой "
            "сон', 'Подпишись на канал — там разборы'."
        ),
        "applied_to": ["pure_neural", "neuro_blogger", "expert_with_infographics",
                       "pure_talking_head", "live_plus_neural_mix"],
    },
    {
        "rule": "Виральные форматы — для top-of-funnel, не для конверсии",
        "explanation": (
            "story_hype_iconic и photo_animation_skit набирают миллионы, но "
            "конвертят слабо — потому что аудитория случайная. Использовать "
            "для роста подписчиков, а конверсию делать через регулярные "
            "expert/talking-head ролики."
        ),
        "applied_to": ["story_hype_iconic", "photo_animation_skit"],
    },
    {
        "rule": "Анализ конкурентов перед production",
        "explanation": (
            "Перед запуском контент-завода — пройтись по YouTube/TikTok каналам "
            "конкурентов, отобрать топ-хайповые ролики, проанализировать что "
            "сработало. См. helpers/analyze_reels.py."
        ),
    },
]


def list_presets() -> list[str]:
    """Все доступные ключи пресетов."""
    return list(PRESETS.keys())


def get_preset(key: str) -> dict[str, Any]:
    """Один пресет по ключу. KeyError если нет."""
    if key not in PRESETS:
        raise KeyError(
            f"Неизвестный пресет: {key}. Доступные: {', '.join(list_presets())}"
        )
    return PRESETS[key]


def filter_by_use_case(use_case: str) -> list[str]:
    """Фильтр пресетов по use-case: 'lead_gen' / 'viral_growth' / 'manual_edit'."""
    if use_case == "lead_gen":
        return [k for k, v in PRESETS.items() if v["cta_required"]]
    if use_case == "viral_growth":
        return [k for k, v in PRESETS.items()
                if not v["cta_required"] and v["hand_off_mode"] == "auto_render"]
    if use_case == "manual_edit":
        return [k for k, v in PRESETS.items() if v["hand_off_mode"] == "raw_sources"]
    raise ValueError(f"unknown use_case: {use_case}")


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for key, p in PRESETS.items():
            print(f"\n=== {key} ===")
            print(f"  {p['name']}")
            print(f"  Длительность: {p['duration_range'][0]}-{p['duration_range'][1]}s, "
                  f"бюджет ~${p['budget_usd']}, CTA: {p['cta_required']}")
            print(f"  {p['description']}")
    elif len(sys.argv) > 1 and sys.argv[1] in PRESETS:
        print(json.dumps(PRESETS[sys.argv[1]], ensure_ascii=False, indent=2))
    else:
        print(f"Загружено пресетов: {len(PRESETS)}")
        print(f"Архитектура: {list(ARCHITECTURE_LAYERS.keys())}")
        print(f"Правил конверсии: {len(CONVERSION_RULES)}")
        print("\nИспользование:")
        print("  python helpers/content_factory_presets.py --list")
        print("  python helpers/content_factory_presets.py <preset_key>")
