# What to Eat? dish data

Builds the dish list for the What to Eat? iOS app and publishes it with GitHub Pages:

```
https://<your-github-username>.github.io/whattoeat-data/dishes.json
```

## How it works

Every Monday (or when you press **Run workflow**), GitHub Actions runs `build_dishes.py`:

1. **Curated dishes** come from `dish-seed.json`. Their names, descriptions, emoji and tags are hand-checked and never overwritten.
2. **New dishes:** Gemini suggests popular dishes for each country, with English and Vietnamese names, a short description, an emoji and spicy/soup/vegetarian tags. Each suggestion is kept only if [QLever](https://qlever.dev) finds its English Wikipedia article on Wikidata and Wikidata classes it as food, so made-up dishes are dropped. Kept dishes are added to `discovered.json`, until each country has 30.
3. **Photos and links:** QLever adds a Wikimedia Commons photo and English/Vietnamese Wikipedia links to every dish.
4. The result is committed to `public/dishes.json` and deployed to GitHub Pages. `generatedAt` only changes when the dishes do.

Without a Gemini key, steps 1, 3 and 4 still run.

## Setup

1. Create a **public** repository named `whattoeat-data` and push this folder to it.
2. **Settings → Secrets and variables → Actions → New repository secret:** name `GEMINI_API_KEY`, value is a key from [Google AI Studio](https://aistudio.google.com/apikey).
3. Optional: **Variables** tab, add `GEMINI_MODEL` to use another model. The default is `gemini-3.5-flash-lite`.
4. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
5. **Actions → Update dishes → Run workflow.**

## Editing

- Fix a discovered dish: edit it in `discovered.json`, or move it into `dish-seed.json` to make it curated.
- Remove a discovered dish: delete it from `discovered.json`. To stop it coming back, add it to `dish-seed.json` instead.
- Add a country: add it to `countries` in `dish-seed.json` (code, flag, English and Vietnamese name).

Run locally:

```bash
python3 build_dishes.py --no-ai                 # curated dishes only
GEMINI_API_KEY=... python3 build_dishes.py      # with discovery
```

## Licenses

- Wikidata data: CC0.
- Photos: Wikimedia Commons, each under its own license. The app links to each photo's page with its author and license.
- Curated English descriptions partly come from Wikipedia (CC BY-SA 4.0).
- Text suggested by Gemini is checked against Wikidata, but descriptions may still need a human look.
