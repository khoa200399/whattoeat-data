# What to Eat? dish data

Builds the dish list for the What to Eat? iOS app and publishes it with GitHub Pages:

```
https://<your-github-username>.github.io/whattoeat-data/dishes.json
```

## How it works

Every day at midnight Vietnam time (or when you press **Run workflow**), GitHub Actions runs `build_dishes.py`:

1. **Curated dishes** come from `dish-seed.json`. Their names, descriptions, emoji and tags are hand-checked and never overwritten.
2. **New dishes:** Gemini suggests popular dishes for each country, with English and Vietnamese names, a short description, an emoji and tags from `tags.json`. Each suggestion is kept only if [QLever](https://qlever.dev) finds its English Wikipedia article on Wikidata and Wikidata classes it as food, so made-up dishes are dropped. Kept dishes are added to `discovered.json`, until each country has 30.
3. **Tags:** `tags.json` lists the tags (id, emoji, English/Vietnamese name, a hint for Gemini, and how the app filters with it: `exclude` like "No spice", `include` like "Vegetarian"). Gemini answers each (dish, tag) pair once, in batches, and the answers are saved in `auto-tags.json`. Add a tag and the next run tags every dish for it; the app gets a new filter chip without an app update. Curated dishes keep their hand-set tags for spicy/soup/vegetarian and are only auto-tagged for newer tags.
4. **Photos and links:** QLever adds a Wikimedia Commons photo and English/Vietnamese Wikipedia links to every dish.
5. The result is committed to `public/dishes.json` and deployed to GitHub Pages. `generatedAt` only changes when the dishes do.

Without a Gemini key, steps 1, 4 and 5 still run, and tags use the answers already saved.

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
- Add a tag: add it to `tags.json`. Remove one: delete it there (old answers stay in `auto-tags.json` but are ignored).
- Fix a tag on a dish: set the value in `auto-tags.json` to `true` or `false`. For curated dishes you can also edit `tags` in `dish-seed.json`.

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
