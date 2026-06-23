# Gemini Deep Research — выжимка по word-boundary / семантика / русская речь

Источник: ручной Gemini-ресёрч от пользователя, май 2026 (см. `05_word_boundary_methodology_gemini_RAW.txt`).

## TL;DR

CTC-модели (GigaAM) дают **лингвистические** границы. Для монтажа нужны
**акустические** и **семантические**. Разрыв между ними и есть причина
рваного монтажа. Решение — 5 слоёв защиты поверх raw transcripts.

## Главные находки (по приоритету внедрения)

### 1. ⭐ Smart Padding — асимметричный, по последней букве слова

**Descript-стиль (industry standard):**
- Гласные на конце слова (`а/о/у/и/е/я`) → **+30мс post-pad** (срез чистый)
- Шипящие/мягкий знак/-ть/-ся/-сь (`ть/ся/сь/ш/щ/ч/ц/ь`) → **+120мс** (нужно
  сохранить глухие шипящие — они звучат дольше после word.end в ASR)
- Прочие согласные → **+50мс**
- Pre-pad (до слова) → фиксированно **30-50мс** (захват микро-смыкания губ)

**Это лучше моего текущего фикс 100/150**. Применяется в `apply_padding.py`.

### 2. ⭐ Семантический чёрный список (нельзя резать внутри синтагмы)

Editor sub-agent должен **жёстко запрещать**:
- ❌ Cut между прилагательным и существительным («в большой [CUT] машине»)
- ❌ Cut между предлогом и существительным («в [CUT] кабинете»)
- ❌ Cut между подлежащим и сказуемым

Только разрешено:
- ✅ На границе clauses (простых предложений внутри сложного)
- ✅ На завершённой мысли (Final Lowering F0 — интонация падает вниз и затихает)

Применяется в `editor_sub_agent_brief.py` — добавить в `<rules>`.

### 3. ⭐ Hanning curve в audio fades (вместо tri)

Текущий код в `render.py:188`:
```python
af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_start:.3f}:d=0.03"
```

Должно быть:
```python
af = (f"afade=t=in:st=0:d=0.03:curve=hsin,"
      f"afade=t=out:st={fade_out_start:.3f}:d=0.03:curve=hsin")
```

`hsin` (half-sine, эквивалент hanning) глаже сглаживает фазу. По умолчанию
ffmpeg использует `tri` (линейный) который может оставлять микро-щелчки на
zero-crossing boundary.

### 4. Audio-pop detection — onset + RMS-delta (а не только RMS)

Мой `detect_audio_spikes.py` сейчас смотрит только max RMS в окне. Gemini
рекомендует **двухступенчатую** проверку:

```python
# 1. Onset detection — клики имеют широкую полосу частот
onsets = librosa.onset.onset_detect(y=y, sr=sr, hop_length=128, backtrack=False)

# 2. RMS-delta peaks — резкие изменения энергии за 1 frame
rms_delta = np.abs(np.diff(librosa.feature.rms(y=y)[0]))
peaks, _ = scipy.signal.find_peaks(rms_delta, height=0.05)
```

Только если **обе проверки** дают peak в окне cut'а ±30мс → real spike.

### 5. Final Lowering (F0) — детектор завершённой мысли

Через `librosa.pyin` отслеживаем тренд F0 (фундаментальной частоты) в
последних 0.3с фразы:

```python
f0, voiced_flag, voiced_probs = librosa.pyin(y, fmin=65, fmax=2093)
valid_f0 = f0[voiced_flag]
if len(valid_f0) > 5:
    trend = np.polyfit(np.arange(len(valid_f0[-5:])), valid_f0[-5:], 1)[0]
    if trend < -0.5:
        # Интонация падает — мысль завершена → safe cut point
```

Применяется в `build_editable_transcript.py` — помечать каждую фразу
маркером ✅ (safe end) или ⚠️ (thought continues).

## Что НЕ делать (чёрный список из Gemini)

| ❌ Не делать | Почему |
|---|---|
| `-150мс` симметричный padding | Захватит вздох или начало следующего слова. Только асимметрично. |
| Cut внутри синтагмы (прилаг+сущ) | Слушается «оборванно» — синтагма у носителя русского неделима. |
| VAD на шумном фоне | Размажет границы свистящих, обрежет шипящие. |
| `-c copy` concat без перекодирования | Glitch'и на GOP boundary (зависание видео на полсекунды). |
| `afade ... curve=tri` (default) | Линейный — оставляет click'и. Использовать `hsin`. |

## Что встроено (сразу после получения research)

1. ✅ `apply_padding.py --smart` режим (Smart Padding по последней букве)
2. ✅ `render.py` — `hsin` curve в afade
3. ✅ `editor_sub_agent_brief.py` — чёрный список синтагм в `<rules>`
4. ✅ `detect_audio_spikes.py` — onset + RMS-delta dual-check
5. ⏳ `build_editable_transcript.py` — F0 pitch annotations (roadmap, нужно ~30 строк)

## Что в roadmap (advanced)

- **Forced Alignment через MFA** — точность до фонемы (Descript-уровень).
  Тяжёлая зависимость (~500 МБ модель), но даёт +30% точности cut'ов.
- **DeepPavlov russian sentence boundary** — модель для детекции точки в
  потоке речи через BERT.
- **Полноценный L-cut / J-cut helper** — через `filter_complex` с
  раздельными video+audio концатенациями (Gemini показывает рабочую команду).
