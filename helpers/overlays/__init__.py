"""Overlay runners для Montazh_Agent.

Каждый runner — отдельный модуль, инкапсулирующий конкретный engine:
- manim_runner: математика/диаграммы/equations
- remotion_runner: React/CSS композиции (product UI motion, brand kits)
- hyperframes_runner: browser-native HTML/CSS/GSAP, кинетическая типографика
- pil_subs: простые PNG-overlays через PIL — субтитры, бейджи, counters

Каждый runner запускается агентом в отдельном parallel sub-agent (Hard Rule #10).
Каждый overlay = свой slot в edit/animations/slot_<id>/.

See SKILL.md «Animations» секцию для палитры, продолжительности, easing.
"""
