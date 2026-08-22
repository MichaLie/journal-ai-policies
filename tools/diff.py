#!/usr/bin/env python3
"""Compare what we just fetched against what a human last signed off, and emit a
REVIEW QUEUE. This is the product; everything else serves it.

WHY ADJUDICATED, NOT PREVIOUS. The first version of this file compared each fetch
to the one immediately before it. That meant an unread change was overwritten on
the next run and lost forever: miss one month and a policy change disappears
silently. That is precisely how TRANSPOSE — the closest precedent to this project
— went from 2,376 entries a year to nothing while still serving a live page.
So the comparison is against `adjudicated_sha256`, stored in the entity YAML,
which changes only when a person edits the record.

DELIBERATELY NOT AUTOMATED: a changed hash produces a review item, never an
edited record. The dataset's only asset is that a person stood behind every quote.

Exit codes: 0 nothing to do · 2 items awaiting adjudication · 1 error.
"""
from __future__ import annotations
import json, sys
from common import SNAPSHOTS, load_entities, today


def main() -> int:
    review, unchanged, new, never, orphans, moved = [], 0, 0, [], [], []
    known = set()

    for e in load_entities():
        for s in e.get("sources", []):
            key = f"{e['id']}/{s['id']}"
            known.add(key)
            meta_path = SNAPSHOTS / e["id"] / s["id"] / "meta.json"
            if not meta_path.exists():
                never.append(key)
                continue
            m = json.loads(meta_path.read_text(encoding="utf-8"))

            # A URL edited in the YAML would otherwise diff the new page against
            # the old page's hash — a guaranteed false CHANGED, indistinguishable
            # from real drift.
            if m.get("url") and s.get("url") and m["url"] != s["url"]:
                moved.append((key, m["url"], s["url"]))
                continue

            adjudicated = s.get("adjudicated_sha256")
            if not adjudicated:
                new += 1
                continue
            if m.get("text_sha256") == adjudicated:
                unchanged += 1
            else:
                review.append({
                    "entity": e["id"], "entity_name": e["name"], "source": s["id"],
                    "url": m.get("url"), "signed_off": adjudicated[:12],
                    "now": (m.get("text_sha256") or "")[:12], "fetched": m.get("fetched"),
                    "axes_to_recheck": sorted({p["axis"] for p in e.get("policies", [])
                                               for ev in p.get("evidence", [])
                                               if ev["source"] == s["id"]}),
                })

    # Snapshots on disk for sources no longer declared: reusing the id later
    # would resurrect a stale hash.
    if SNAPSHOTS.exists():
        for ed in SNAPSHOTS.iterdir():
            if not ed.is_dir():
                continue
            for sd in ed.iterdir():
                if sd.is_dir() and f"{ed.name}/{sd.name}" not in known:
                    orphans.append(f"{ed.name}/{sd.name}")

    out = {"generated": today().isoformat(), "review_queue": review, "unchanged": unchanged,
           "never_fetched": never, "awaiting_first_signoff": new,
           "url_changed": moved, "orphan_snapshots": orphans}
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    (SNAPSHOTS / "review-queue.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\nunchanged {unchanged} · awaiting first sign-off {new} · never fetched {len(never)} "
          f"· TO REVIEW {len(review)}")
    for r in review:
        print(f"\n  {r['entity_name']} — {r['source']}")
        print(f"    {r['url']}")
        print(f"    signed off {r['signed_off']} -> now {r['now']}  (fetched {r['fetched']})")
        print(f"    re-check: {', '.join(r['axes_to_recheck']) or 'no axis cites this source'}")
    for key, was, now in moved:
        print(f"\n  URL CHANGED {key}\n    was {was}\n    now {now}\n"
              f"    Re-fetch, then re-read the quotes: the hash chain has been reset.")
    if orphans:
        print(f"\n  orphan snapshots (source removed from YAML): {', '.join(orphans)}")
    if not review and not moved:
        print("\n  Nothing to adjudicate.")
    return 2 if (review or moved) else 0


if __name__ == "__main__":
    sys.exit(main())
