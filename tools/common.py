"""Shared helpers. Single source of truth for paths and freshness policy."""
from __future__ import annotations
import datetime as _dt
from pathlib import Path
import yaml

ROOT      = Path(__file__).resolve().parent.parent
ENTITIES  = ROOT / "data" / "entities"
SCHEMA    = ROOT / "schema"
SNAPSHOTS = ROOT / "snapshots"
DOCS      = ROOT / "docs"

# Freshness policy. These numbers are the whole honesty mechanism — a record that
# has not been re-verified is not "probably still fine", it is unverified.
FRESH_DAYS  = 90     # green
AGING_DAYS  = 180    # amber
STALE_DAYS  = 365    # red

# Past this, the SITE ITSELF declares that it is no longer maintained.
# TRANSPOSE still returns HTTP 200 with no staleness banner four years after its
# last update. Building the tombstone before the content is the point.
TOMBSTONE_DAYS = 550


def today() -> _dt.date:
    return _dt.date.today()


def load_entities() -> list[dict]:
    out = []
    for p in sorted(ENTITIES.glob("*.yml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        d["_file"] = p.name
        out.append(d)
    return out


def load_axes() -> dict:
    return yaml.safe_load((SCHEMA / "stm-activities.yml").read_text(encoding="utf-8"))


def axis_index(axes: dict) -> dict[str, dict]:
    idx = {}
    for a in axes["activities"]:
        idx[a["key"]] = {"id": a["id"], "title": a["title"], "group": "stm",
                         "note": a.get("note_2023")}
    for a in axes["extended_axes"]:
        idx[a["key"]] = {"id": None, "title": a["title"], "group": "extended",
                         "note": a.get("why")}
    return idx


def age_days(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (today() - _dt.date.fromisoformat(str(iso))).days
    except ValueError:
        return None


def freshness(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days <= FRESH_DAYS:
        return "fresh"
    if days <= AGING_DAYS:
        return "aging"
    if days <= STALE_DAYS:
        return "stale"
    return "expired"


def entity_last_verified(e: dict) -> str | None:
    # YAML parses an unquoted date into datetime.date; comparing that against a
    # quoted string raises TypeError. Normalise before comparing.
    ds = [str(s.get("last_verified")) for s in e.get("sources", []) if s.get("last_verified")]
    return min(ds) if ds else None
