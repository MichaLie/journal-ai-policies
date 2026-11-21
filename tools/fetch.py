#!/usr/bin/env python3
"""Fetch every declared http source into ITS OWN isolated directory, hash it, snapshot it.

Only `fetch_method: http` sources are fetched. Archive, browser and manual
sources are never fetched here: a fixed archive capture cannot show a live
change, and a browser extract cannot be refetched by a script. Each of them is
recorded as due for a dated manual live read and printed in the work queue.

Usage: fetch.py [entity-id] [--accept-suspect]

WHY ISOLATED DIRECTORIES: during the reconnaissance that produced this repo, one
agent's generically-named temp file was silently overwritten by a different agent
fetching into a shared directory, yielding correctly-labelled output containing
unrelated content. The failure is invisible — the output still looks plausible.
Every fetch here writes to snapshots/<entity>/<source>/ and nowhere else.

WHY TWO HASHES: `sha256` is the archival hash of the exact bytes. `text_sha256`
is computed over visible text with scripts, styles, comments, attributes and
whitespace stripped. Many publisher pages embed CSRF tokens, nonces and build
IDs that change every request, so the raw hash flips constantly while the policy
does not. Diffing on text_sha256 keeps the review queue free of false positives;
keeping sha256 preserves the archival record.

WHY PDFs ARE EXTRACTED HERE: the first version decoded every body as UTF-8, so a
PDF's "visible text" was its raw bytes. That looked fine — the hash was stable and
the file was large — but the committed text.txt held no words, and the monthly
monitor's commit of 2026-09-01 silently overwrote the PDF extracts the quote
gate depends on. Nothing ran validate.py on that commit, so the gate stayed broken
for ten days. Text now comes from pypdf, the same way verify_quotes reads it.
For a PDF the drift hash is taken over the raw bytes, not the extraction: the bytes
ARE the document, and pypdf's output varies between versions (CI and a laptop do
not necessarily agree), which would report drift that does not exist.

WHY THE WAYBACK TOOLBAR IS STRIPPED: some sources are dated Internet Archive
captures. The archive injects its toolbar into the page, and that toolbar carries
the capture count and date range, which change every time anyone saves the page.
Two captures reported drift in September 2026 with not one word of policy changed.
The toolbar sits between fixed HTML comments; removing that block gives the hash
the archive was supposed to give — the captured page, and only the captured page.
main() no longer fetches archive sources, but visible_text() is the single
extractor for the pipeline (verify_quotes reads a stored content.bin through it),
so any capture that is re-extracted must be stripped the same way.

WHY A SUSPECT EXTRACT IS NOT STORED: a 200 response that passes the challenge
checks can still be the wrong page — a cookie wall, a login redirect, a
truncated render. If an http source already has a text.txt and the new extract
is under 40% of the old one's length, or a quote the records cite from this
source was in the old extract and is gone from the new one, nothing is
overwritten. attempt.json records status "failed" with detail "suspect extract: …"
and diff.py lists it for a human. A redirect to a different path is named in
that detail; on its own it is only printed as [REDIRECTED]. When a person has
read the live page and the change is real, rerun with --accept-suspect, then
update the quotes.

WHY `adjudicated_sha256`: a change must survive an unread month. The previous
design compared each fetch to the one before it, so an unadjudicated change was
overwritten and lost forever on the next run — precisely the TRANSPOSE failure
this project exists to document. diff.py now compares against the hash a human
last signed off, which is stored in the entity YAML, not in the snapshot.
"""
from __future__ import annotations
import hashlib, html, json, os, re, sys, urllib.error, urllib.parse, urllib.request
from common import SNAPSHOTS, load_entities, today
from verify_quotes import norm

# A plain UA gets 403 from Wiley, Springer Nature, science.org and COPE. Those
# sites are not blocking automation as such — they block obviously-scripted
# clients. Presenting a normal browser's headers recovered three sources that
# the previous version reported as permanently unreachable.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 60
MAX_BYTES = 25 * 1024 * 1024
MIN_KEPT = 0.40            # a new extract below this share of the old one is suspect


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


WAYBACK_TOOLBAR = re.compile(
    r"<!--\s*BEGIN WAYBACK TOOLBAR INSERT\s*-->.*?<!--\s*END WAYBACK TOOLBAR INSERT\s*-->",
    re.S)


