#!/usr/bin/env python3
"""Check every quote against the bytes we actually hold. This is the guard that
should have existed from the start: eight quotes shipped misattributed and one
was a paraphrase in quotation marks, because quotes were transcribed from agent
reports rather than from documents.

EXACT  — found byte-for-byte in the cited source
NORM   — found after collapsing whitespace, unescaping entities and stripping tags
ELSEWHERE — not in the cited source, but present in another source we hold
MISSING — not found in anything we hold
"""
from __future__ import annotations
import html, json, re, sys
from common import SNAPSHOTS, load_entities


def visible(raw: bytes) -> str:
    try:
        s = raw.decode("utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        return ""
    if b"%PDF" == raw[:4]:
        try:
            import pypdf, io
            return re.sub(r"\s+", " ", "\n".join(
                (p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(raw)).pages))
        except Exception:                                    # noqa: BLE001
            return ""
    s = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s))


def norm(s: str) -> str:
    s = html.unescape(s)
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("—", "-").replace("–", "-").replace(" ", " "))
    return re.sub(r"\s+", " ", s).strip().lower()


def strip(s: str) -> str:
    """Last resort: alphanumerics only. Defeats ligature and spacing artefacts."""
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", norm(s))


def collect_unverified() -> list[dict]:
    """Machine-readable form of the report, for validate.py.
    Only quotes claiming byte-level provenance are enforced: a quote explicitly
    marked `unverified` is an honest declaration, not an error."""
    out = []
    for row in _rows():
        if row["verdict"].startswith("VERIFIED"):
            continue
        if row["provenance"] == "unverified":
            continue
        out.append(row)
    return out


def _rows() -> list[dict]:
    ents = load_entities()
    corpus, strip_map = {}, {}
    for e in ents:
        for s in e.get("sources", []):
            v = source_text(e["id"], s["id"])
            if v is not None:
                corpus[f"{e['id']}/{s['id']}"] = norm(v)
                strip_map[f"{e['id']}/{s['id']}"] = strip(v)
    rows = []
    for e in ents:
        for pol in e.get("policies", []):
            for ev in pol.get("evidence", []):
                key = f"{e['id']}/{ev['source']}"
                q = norm(ev["quote"])
                if q in corpus.get(key, ""):
                    verdict = "VERIFIED"
                elif len(strip(ev["quote"])) >= 30 and strip(ev["quote"]) in strip_map.get(key, ""):
                    verdict = "VERIFIED (punctuation-normalised)"
                elif key not in corpus:
                    verdict = "NO SNAPSHOT"
                else:
                    others = [k for k, v2 in corpus.items() if q in v2]
                    verdict = ("ELSEWHERE -> " + ", ".join(others)) if others else "MISSING"
                rows.append({"entity": e["id"], "axis": pol["axis"], "source": ev["source"],
                             "quote": ev["quote"], "verdict": verdict,
                             "provenance": ev["quote_provenance"]})
    return rows


def source_text(entity: str, source: str) -> str | None:
    """Prefer the committed text extract; fall back to raw bytes when present.
    text.txt is in version control, content.bin is not, so this is what makes
    the quote gate runnable on a clean checkout."""
    d = SNAPSHOTS / entity / source
    txt = d / "text.txt"
    if txt.exists():
        return txt.read_text(encoding="utf-8")
    raw = d / "content.bin"
    return visible(raw.read_bytes()) if raw.exists() else None


def main() -> int:
    ents = load_entities()
    corpus, strip_map = {}, {}
    for e in ents:
        for s in e.get("sources", []):
            v = source_text(e["id"], s["id"])
            if v is not None:
                corpus[f"{e['id']}/{s['id']}"] = norm(v)
                strip_map[f"{e['id']}/{s['id']}"] = strip(v)

    rows, bad = [], 0
    for e in ents:
        for pol in e.get("policies", []):
            for ev in pol.get("evidence", []):
                key = f"{e['id']}/{ev['source']}"
                q = norm(ev["quote"])
                raw_hit = corpus.get(key, "")
                if q in raw_hit:
                    verdict = "VERIFIED"
                elif len(strip(ev["quote"])) >= 30 and strip(ev["quote"]) in strip_map.get(key, ""):
                    # Present, but only after discarding punctuation and non-word
                    # characters. That is an extraction artefact (ligatures, PDF
                    # spacing, entity encoding), not a difference in wording — but
                    # it is reported separately so it is never mistaken for exact.
                    verdict = "VERIFIED (punctuation-normalised)"
                else:
                    others = [k for k, v in corpus.items() if q in v]
                    if others:
                        verdict = "ELSEWHERE -> " + ", ".join(others)
                    elif key not in corpus:
                        verdict = "NO SNAPSHOT"
                    else:
                        verdict = "MISSING"
                if not verdict.startswith("VERIFIED"):
                    bad += 1
                rows.append((e["id"], pol["axis"], ev["source"],
                             ev["quote"][:52], verdict, ev["quote_provenance"]))

    w1 = max(len(r[0]) for r in rows); w2 = max(len(r[1]) for r in rows)
    w3 = max(len(r[2]) for r in rows)
    print(f"\n{'entity':<{w1}}  {'axis':<{w2}}  {'source':<{w3}}  verdict")
    print("-" * (w1 + w2 + w3 + 30))
    for eid, ax, src, snippet, verdict, prov in rows:
        flag = "   " if verdict.startswith("VERIFIED") else " ! "
        print(f"{flag}{eid:<{w1}}  {ax:<{w2}}  {src:<{w3}}  {verdict}")
        if not verdict.startswith("VERIFIED"):
            print(f"{'':<{w1+w2+w3+7}}  “{snippet}…”")
    print(f"\n{len(rows)} quotes · {len(rows)-bad} verified against held bytes · {bad} NOT verified")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
