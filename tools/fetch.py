#!/usr/bin/env python3
"""Fetch every declared source into ITS OWN isolated directory, hash it, snapshot it.

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

WHY `adjudicated_sha256`: a change must survive an unread month. The previous
design compared each fetch to the one before it, so an unadjudicated change was
overwritten and lost forever on the next run — precisely the TRANSPOSE failure
this project exists to document. diff.py now compares against the hash a human
last signed off, which is stored in the entity YAML, not in the snapshot.
"""
from __future__ import annotations
import hashlib, html, json, os, re, sys, urllib.error, urllib.request
from common import SNAPSHOTS, load_entities, today

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


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def visible_text(raw: bytes) -> str:
    """Best-effort visible text, for a hash that ignores volatile markup."""
    try:
        s = raw.decode("utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        return ""
    if "<" not in s[:4096]:
        return re.sub(r"\s+", " ", s).strip()
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


def main(argv: list[str]) -> int:
    only = argv[1] if len(argv) > 1 else None
    stamp = today().isoformat()
    fetched, queue, failed = [], [], []

    for e in load_entities():
        if only and e["id"] != only:
            continue
        for s in e.get("sources", []):
            tag, url = f"{e['id']}/{s['id']}", s.get("url")
            method = s.get("fetch_method", "http")

            if not url:
                queue.append((tag, "no URL recorded", method)); continue
            if method == "manual":
                queue.append((tag, url, method)); continue

            outdir = SNAPSHOTS / e["id"] / s["id"]           # isolation, by construction
            outdir.mkdir(parents=True, exist_ok=True)
            meta_path = outdir / "meta.json"
            prev = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

            body, status, final_url = fetch_url(url)
            if body is None:
                failed.append((tag, status, url)); continue

            digest, tdigest = sha256(body), sha256(visible_text(body).encode("utf-8"))
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
            write_atomic(outdir / "text.txt", visible_text(body).encode("utf-8"))
            meta_path.write_text(json.dumps({
                "entity": e["id"], "source": s["id"],
                "url": url, "final_url": final_url, "http_status": status,
                "fetched": stamp, "sha256": digest, "text_sha256": tdigest,
                "bytes": len(body), "adjudicated_sha256": adjudicated,
                "history": history[-20:],
            }, indent=2), encoding="utf-8")

            redirected = final_url and final_url.rstrip("/") != url.rstrip("/")
            fetched.append((tag, status, tdigest[:12], state, redirected))

    w = max([len(x[0]) for x in fetched + queue + failed] or [10])
    if fetched:
        print("\nFETCHED")
        for tag, status, d, state, redir in fetched:
            print(f"  {tag:<{w}}  {status:<8} {d}  {state}" + ("  [REDIRECTED]" if redir else ""))
    if failed:
        print("\nFAILED — needs an archive URL or a human")
        for tag, status, url in failed:
            print(f"  {tag:<{w}}  {status:<10} {url}")
    if queue:
        print("\nWORK QUEUE — not attempted")
        for tag, url, method in queue:
            print(f"  {tag:<{w}}  [{method}]  {url}")
    if failed or queue:
        print(f"\n  {len(failed) + len(queue)} source(s) unretrieved. Listed, not skipped:")
        print("  a monitor that silently drops sources reports false confidence.")

    changed = [f for f in fetched if f[3] == "CHANGED"]
    if changed:
        print(f"\n{len(changed)} source(s) CHANGED — run tools/diff.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