def is_pdf(raw: bytes) -> bool:
    return raw[:5] == b"%PDF-"


def pdf_text(raw: bytes) -> str:
    """Text of a PDF via pypdf. Empty string, never an exception, if pypdf is
    missing or the file is unreadable — the caller must not mistake that for
    an empty document, which is why text_sha256 for PDFs is over the bytes."""
    try:
        import io, pypdf
        pages = pypdf.PdfReader(io.BytesIO(raw)).pages
        return re.sub(r"\s+", " ", "\n".join((p.extract_text() or "") for p in pages)).strip()
    except Exception:                                        # noqa: BLE001
        return ""


def drift_hash(raw: bytes) -> str:
    """The hash diff.py compares against adjudicated_sha256. Visible text for
    HTML (volatile markup ignored); the raw bytes for a PDF (extraction varies
    by pypdf version, the bytes do not)."""
    return sha256(raw) if is_pdf(raw) else sha256(visible_text(raw).encode("utf-8"))


def visible_text(raw: bytes) -> str:
    """Best-effort visible text, for a hash that ignores volatile markup.
    Single implementation: verify_quotes imports this, so the text that is
    hashed is the text the quotes are checked against."""
    if is_pdf(raw):
        return pdf_text(raw)
    try:
        s = raw.decode("utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        return ""
    if "<" not in s[:4096]:
        return re.sub(r"\s+", " ", s).strip()
    s = WAYBACK_TOOLBAR.sub(" ", s)
    s = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fetch_url(url: str) -> tuple[bytes | None, str, str | None]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return None, "TOO LARGE", None
            return body, str(r.status), r.url
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}", None
    except Exception as e:                                   # noqa: BLE001
        return None, type(e).__name__, None


