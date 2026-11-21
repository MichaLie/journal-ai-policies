#!/usr/bin/env python3
"""Validate every entity record. Run in CI; failure blocks the build.

Checks beyond JSON Schema, each of which corresponds to a way this kind of
registry has been observed to rot:
  - every policy axis exists in the axis definition        (schema drift)
  - every evidence source id resolves to a declared source (dangling citation)
  - a quote with no URL is flagged, never silently shipped (fabrication risk)
  - exactly one authoritative source per audience          ("cite this, not that")
  - no two authoritative sources with overlapping audiences
    ('all' overlaps every audience)                         (two pages both "cite this")
  - parent ids resolve                                     (broken inheritance)
  - policy_owner names a recorded entity or the record itself (invented inheritance)
  - "format": "date" fields are real dates                  (schema formats are
                                                             annotations unless checked)
  - quote_provenance matches how the source is held:
    browser sources -> browser_dom; http/archive sources never browser_dom
    (`unverified` and `summariser_relayed` are honest anywhere)
  - every quote is found in the stored copy of its source  (the quote gate)
"""
from __future__ import annotations
import json, sys
from common import ENTITIES, SCHEMA, load_entities, load_axes, axis_index, age_days

try:
    import jsonschema
except ImportError:
    jsonschema = None


def main() -> int:
    entities = load_entities()
    axes = axis_index(load_axes())
    ids = {e["id"] for e in entities}
    errors, warnings = [], []

    schema = json.loads((SCHEMA / "entity.schema.json").read_text(encoding="utf-8"))
    # Without a FormatChecker, "format": "date" is an annotation only and
    # "2026-13-45" passes. The checker makes the schema mean what it says.
    validator = (jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
        if jsonschema else None)

    # Duplicate ids would collide in the same snapshots/<id>/<src>/ directory —
    # silently reintroducing the invisible-overwrite failure this repo is built
    # to avoid. Nothing previously detected it.
    seen_ids: dict[str, str] = {}
    for e in entities:
        if e["id"] in seen_ids:
            errors.append(f"{e['_file']}: entity id '{e['id']}' already used by {seen_ids[e['id']]}")
        seen_ids[e["id"]] = e["_file"]

    for e in entities:
        f = e["_file"]
        rec = {k: v for k, v in e.items() if not k.startswith("_")}

        if validator:
            for err in sorted(validator.iter_errors(rec), key=lambda x: list(x.path)):
                errors.append(f"{f}: {'/'.join(map(str, err.path)) or '<root>'}: {err.message}")

        src_ids, dupes = set(), []
        for s in rec.get("sources", []):
            (dupes.append(s["id"]) if s["id"] in src_ids else src_ids.add(s["id"]))
        for dup in dupes:
            errors.append(f"{f}: duplicate source id '{dup}' — both would write to the same snapshot directory")

        axes_seen, axis_dupes = set(), []
        for pp in rec.get("policies", []):
            (axis_dupes.append(pp["axis"]) if pp["axis"] in axes_seen else axes_seen.add(pp["axis"]))
        for dup in axis_dupes:
            errors.append(f"{f}: axis '{dup}' recorded twice — the entity would vote twice in the consensus")

        for s in rec.get("sources", []):
            if s.get("url") is None and s.get("status") != "unconfirmed":
                warnings.append(f"{f}: source '{s['id']}' has no URL — set status: unconfirmed")

        by_audience: dict[str, int] = {}
        for s in rec.get("sources", []):
            if s.get("authoritative"):
                by_audience[s.get("audience", "unspecified")] = by_audience.get(s.get("audience", "unspecified"), 0) + 1
        for aud, n in by_audience.items():
            if n > 1:
                errors.append(f"{f}: {n} authoritative sources for audience '{aud}' — must be exactly one")
        if rec.get("sources") and not by_audience:
            errors.append(f"{f}: no authoritative source — the 'cite this' panel would render empty")
        # Different audiences can still overlap: an authoritative page for 'all'
        # and another for 'authors' both claim to be the one an author cites.
        auths = [(s["id"], s.get("audience", "unspecified"))
                 for s in rec.get("sources", []) if s.get("authoritative")]
        for i, (sa, aa) in enumerate(auths):
            for sb, ab in auths[i + 1:]:
                if aa != ab and "all" in (aa, ab):
                    warnings.append(f"{f}: authoritative sources '{sa}' ({aa}) and '{sb}' ({ab}) "
                                    f"overlap — 'all' covers every audience, so both say 'cite this'")

        # policy_owner is the entity that writes the policy. A value that names
        # nothing recorded here is an inheritance the site cannot show.
        owner = rec.get("policy_owner")
        if owner and owner != rec.get("id") and owner not in ids:
            warnings.append(f"{f}: policy_owner '{owner}' is not a recorded entity id")

        # Provenance must say how the words were actually obtained. A browser
        # source has no raw HTTP bytes to quote from; an http or archive source
        # was not captured from a rendered DOM.
        method_of = {s["id"]: s.get("fetch_method", "http") for s in rec.get("sources", [])}
        for p in rec.get("policies", []):
            for ev in p.get("evidence", []):
                prov, method = ev.get("quote_provenance"), method_of.get(ev["source"])
                if prov in ("unverified", "summariser_relayed") or method is None:
                    continue
                if method == "browser" and prov != "browser_dom":
                    warnings.append(f"{f}: quote on '{p['axis']}' cites browser source '{ev['source']}' "
                                    f"but claims provenance '{prov}' — should be browser_dom")
                elif method in ("http", "archive") and prov == "browser_dom":
                    warnings.append(f"{f}: quote on '{p['axis']}' cites {method} source '{ev['source']}' "
                                    f"but claims provenance browser_dom")

        for s in rec.get("sources", []):
            d = age_days(s.get("last_verified"))
            if d is not None and d < 0:
                errors.append(f"{f}: source '{s['id']}' has last_verified in the future")

        for p in rec.get("policies", []):
            if p["axis"] not in axes:
                errors.append(f"{f}: unknown axis '{p['axis']}'")
            for ev in p.get("evidence", []):
                if ev["source"] not in src_ids:
                    errors.append(f"{f}: evidence cites undeclared source '{ev['source']}'")
                if ev.get("quote_provenance") == "unverified":
                    warnings.append(f"{f}: unverified quote on axis '{p['axis']}'")
            # A silent cell carrying a quote reads as a contradiction unless the
            # quote is explicitly marked as documenting what is said INSTEAD.
            if p["permission"] == "not_addressed":
                for ev in p.get("evidence", []):
                    if ev.get("evidence_role") != "documents_absence":
                        errors.append(f"{f}: axis '{p['axis']}' is silent but carries evidence without "
                                      f"evidence_role: documents_absence — a silent cell has nothing to quote")

            # TOPIC HEURISTIC. Every quote in this repo matched its source, and five
            # still described the wrong subject: an instruction to EDITORS filed under
            # an author-drafting activity, a REVIEWER restriction filed as evidence of
            # a publisher's own AI use. String matching cannot see that. This catches
            # the commonest shape of it — role words on an author-facing activity.
            AUTHOR_AXES = {"language_refinement", "writing_drafting", "data_presentation",
                           "illustrative_images", "translation", "data_visualisation",
                           "code_presentation", "reference_gathering", "passing_off"}
            if p["axis"] in AUTHOR_AXES:
                for ev in p.get("evidence", []):
                    q = ev["quote"].lower()
                    if ("by editors" in q or "reviewers may not" in q or "reviewers should not" in q
                            or "used by editors" in q):
                        warnings.append(f"{f}: axis '{p['axis']}' is an author activity but its quote "
                                        f"describes editor or reviewer conduct — check it is on topic")

            if p["permission"] == "not_addressed" and p["disclosure"] not in ("not_addressed",):
                warnings.append(f"{f}: axis '{p['axis']}' is silent on permission but "
                                f"'{p['disclosure']}' on disclosure — renders as a contradiction")
            if p["disclosure"] in ("not_required", "not_addressed") and p.get("disclosure_location"):
                warnings.append(f"{f}: axis '{p['axis']}' lists a disclosure location "
                                f"while disclosure is '{p['disclosure']}'")
            if p["permission"] != "not_addressed" and not p.get("evidence"):
                warnings.append(f"{f}: axis '{p['axis']}' asserts '{p['permission']}' with no evidence")

        for c in rec.get("coherence", []):
            for s in c.get("sources", []):
                if s not in src_ids:
                    errors.append(f"{f}: coherence note cites undeclared source '{s}'")

        if rec.get("parent") and rec["parent"] not in ids:
            errors.append(f"{f}: parent '{rec['parent']}' does not resolve")

    # ── quote verification: the guard that was missing ───────────────────────
    # Eight quotes shipped attributed to pages that did not contain them, and one
    # was a paraphrase in quotation marks, because quotes were transcribed from
    # research notes instead of documents. Discipline did not prevent that; a test
    # does. No record may claim byte-level provenance without bytes to back it.
    try:
        import verify_quotes
        unverified = verify_quotes.collect_unverified()
        for u in unverified:
            errors.append(f"{u['entity']}.yml: quote on '{u['axis']}' claims "
                          f"provenance '{u['provenance']}' but is {u['verdict']} "
                          f"in the bytes held for source '{u['source']}'")
    except Exception as exc:                                    # noqa: BLE001
        # A gate that could not run has checked nothing. Exiting 0 here would
        # report every quote as verified, so this is an error.
        errors.append(f"quote verification could not run: {type(exc).__name__}: {exc}")

    for w in warnings:
        print(f"  warn  {w}")
    for x in errors:
        print(f"  ERROR {x}")

    print(f"\n{len(entities)} entities · {len(errors)} errors · {len(warnings)} warnings")
    if not jsonschema:
        print("\nFAIL: jsonschema is not installed, so structural validation did not run.")
        print("      Install it (pip install jsonschema) — a silent pass is worse than a failure.")
        return 1
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
