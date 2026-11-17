#!/usr/bin/env python3
"""Clean up discovered.json and auto-tags.json.

1. Duplicates: a discovered dish is dropped when another dish of the same country has the same
   Wikidata QID or English name, or a curated dish has the same local name (Gemini's local names
   are not reliable enough to compare with each other). Curated dishes always win, then the
   oldest discovered one. Curated duplicates are only reported, never changed.
2. Old dishes (optional): --older-than DAYS drops discovered dishes added more than DAYS ago.
   The next build refills each country with new suggestions.
3. Orphan tags: auto-tags.json entries for dishes that no longer exist are removed.

Shows what it would do by default; pass --apply to write the files, then rebuild with
`python3 build_dishes.py --no-ai` (or push, and the workflow rebuilds).

    python3 cleanup_dishes.py                     # report only
    python3 cleanup_dishes.py --apply             # remove duplicates and orphan tags
    python3 cleanup_dishes.py --older-than 90 --apply
"""
import argparse
import datetime
import json
import pathlib
import re
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent
SEED = ROOT / "dish-seed.json"
DISCOVERED = ROOT / "discovered.json"
AUTO_TAGS = ROOT / "auto-tags.json"


def norm(text):
    """Compare names ignoring case, accents, spacing and punctuation."""
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", "", text)


def keys(dish):
    """What makes two dishes the same: QID anywhere, or a name within one country."""
    found = []
    if dish.get("qid"):
        found.append(("qid", dish["qid"]))
    for field, value in (("name", dish["name"]["en"]), ("localName", dish.get("localName"))):
        if norm(value):
            found.append((field, dish["country"], norm(value)))
    return found


def label(dish):
    return f'{dish["id"]} ({dish["name"]["en"]})'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the changes (default: report only)")
    parser.add_argument("--older-than", type=int, metavar="DAYS",
                        help="also drop discovered dishes added more than DAYS ago")
    args = parser.parse_args()

    curated = json.loads(SEED.read_text(encoding="utf-8"))["dishes"]
    discovered = json.loads(DISCOVERED.read_text(encoding="utf-8")) if DISCOVERED.exists() else []
    auto = json.loads(AUTO_TAGS.read_text(encoding="utf-8")) if AUTO_TAGS.exists() else {}

    # Curated duplicates: report only, they are hand-checked and may be intentional.
    owner = {}
    for dish in curated:
        for key in keys(dish):
            if key in owner and key[0] == "qid":
                print(f"note: curated {label(dish)} has the same QID as {label(owner[key])}")
            owner.setdefault(key, dish)

    # Oldest discovered dish first, so it is the one kept.
    order = sorted(range(len(discovered)), key=lambda i: (discovered[i].get("addedAt") or "", i))
    removed = {}
    for i in order:
        dish = discovered[i]
        twin = next((owner[k] for k in keys(dish) if k in owner), None)
        if twin is not None:
            removed[dish["id"]] = f"duplicate of {label(twin)}"
            continue
        for key in keys(dish):
            if key[0] != "localName":   # only curated local names are trusted
                owner.setdefault(key, dish)

    if args.older_than is not None:
        cutoff = (datetime.date.today() - datetime.timedelta(days=args.older_than)).isoformat()
        for dish in discovered:
            if dish["id"] not in removed and (dish.get("addedAt") or "") < cutoff:
                removed[dish["id"]] = f'added {dish.get("addedAt") or "at an unknown date"}'

    kept = [d for d in discovered if d["id"] not in removed]
    ids = {d["id"] for d in curated + kept}
    # Tags of dishes removed above go with them; only report the ones that were already orphans.
    orphans = sorted(k for k in auto if k not in ids and k not in removed)

    for dish in discovered:
        if dish["id"] in removed:
            print(f'remove {label(dish)}: {removed[dish["id"]]}')
    if orphans:
        print(f"remove tags of {len(orphans)} dishes that no longer exist: {', '.join(orphans)}")
    if not removed and not orphans:
        print("Nothing to clean up")
        return

    if not args.apply:
        print(f"\n{len(removed)} dishes and {len(orphans)} tag entries would be removed. Run with --apply to do it.")
        return
    write_json(DISCOVERED, kept)
    write_json(AUTO_TAGS, {k: v for k, v in auto.items() if k in ids})
    print(f"\nRemoved {len(removed)} dishes and {len(orphans)} tag entries. "
          "Rebuild with: python3 build_dishes.py --no-ai")


if __name__ == "__main__":
    main()
