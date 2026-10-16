#!/usr/bin/env python3
"""Build public/dishes.json for the What to Eat app.

1. Curated dishes from dish-seed.json (hand-checked names, descriptions, emoji and tags).
2. Discovered dishes from discovered.json. When GEMINI_API_KEY is set, Gemini suggests new
   popular dishes for each country, and only the ones that QLever finds on Wikidata as food
   are kept, so made-up dishes never ship. The file grows over time and is committed.
3. QLever (a fast SPARQL engine over Wikidata, CC0) adds a photo and Wikipedia links to every dish.

    python3 build_dishes.py                 # uses GEMINI_API_KEY if set
    python3 build_dishes.py --no-ai         # never call Gemini
    python3 build_dishes.py --ai-file f.json  # use saved suggestions instead of calling Gemini (testing)
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
SEED = ROOT / "dish-seed.json"
DISCOVERED = ROOT / "discovered.json"
OUT = ROOT / "public" / "dishes.json"
UA = "WhatToEatDataBot/1.0 (open-data build for an educational iOS app)"
SCHEMA_VERSION = 1

QLEVER = "https://qlever.dev/api/wikidata"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"

TARGET_PER_COUNTRY = 30   # discovered dishes per country to aim for
ASK_PER_RUN = 12          # suggestions requested per country per run
TAGS = ["spicy", "soup", "vegetarian"]
FOOD_ROOTS = "wd:Q2095 wd:Q746549 wd:Q8195619 wd:Q19861951"  # food, dish, human food, type of food or dish


# MARK: - HTTP

def http_json(url, *, data=None, headers=None, retries=5):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, **(headers or {})})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503) or attempt == retries - 1:
                detail = error.read().decode(errors="replace")[:300]
                raise RuntimeError(f"{error.code} from {url.split('?')[0]}: {detail}") from None
            time.sleep(float(error.headers.get("Retry-After") or 2 ** (attempt + 1)))
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def sparql(query):
    url = QLEVER + "?" + urllib.parse.urlencode({"query": query})
    result = http_json(url, headers={"Accept": "application/sparql-results+json"})
    return [{k: v["value"] for k, v in row.items()} for row in result["results"]["bindings"]]


PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


def chunks(items, size=100):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


# MARK: - QLever lookups

def article_url(title):
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.strip().replace(" ", "_"), safe="():,'-_")


def find_food_items(titles):
    """English Wikipedia title -> Wikidata QID, only for items that are food."""
    found = {}
    for batch in chunks(titles, 80):
        values = " ".join(f"<{article_url(t)}>" for t in batch)
        rows = sparql(PREFIXES + f"""
SELECT DISTINCT ?article ?item WHERE {{
  VALUES ?article {{ {values} }}
  VALUES ?root {{ {FOOD_ROOTS} }}
  ?article schema:about ?item .
  ?item (wdt:P31|wdt:P279)/wdt:P279* ?root .
}}""")
        by_url = {r["article"]: r["item"].rsplit("/", 1)[1] for r in rows}
        for title in batch:
            if article_url(title) in by_url:
                found[title] = by_url[article_url(title)]
    return found


def enrich(qids):
    """QID -> {image, wiki} from Wikidata."""
    info = {}
    for batch in chunks(sorted(qids)):
        values = " ".join(f"wd:{q}" for q in batch)
        rows = sparql(PREFIXES + f"""