def write_atomic(path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def response_problem(body: bytes) -> str | None:
    """An HTTP 200 challenge is not a policy snapshot. Preserve the last good copy."""
    if is_pdf(body):
        return None if visible_text(body) else "PDF TEXT EXTRACTION FAILED"
    raw = body.decode("utf-8", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    title = html.unescape(title.group(1)).strip().lower() if title else ""
    if any(marker in title for marker in (
        "client challenge", "just a moment", "access denied", "attention required",
        "security verification", "robot or human", "verify you are human",
    )):
        return "CHALLENGE PAGE"
    text = visible_text(body)
    if not text:
        return "EMPTY TEXT"
    if len(text) < 2000 and any(marker in text.lower() for marker in (
        "enable javascript and cookies to continue", "verify you are human",
        "checking your browser", "please enable javascript to proceed",
    )):
        return "CHALLENGE PAGE"
    return None


def moved_path(url: str, final_url: str | None) -> bool:
    """True when a redirect landed on a different host or path, not merely a
    trailing slash or a query string."""
    if not final_url:
        return False
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(final_url)
    return (a.netloc.lower(), a.path.rstrip("/")) != (b.netloc.lower(), b.path.rstrip("/"))


def suspect_extract(old: str | None, new: str, quotes: list[str]) -> str | None:
    """Why a new extract should not replace the stored one, or None.
    Quotes are compared after verify_quotes.norm, the same normalisation the
    quote gate uses, so a quote counts as present exactly when the gate would
    find it."""
    if not old:
        return None
    reasons = []
    if len(new) < MIN_KEPT * len(old):
        reasons.append(f"text shrank from {len(old)} to {len(new)} characters")
    old_n, new_n = norm(old), norm(new)
    lost = [q for q in quotes if norm(q) in old_n and norm(q) not in new_n]
    if lost:
        reasons.append(f"{len(lost)} quoted passage(s) present in the stored extract are missing "
                       f"from the new one, starting “{lost[0][:60]}…”")
    return "; ".join(reasons) or None


def main(argv: list[str]) -> int:
    accept_suspect = "--accept-suspect" in argv
    args = [a for a in argv[1:] if a != "--accept-suspect"]
    only = args[0] if args else None
    stamp = today().isoformat()
    fetched, queue, failed = [], [], []

    for e in load_entities():
        if only and e["id"] != only:
            continue
        for s in e.get("sources", []):
            tag, url = f"{e['id']}/{s['id']}", s.get("url")
            method = s.get("fetch_method", "http")

            outdir = SNAPSHOTS / e["id"] / s["id"]           # isolation, by construction
            outdir.mkdir(parents=True, exist_ok=True)
            attempt_path = outdir / "attempt.json"

            def record_attempt(status, detail=None):
                write_atomic(attempt_path, json.dumps({
                    "attempted": stamp, "url": url, "method": method,
                    "status": status, "detail": detail,
                }, indent=2).encode("utf-8"))

            # A fixed archive cannot reveal live changes. These sources need an
            # explicit dated live read, not another successful fetch of old bytes.
            if method in ("archive", "browser", "manual") or not url:
                verified = s.get("last_live_verified") if method == "archive" else s.get("last_verified")
                if url and str(verified or "") >= stamp:
                    record_attempt("manually_verified", str(verified))
                else:
                    record_attempt("manual_review_due", s.get("live_url") or url)
                    queue.append((tag, s.get("live_url") or url or "no URL recorded", method))
                continue

            meta_path = outdir / "meta.json"
            prev = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

            body, status, final_url = fetch_url(url)
            problem = status if body is None else response_problem(body)
            if problem:
                record_attempt("failed", problem)
                failed.append((tag, problem, url)); continue

            # Do not overwrite good evidence with a page that merely returned 200.
            txt_path = outdir / "text.txt"
            old_text = txt_path.read_text(encoding="utf-8") if txt_path.exists() else None
            new_text = visible_text(body)
            quotes = [ev["quote"] for p in e.get("policies", [])
                      for ev in p.get("evidence", []) if ev.get("source") == s["id"]]
            suspect = None if accept_suspect else suspect_extract(old_text, new_text, quotes)
            if suspect:
                if moved_path(url, final_url):
                    suspect += f"; redirected to {final_url}"
                problem = f"suspect extract: {suspect}"
                record_attempt("failed", problem)
                failed.append((tag, problem, url)); continue

            digest, tdigest = sha256(body), drift_hash(body)
            adjudicated = s.get("adjudicated_sha256")
            state = ("NEW" if not prev else
                     "unchanged" if prev.get("text_sha256") == tdigest else "CHANGED")

            history = prev.get("history", [])
            if not history or history[-1].get("text_sha256") != tdigest:
                history.append({"fetched": stamp, "sha256": digest, "text_sha256": tdigest})

            write_atomic(outdir / "content.bin", body)
            # The text extract is what gets committed. Quote verification needs
            # visible text, not raw bytes, and raw bytes are ~11x larger. Keeping
            # only content.bin meant the quote gate could not run on a fresh
            # checkout, so CI validated everything except the check this project
            # is built around.
            write_atomic(txt_path, new_text.encode("utf-8"))
            meta_path.write_text(json.dumps({
                "entity": e["id"], "source": s["id"],
                "url": url, "final_url": final_url, "http_status": status,
                "fetched": stamp, "sha256": digest, "text_sha256": tdigest,
                "bytes": len(body), "adjudicated_sha256": adjudicated,
                "history": history[-20:],
            }, indent=2), encoding="utf-8")
            record_attempt("fetched", status)

            redirected = final_url and final_url.rstrip("/") != url.rstrip("/")
            fetched.append((tag, status, tdigest[:12], state, redirected))

    w = max([len(x[0]) for x in fetched + queue + failed] or [10])
    if fetched:
        print("\nFETCHED")
        for tag, status, d, state, redir in fetched:
            print(f"  {tag:<{w}}  {status:<8} {d}  {state}" + ("  [REDIRECTED]" if redir else ""))
    if failed:
        print("\nFAILED — previous snapshot retained; needs a retry or a human")
        for tag, status, url in failed:
            print(f"  {tag:<{w}}  {status:<10} {url}")
    if queue:
        print("\nLIVE REVIEW DUE — archive/browser/manual sources need a dated live read")
        for tag, url, method in queue:
            print(f"  {tag:<{w}}  [{method}]  {url}")
    if failed or queue:
        print(f"\n  {len(failed) + len(queue)} source(s) lack a current successful check:")
        print("  a monitor that silently drops sources reports false confidence.")

    changed = [f for f in fetched if f[3] == "CHANGED"]
    if changed:
        print(f"\n{len(changed)} source(s) CHANGED — run tools/diff.py.")
    return 1 if failed else 2 if queue else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
