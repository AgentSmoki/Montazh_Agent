# Письмо для partnerships@vlipsy.com (запрос API-доступа)

**To:** partnerships@vlipsy.com
**Subject:** API access request — automated meme insertion for short-form video editor

---

Hello Vlipsy team,

I'm building an automated short-form video editing tool (Reels / TikTok / YouTube Shorts) that inserts reaction memes and meme video clips into creators' videos based on simple cues in their script (an emoji or a short text like "insert the mind-blown meme").

I'd like to integrate the Vlipsy API as a source of HD video memes and reaction clips. Could you share:

1. **API documentation** — base URL, authentication, search endpoint, response format (where the MP4/WebM file URLs are).
2. **Access / API key** — how to obtain a key and any onboarding steps.
3. **Pricing** — free tier limits and paid plans, if any.
4. **Licensing for commercial use** — we produce videos for paying clients, so we need clarity on whether the clips can be embedded into commercially distributed content, and any attribution requirements.
5. **Rate limits** — requests per minute/day.

Our expected volume initially is modest (a few hundred clip lookups per month, cached on our side to avoid repeated calls).

Happy to share more about the product or sign any required agreement.

Thank you,
Bogdan
[ваш контактный email / Telegram]

---

## Статус
- [ ] Отправлено: ____ (дата)
- [ ] Ответ получен: ____
- [ ] Ключ/доки получены → добавить провайдер `vlipsy` в `helpers/meme_fetch.py` (PROVIDERS dict) и `VLIPSY_API_KEY` в `.env`

> Пока ждём — основной источник мемов KLIPY (работает, бесплатно, коммерция ок). Vlipsy добавим как доп. провайдер, когда дадут доступ.