SELECT ?item ?img ?enwiki ?viwiki WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }}
  OPTIONAL {{ ?viwiki schema:about ?item ; schema:isPartOf <https://vi.wikipedia.org/> }}
}}""")
        for row in rows:
            qid = row["item"].rsplit("/", 1)[1]
            entry = info.setdefault(qid, {"image": None, "wiki": {}})
            if row.get("img") and not entry["image"]:
                filename = urllib.parse.unquote(row["img"].rsplit("/", 1)[1])
                quoted = urllib.parse.quote(filename.replace(" ", "_"))
                entry["image"] = {
                    "url": f"https://commons.wikimedia.org/wiki/Special:FilePath/{quoted}?width=800",
                    "page": f"https://commons.wikimedia.org/wiki/File:{quoted}",
                }
            for lang in ("en", "vi"):
                if row.get(f"{lang}wiki"):
                    entry["wiki"].setdefault(lang, row[f"{lang}wiki"])
    return info


# MARK: - Gemini

SUGGESTION_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "wikipediaTitle": {"type": "STRING", "description": "Exact title of the English Wikipedia article about the dish"},
            "nameEn": {"type": "STRING"},
            "nameVi": {"type": "STRING", "description": "Name Vietnamese people use for it"},
            "localName": {"type": "STRING", "description": "Name in the country's own language and script"},
            "blurbEn": {"type": "STRING", "description": "One appetizing sentence, at most 120 characters"},
            "blurbVi": {"type": "STRING", "description": "Same sentence in natural Vietnamese"},
            "emoji": {"type": "STRING", "description": "One food emoji that fits best"},
            "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": TAGS}},
        },
        "required": ["wikipediaTitle", "nameEn", "nameVi", "localName", "blurbEn", "blurbVi", "emoji", "tags"],
    },
}


def ask_gemini(country, known_names, count, api_key):
    prompt = (
        f"List {count} popular dishes from {country['name']['en']} that people order or cook as a meal or snack. "
        "Only real, well-known dishes that have their own English Wikipedia article. "
        f"Do not repeat any of these: {', '.join(sorted(known_names))}. "
        "Tags: spicy if it is usually spicy, soup if it is served in broth or is a soup or stew, "
        "vegetarian only if the usual recipe has no meat or fish."
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SUGGESTION_SCHEMA},
    }
    result = http_json(GEMINI.format(model=GEMINI_MODEL), data=body, headers={"x-goog-api-key": api_key})
    parts = result["candidates"][0]["content"]["parts"]
    return json.loads("".join(p.get("text", "") for p in parts))


# MARK: - Build

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def clean_emoji(value):
    value = (value or "").strip()
    return value if 0 < len(value) <= 4 else "🍽️"


def discover(seed, discovered, api_key, ai_file):
    """Ask for new dishes per country and keep the ones Wikidata knows as food."""
    taken_qids = {d["qid"] for d in seed["dishes"] + discovered if d.get("qid")}
    saved = json.loads(pathlib.Path(ai_file).read_text(encoding="utf-8")) if ai_file else {}
    added = []
    for country in seed["countries"]:
        code = country["code"]
        mine = [d for d in seed["dishes"] + discovered if d["country"] == code]
        have = sum(1 for d in discovered if d["country"] == code)
        if have >= TARGET_PER_COUNTRY:
            continue
        if ai_file:
            suggestions = saved.get(code, [])
        else:
            known = {d["name"]["en"] for d in mine}
            try:
                suggestions = ask_gemini(country, known, min(ASK_PER_RUN, TARGET_PER_COUNTRY - have), api_key)
            except Exception as error:  # one country failing should not stop the build
                print(f"  {code}: Gemini failed: {error}")
                continue
        matched = find_food_items([s["wikipediaTitle"] for s in suggestions if s.get("wikipediaTitle")])
        kept = rejected = 0
        for s in suggestions:
            qid = matched.get(s.get("wikipediaTitle", ""))
            if not qid or qid in taken_qids:
                rejected += 1
                continue
            taken_qids.add(qid)
            kept += 1
            added.append({
                "id": f"{code.lower()}-{slug(s['nameEn'])}-{qid.lower()}",
                "qid": qid,
                "country": code,
                "emoji": clean_emoji(s.get("emoji")),
                "localName": s.get("localName") or s["nameEn"],
                "tags": [t for t in s.get("tags", []) if t in TAGS],
                "name": {"en": s["nameEn"], "vi": s.get("nameVi") or s["nameEn"]},
                "blurb": {"en": s.get("blurbEn", ""), "vi": s.get("blurbVi") or s.get("blurbEn", "")},
                "addedAt": datetime.date.today().isoformat(),
            })
        print(f"  {code}: {len(suggestions)} suggested, {kept} kept, {rejected} not found on Wikidata or duplicate")
    return added


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ai", action="store_true", help="never call Gemini")
    parser.add_argument("--ai-file", help="JSON {country code: [suggestions]} to use instead of Gemini")
    args = parser.parse_args()

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    discovered = json.loads(DISCOVERED.read_text(encoding="utf-8")) if DISCOVERED.exists() else []

    api_key = os.environ.get("GEMINI_API_KEY")
    if args.ai_file or (api_key and not args.no_ai):
        print(f"Discovering dishes ({'saved suggestions' if args.ai_file else GEMINI_MODEL})…")
        new = discover(seed, discovered, api_key, args.ai_file)
        if new:
            discovered += new
            DISCOVERED.write_text(json.dumps(discovered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    else:
        print("No GEMINI_API_KEY, skipping discovery")

    curated = [{**d, "curated": True} for d in seed["dishes"]]
    found = [{k: v for k, v in d.items() if k != "addedAt"} | {"curated": False} for d in discovered]
    dishes = curated + found
    print(f"Adding photos and links for {len(dishes)} dishes from Wikidata…")
    info = enrich({d["qid"] for d in dishes if d.get("qid")})
    for dish in dishes:
        extra = info.get(dish.get("qid"), {})
        dish["image"] = extra.get("image")
        dish["wiki"] = extra.get("wiki", {})

    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": None,
        "source": "Curated list and Gemini suggestions checked against Wikidata (CC0). "
                  "Images from Wikimedia Commons, see each image page for its license.",
        "countries": seed["countries"],
        "dishes": dishes,
    }
    # Keep the old timestamp when nothing changed, so the file (and the app's cache) stays the same.
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    unchanged = {**previous, "generatedAt": None} == payload
    payload["generatedAt"] = previous.get("generatedAt") if unchanged else \
        datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if unchanged:
        print("No changes since the last build")
    print(f"Wrote {len(dishes)} dishes ({len(curated)} curated, {len(found)} discovered, "
          f"{sum(1 for d in dishes if d['image'])} with photos) to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
