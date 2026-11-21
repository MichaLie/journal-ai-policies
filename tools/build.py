#!/usr/bin/env python3
"""Render the observatory to docs/.

READER ORDER IS THE DESIGN DECISION. The primary reader is a working scientist
who has already used AI, is about to submit, and is frightened. She will not
scroll past a matrix to reach reassurance; an editor will happily scroll past
reassurance to reach a matrix. That asymmetry settles the order. An anchor nav
gives the impatient reader a one-click bypass so neither audience pays for the
other's opening.

ACCESSIBILITY IS NOT A LATER PASS. The table carries scope and a caption, the
scroll container is focusable, cells carry aria-labels rather than title-only,
headings descend without skipping, and every colour meaning is duplicated in
words. An evidence grid that a screen reader announces as "conditional required"
with no publisher and no activity is not an evidence grid.
"""
from __future__ import annotations
import json, html, re, yaml
from urllib.parse import urlsplit
from consensus import compute as compute_consensus, in_comparison, MIN_CONFIDENT
from common import (DOCS, SCHEMA, load_entities, load_axes, axis_index, age_days,
                    freshness, entity_last_verified, today, TOMBSTONE_DAYS,
                    FRESH_DAYS, AGING_DAYS, STALE_DAYS)

PERM = {"permitted": ("permitted", "ok"), "permitted_with_conditions": ("conditional", "cond"),
        "prohibited": ("prohibited", "no"), "discouraged": ("discouraged", "no"),
        "not_addressed": ("silent", "silent")}
DISC = {"required": "required", "encouraged": "encouraged",
        "not_required": "exempt", "not_addressed": "silent"}
WORRY = {"low": ("usually nothing to do", "w-low"),
         "some": ("declare it", "w-some"),
         "check_first": ("check before you do it", "w-check")}
SECTIONS = [("fine", "You are probably fine"), ("cases", "Find what you did"),
            ("do", "What to do"), ("summary", "What applies"),
            ("grid", "The grid"), ("records", "Sources"), ("method", "Method")]
# Filter groups for the grid and the records, derived from `type`. A missing type
# means publisher, as in consensus.in_comparison. A national standard (GB/Z) sits
# with the standards bodies; it is not a publisher, funder or preprint server.
GROUPS = [("pub", "Publishers & journals", ("publisher", "imprint", "journal")),
          ("funder", "Funders", ("funder",)),
          ("preprint", "Preprint servers", ("preprint_server",)),
          ("ethics", "Ethics & standards bodies", ("normative_body", "national_body"))]
# Legend order, so a record's summary strip reads like the grid legend.
PERM_ORDER = ["permitted", "permitted_with_conditions", "discouraged", "prohibited", "not_addressed"]
# Source links show a domain and a short label; the full address stays in href and title.
ROLE_LABEL = {"policy": "Policy page", "guidance": "Guidance", "announcement": "Announcement",
              "information": "Information page"}
# Audience is shown only where it narrows who the page is for; "all" is the default.
SPECIFIC_AUDIENCE = ("authors", "reviewers", "editors")
PROV_LABEL = {"raw_bytes": "checked against the page",
              "browser_dom": "checked against a saved browser extract",
              "summariser_relayed": "relayed, not directly checked",
              "unverified": "not verified"}


def domain(url: str) -> str:
    h = urlsplit(url).hostname or url
    return h[4:] if h.startswith("www.") else h


def source_label(s: dict) -> str:
    """'elsevier.com · Policy page', with the audience when it is a specific role."""
    label = "Policy page" if s.get("authoritative") else ROLE_LABEL.get(s.get("role"), "Page")
    aud = s.get("audience", "all")
    if aud in SPECIFIC_AUDIENCE:
        label += f" for {aud}"
    url = s.get("live_url") or s.get("url")
    return f"{domain(url)} · {label}" if url else label


# Abbreviations that end in a full stop without ending the sentence.
_ABBR = re.compile(r"(?:\b(?:e\.g|i\.e|etc|cf|vs|al|approx|incl|no|fig|figs|st|dr|u\.s|u\.k)\.)$", re.I)


def first_sentence(text: str) -> tuple[str, bool]:
    """The first sentence of a record's conditions, and whether more follows.
    The full text is always shown below the table; this is only the summary."""
    t = " ".join(clean(text).split())
    for m in re.finditer(r"[.!?][)’”'\"]?(?=\s+[A-Z0-9“‘\"'(])", t):
        head = t[:m.end()]
        if _ABBR.search(head):
            continue
        return head, True
    return t, False


def group_of(e) -> str:
    t = e.get("type", "publisher")
    return next((k for k, _, types in GROUPS if t in types), "other")


def name_links(names, ids) -> str:
    """Organisation names as links to their record anchors; a name without a
    record stays plain text rather than pointing nowhere."""
    return ", ".join(f'<a href="#{esc(ids[n])}">{esc(n)}</a>' if n in ids else esc(n) for n in names)


def filter_bar(scope: str, entities) -> str:
    """Hidden until the script runs: with JavaScript off there is nothing to
    operate, so nothing is shown. Counts are computed here, at build time."""
    counts = {}
    for e in entities:
        counts[group_of(e)] = counts.get(group_of(e), 0) + 1
    btns = [f'<button type="button" class="fb" data-g="" aria-pressed="true">All'
            f'<span class="fn">{len(entities)}</span></button>']
    for k, label, _ in GROUPS:
        if counts.get(k):
            btns.append(f'<button type="button" class="fb" data-g="{k}" aria-pressed="false">'
                        f'{esc(label)}<span class="fn">{counts[k]}</span></button>')
    return (f'<div class="filter" data-filter hidden>'
            f'<label class="vh" for="q-{scope}">Find a publisher, journal or funder</label>'
            f'<input type="search" id="q-{scope}" class="fq" autocomplete="off" '
            f'placeholder="Find a publisher, journal or funder&hellip;">'
            f'<div class="fbtns" role="group" aria-label="Show organisation type">{"".join(btns)}</div>'
            f'<p class="fstat"></p></div>')


def verdict_badges(p) -> str:
    """The grid cell's two values, in the grid's own classes and words, plus
    where the declaration goes. Hidden words keep it from reading as
    "conditional required" to a screen reader."""
    label, klass = PERM[p["permission"]]
    d = DISC[p["disclosure"]]
    locs = [l for l in (p.get("disclosure_location") or []) if l != "unspecified"]
    out = (f'<span class="verdict"><span class="p {klass}">{label}</span>'
           f'<span class="vh">, disclosure </span><span class="d d-{d}">{d}</span>')
    if locs:
        out += '<span class="vh">, declared in </span>' + '<span class="vh">, </span>'.join(
            f'<span class="loc">{esc(l.replace("_", " "))}</span>' for l in locs)
    return out + '</span>'


def verdict_strip(e, n_axes: int) -> str:
    pol = e.get("policies", [])
    c = {}
    for p in pol:
        c[p["permission"]] = c.get(p["permission"], 0) + 1
    bits = [f'<span class="vsum-n">{len(pol)} of {n_axes} activities assessed:</span>']
    for k in PERM_ORDER:
        if c.get(k):
            label, klass = PERM[k]
            bits.append(f'<span class="p {klass}">{c[k]} {label}</span>')
    gaps = sum(1 for p in pol if p["permission"] != "not_addressed" and not p.get("evidence"))
    if gaps:
        bits.append(f'<span class="gap">{gaps} quote{"s" if gaps != 1 else ""} still needed</span>')
    return f'<p class="vsum">{"".join(bits)}</p>'


# Text extraction occasionally leaves C0 control characters inside words (ICMJE's
# pages carry U+0002 where a soft hyphen was). The records keep them, because quotes
# must match the stored text byte for byte; readers should never see them.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(s) -> str:
    return _CONTROL.sub("", str(s))


def esc(s) -> str:
    return html.escape(clean(s), quote=True)


def _clean_tree(x):
    if isinstance(x, str):
        return clean(x)
    if isinstance(x, list):
        return [_clean_tree(i) for i in x]
    if isinstance(x, dict):
        return {k: _clean_tree(v) for k, v in x.items()}
    return x


def opening_counts(entities) -> str:
    """The first claim a reader sees, computed from the records so it cannot go stale.
    Denominators are the publishers and journals ASSESSED on each activity: an omitted
    activity is "not checked", never "does not ban"."""
    pubs = [e for e in entities if in_comparison(e)]
    def tally(axis):
        c = {}
        for e in pubs:
            for p in e.get("policies", []):
                if p["axis"] == axis:
                    c.setdefault(p["permission"], []).append(p)
        return c
    d = tally("writing_drafting")
    allow = d.get("permitted", []) + d.get("permitted_with_conditions", [])
    n_allow, n_disc, n_ban = len(allow), len(d.get("discouraged", [])), len(d.get("prohibited", []))
    n_silent = len(d.get("not_addressed", []))
    n = n_allow + n_disc + n_ban + n_silent
    declared = sum(1 for p in allow if p.get("disclosure") == "required")
    share = declared / n_allow if n_allow else 0
    how = "nearly always" if share >= .9 else "usually" if share >= .6 else "often"
    parts = []
    if n_ban == 0:
        lead = f"Of the {n} publishers and journals assessed here on manuscript writing, none imposes a blanket ban on AI-assisted drafting: "
    else:
        lead = f"Of the {n} publishers and journals assessed here on manuscript writing, {n_ban} ban AI-assisted drafting, "
    parts.append(f"{n_allow} allow it under conditions ({how} with a declaration, and some set stricter "
                 "rules for particular article types or journals)")
    if n_disc:
        parts.append(f"{n_disc} ask you to keep AI to language and readability")
    if n_silent:
        parts.append(f"{n_silent} say nothing on it")
    body = lead + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + "."
    po = tally("passing_off")
    m = sum(len(v) for v in po.values()); k = len(po.get("prohibited", []))
    if m:
        body += (f" What every one of the {m} that address it forbids is presenting AI output as your own data."
                 if k == m else
                 f" {k} of the {m} that address it forbid presenting AI output as your own data.")
    return body


def cite_html(guide, key) -> str:
    c = guide["citations"].get(key)
    if not c:
        return ""
    doi = f' <a href="https://doi.org/{esc(c["doi"])}">doi:{esc(c["doi"])}</a>' if c.get("doi") else ""
    pmid = f' · PMID {esc(c["pmid"])}' if c.get("pmid") else ""
    link = f' <a href="{esc(c["url"])}">Source</a>' if c.get("url") else ""
    return f'<p class="cite">{esc(c["text"])}{doi}{pmid}{link}</p>'


def where_it_goes(axis: str, entities: list[dict]) -> list[tuple[str, list[str]]]:
    """Who wants this declared where, from the records. Never hand-written:
    Wiley routes by purpose, Elsevier fixes one position, ICMJE wants two at
    once. A single generic instruction would be wrong for most readers.
    Counts the same population as the consensus panel, and never names an
    organisation that prohibits the activity as a place to declare it."""
    from collections import defaultdict
    m = defaultdict(set)
    for e in entities:
        if not in_comparison(e):
            continue
        for p in e.get("policies", []):
            if p["axis"] != axis or p["disclosure"] not in ("required", "encouraged"):
                continue
            if p["permission"] == "prohibited":
                continue
            for loc in (p.get("disclosure_location") or []):
                if loc != "unspecified":
                    m[loc].add(e["name"])
    return sorted(((k, sorted(v)) for k, v in m.items()), key=lambda x: -len(x[1]))


def build() -> None:
    entities = load_entities()
    axes_raw = load_axes()
    axes = axis_index(axes_raw)
    plain = {a["key"]: a.get("plain") or a["title"]
             for a in axes_raw["activities"] + axes_raw["extended_axes"]}
    guide = yaml.safe_load((SCHEMA / "reader-guidance.yml").read_text(encoding="utf-8"))
    con = compute_consensus(entities, axes, axes_raw)
    con_by_axis = {r["axis"]: r for r in con["rows"]}
    ids = {e["name"]: e["id"] for e in entities}

    # Dates, never "N days ago": the page is static and is not rebuilt every
    # month, so a relative age baked in at build time becomes false the next day.
    checked = sorted(d for d in (entity_last_verified(e) for e in entities) if d)
    oldest = checked[0] if checked else None
    site_age = age_days(oldest)
    if site_age is None:
        site_age = 9999
    tomb = site_age > TOMBSTONE_DAYS

    order = [a["key"] for a in axes_raw["activities"]] + [a["key"] for a in axes_raw["extended_axes"]]
    used = [k for k in order if any(p["axis"] == k for e in entities for p in e.get("policies", []))]
    rank = {k: i for i, k in enumerate(order)}

    n_quotes = sum(len(p.get("evidence", [])) for e in entities for p in e.get("policies", []))
    n_gaps = sum(1 for e in entities for p in e.get("policies", [])
                 if p["permission"] != "not_addressed" and not p.get("evidence"))
    n_coh = sum(len(e.get("coherence") or []) for e in entities)
    n_meta = sum(len(e.get("metadata_inconsistency") or []) for e in entities)
    n_src = sum(len(e.get("sources", [])) for e in entities)
    n_arch = sum(1 for e in entities for s in e.get("sources", [])
                 if s.get("fetch_method") == "archive")
    n_browser = sum(1 for e in entities for s in e.get("sources", [])
                    if s.get("fetch_method") == "browser")

    P = []
    A = P.append
    A('<!doctype html>')
    A('<html lang="en">')
    A('<meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width, initial-scale=1">')
    A('<title>What Journals Actually Require</title>')
    A('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    A('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lexend:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">')
    A("<style>" + CSS + "</style>")
    A('<body>')
    A('<a class="skip" href="#main">Skip to content</a>')
    A('<div class="wrap">')

    A('<header>')
    A('<p class="eyebrow">Generative AI in the natural &amp; life sciences</p>')
    A('<h1>What Journals Actually Require</h1>')
    A('<p class="lede">What publishers, journals, funders, preprint servers and research-ethics bodies have actually written down, '
      'quoted word for word and re-checked on a schedule &mdash; so the answer to &ldquo;am I allowed to '
      'do this?&rdquo; comes from a source rather than a rumour.</p>')
    A(f'<p class="meta-row"><span>{len(entities)} organisations</span>'
      f'<span>{n_quotes} quotes, all checked against the stored copy of the page they came from</span>'
      f'<span>updated {today().isoformat()}</span></p>')
    A('</header>')

    # A quiet lookup for the reader who came for one journal. It hands the query
    # to the records filter, so there is one search behaviour, not two. Without
    # JavaScript there is nothing to operate, so it stays hidden.
    A('<form class="lookup" data-lookup hidden role="search" action="#records">'
      '<label class="vh" for="q-top">Jump to a journal, publisher or funder</label>'
      '<input type="search" id="q-top" class="lq" autocomplete="off" '
      'placeholder="Jump to a journal, publisher or funder&hellip;"></form>')

    A('<nav class="toc" aria-label="Sections">')
    for sid, label in SECTIONS:
        A(f'<a href="#{sid}">{label}</a>')
    A('</nav>')

    if tomb:
        A('<p class="tombstone"><strong>This page is no longer maintained.</strong> '
          f'Its oldest record was last checked {esc(oldest or "on an unknown date")}. '
          'Policies here change without announcement, '
          'so treat everything below as historical.</p>')
    elif site_age > STALE_DAYS:
        A(f'<p class="warnbar">Oldest record last checked {esc(oldest)}. Re-checking is overdue.</p>')

    A('<main id="main">')

    # 1 ─ reassurance. One reading column; one box, for the lines that matter.
    r = guide["reassurance"]
    A('<section id="fine" class="prose" aria-labelledby="h-fine"><div class="sec-head">'
      '<p class="eyebrow">Read this first</p>'
      f'<h2 id="h-fine">{esc(r["headline"])}</h2></div>')
    A(f'<p class="lede">{esc(opening_counts(entities))} {esc(r["body"].strip())}</p>')
    if r.get("body_cite"):
        A(cite_html(guide, r.get("body_cite")))
    A(f'<div class="lines"><h3>Where the real lines are</h3><p>{esc(r["bound"].strip())}</p></div>')
    dn = guide["detector_note"]
    A(f'<div class="part"><h3>{esc(dn["headline"])}</h3><p>{esc(dn["body"].strip())}</p>')
    for k in dn.get("cites", []):
        A(cite_html(guide, k))
    A('</div>')
    nf = guide["not_your_fault"]
    A(f'<div class="part"><p>{esc(nf["body"].strip())}</p>')
    A(cite_html(guide, nf.get("body_cite")))
    A('</div></section>')

    # 2 ─ your case
    b = guide["boundary"]
    A('<section id="cases" class="prose" aria-labelledby="h-cases"><div class="sec-head">'
      '<p class="eyebrow">The common cases</p><h2 id="h-cases">Find what you did</h2></div>')
    A(f'<div class="part first"><h3>{esc(b["headline"])}</h3>'
      f'<p>{esc(b["body"].strip())}</p><p class="muted">{esc(b["note"].strip())}</p>'
      f'{cite_html(guide, b.get("body_cite"))}</div>')
    rc = guide.get("register_contrast")
    if rc:
        A(f'<div class="part"><h3>{esc(rc["headline"])}</h3><p>{esc(rc["body"].strip())}</p></div>'
          '<div class="register">'
          f'<div class="reg reg-bad"><p class="reg-tag">Reads as a confession</p><p>{esc(rc["confession"].strip())}</p></div>'
          f'<div class="reg reg-good"><p class="reg-tag">Reads as a method</p><p>{esc(rc["methods"].strip())}</p></div>'
          f'</div><p class="muted">{esc(rc["note"].strip())}</p>')
    A('<div class="part"><p class="muted">Ordered by how often life scientists actually do these things. Verdicts and '
      'placement come from the records further down; the advice and the example wording are ours.</p>'
      f'<p class="muted small">{esc(guide["templates"]["bracket_contract"].strip())}</p></div>')
    A('<div class="cases">')
    for c in guide["cases"]:
        label, wcls = WORRY[c["worry"]]
        rr = con_by_axis.get(c["axis"])
        if rr and rr["band"] == "void":
            src = f'none of the {rr["n"]} organisations recorded here states a position'
        elif rr and rr["n"]:
            src = f'{rr["n"]} of {rr["total"]} publishers and journals recorded here so far'
        else:
            src = 'no organisation recorded here yet'
        ex = c.get("example") or {}
        A(f'<details class="case {wcls}"><summary>'
          f'<span class="you">{esc(c["you_did"])}</span>'
          f'<span class="w">{label}</span></summary>'
          f'<div class="case-body"><p>{esc(c["do_this"].strip())}</p>')
        A(cite_html(guide, c.get("body_cite")))
        if ex.get("text"):
            places = where_it_goes(c["axis"], entities)
            A('<div class="tmpl"><div class="tmpl-head"><span class="tmpl-tag">'
              + ('example wording' if ex.get("needed") else 'optional wording') + '</span>'
              + ('' if ex.get("needed") else
                 '<span class="tmpl-opt">you probably need to write nothing</span>')
              + '<button type="button" class="copy" data-copy hidden '
                'aria-label="Copy example wording">Copy</button></div>')
            A(f'<blockquote class="tmpl-text">{esc(ex["text"])}</blockquote>')
            if ex.get("note"):
                A(f'<p class="tmpl-note">{esc(ex["note"].strip())}</p>')
                A(cite_html(guide, ex.get("note_cite")))
            if places:
                A('<div class="places"><p class="places-lbl">Where it goes, according to the '
                  'records here</p><ul>')
                for loc, who in places:
                    A(f'<li><span class="loc">{esc(loc.replace("_"," "))}</span>'
                      f'<span class="loc-who">{name_links(who, ids)}</span></li>')
                A('</ul></div>')
            else:
                A(f'<p class="places-none">{esc((ex.get("placement_fallback") or "Check the journal’s disclosure instructions for the required location.").strip())}</p>')
            A(f'<p class="tmpl-note">{esc(guide["templates"]["slot_warning"].strip())}</p>')
            A('</div>')
        elif ex.get("note"):
            A(f'<p class="tmpl-none">{esc(ex["note"].strip())}</p>')
        A(f'<p class="case-src">{src}'
          + (' &middot; <a href="#grid">see the grid</a>' if rr and rr["n"] else '') + '</p>')
        A('</div></details>')
    A('</div>')
    nc = guide["not_covered"]
    A(f'<div class="part"><h3>{esc(nc["headline"])}</h3><ul class="plain">')
    for item in nc["items"]:
        t = esc(item)
        t = t.replace("**", "\x00")
        parts = t.split("\x00")
        t = "".join(f"<strong>{s}</strong>" if i % 2 else s for i, s in enumerate(parts))
        A(f'<li>{t}</li>')
    A('</ul></div>')
    A('</section>')

    # 3 ─ what to do
    # Advice names only publishers, imprints and journals: the same population the
    # consensus panel counts. An advisory body's recommendation (STM) or a funder's
    # rule is not a journal prohibition, and listing it here once told readers that
    # the STM Association "forbids" a use.
    journals = [e for e in entities if in_comparison(e)]
    # Only uses a researcher makes as author or reviewer. Rules on what the
    # publisher or its editors may do are not something an author can check
    # "before you start", and listing them here read as an instruction to authors.
    NOT_YOURS = {"publisher_own_use", "detection_screening", "due_process", "content_licensing"}
    risky = []
    for rr in con["rows"]:
        if rr["axis"] in NOT_YOURS:
            continue
        forb = [e["name"] for e in journals for pp in e.get("policies", [])
                if pp["axis"] == rr["axis"] and pp["permission"] == "prohibited"]
        if forb:
            risky.append((rr["plain"], sorted(set(forb))))
    audit_req = sorted({e["name"] for e in journals for pp in e.get("policies", [])
                        if pp["axis"] == "audit_trail" and pp["disclosure"] == "required"})
    ad, af = guide["already_done"], guide["already_found_problem"]

    A('<section id="do" class="prose" aria-labelledby="h-do"><div class="sec-head">'
      '<p class="eyebrow">What to actually do</p>'
      '<h2 id="h-do">Keep the record. That is the part you cannot recreate.</h2></div>')
    A('<div class="part first"><h3>Start a log, even a rough one</h3>'
      '<p>Model and <strong>version</strong>, rough dates, the prompts, and the session records '
      'themselves. Write the declaration while the work is fresh &mdash; a first draft takes '
      'ten minutes to write. A transcript from eight months ago cannot be rebuilt, and model versions '
      'get retired.</p>'
      + (f'<p class="muted small">Already required, not hypothetical: {name_links(audit_req, ids)} '
         f'require{"s" if len(audit_req) == 1 else ""} authors to record or supply tool versions, '
         'prompts or session records in some form today.</p>' if audit_req else '') + '</div>')
    A(f'<div class="part"><h3>{esc(ad["headline"])}</h3><p>{esc(ad["body"].strip())}</p></div>')
    A(f'<div class="part"><h3>{esc(af["headline"])}</h3><p>{esc(af["body"].strip())}</p></div>')
    saved = guide["save_policy"]
    A(f'<div class="part"><h3>{esc(saved["headline"])}</h3>'
      f'<p>{esc(saved["body"].strip())}</p></div>')
    if risky:
        A('<div class="warn"><h3>Check these before you start</h3>'
          '<p>Where a use is prohibited outright, the work cannot be fixed at submission. These are the ones '
          'worth checking first, with the publishers and journals here that forbid them:</p><ul class="lanes">')
        for plain_label, who in risky:
            A(f'<li><span class="lane">{esc(plain_label)}</span>'
              f'<span class="lane-who">{name_links(who, ids)}</span></li>')
        A('</ul></div>')
    A('<div class="part"><h3>Then check <em>which</em> page applies</h3>'
      '<p>Authors, reviewers and editors have different responsibilities. Journal-specific rules can add '
      'requirements to a publisher policy. Each record below marks the page and audience to cite.</p></div>')
    A('</section>')

    # 4 ─ consensus. No band boxes: each activity is one two-line row. Line one is
    # the fraction and the rule; line two joins the disclosure split, the usual
    # locations, exceptions and silences in plain muted text.
    rows_by = lambda *b: [x for x in con["rows"] if x["band"] in b]
    BANDS = [("holds", ("universal", "strong"), "Broad agreement",
              "At least three quarters of assessed organisations take the same stance. Exceptions and "
              "differences in disclosure requirements are shown under each rule."),
             ("void", ("void",), "Not addressed in assessed sources",
              "The assessed sources do not address this activity. Blank cells remain separate: they have not been assessed."),
             ("split", ("split",), "Genuinely contested",
              "Organisations disagree on stance, beyond differences in conditions. The dissenters are named "
              "because they are the useful part."),
             ("thin", ("thin",), "Too thin to call",
              f"Fewer than {MIN_CONFIDENT} organisations assessed. A rule resting on two records is not a "
              "finding, so no claim is made."),
             ("unassessed", ("unassessed",), "Not yet assessed",
              "No organisation recorded here has a record on this yet. It is work still to do.")]
    A('<section id="summary" aria-labelledby="h-sum"><div class="sec-head">'
      '<p class="eyebrow">What applies</p>'
      '<h2 id="h-sum">Where the policies agree</h2></div>')
    A('<p class="intro">Calculated from the records below; nothing here is written by hand. Each fraction '
      'counts the publishers and journals assessed on that activity, out of all publishers and journals '
      'recorded here. Advisory bodies, funders and preprint servers appear in the records below and are '
      'kept out of this comparison. A claim resting on three records is not the same as one resting on '
      'thirty, so the denominator is always shown. As records are added, an activity can move from one '
      'group to another.</p>')
    A('<div class="consensus">')
    for key, bands, title, blurb in BANDS:
        rs = rows_by(*bands)
        if not rs:
            continue
        A(f'<div class="band band-{key}"><div class="band-head"><h3>{title}</h3>'
          f'<span class="band-n">{len(rs)} of {len(con["rows"])} activities</span></div>'
          f'<p class="band-blurb">{blurb}</p><ul class="rules">')
        for x in sorted(rs, key=lambda z: -z["n"]):
            frac = (f'<span class="frac">{x["n"]}<span>/{x["total"]}</span>'
                    f'<span class="vh"> organisations assessed</span></span>')
            if x["band"] == "unassessed":
                A(f'<li><p class="rule-line">{frac}<span class="rule-txt muted">{esc(x["plain"])}</span></p></li>'); continue
            if x["band"] == "void":
                A(f'<li><p class="rule-line">{frac}<span class="rule-txt">{esc(x["plain"])} &mdash; '
                  '<em>no organisation states a position</em></span></p></li>'); continue
            if x["band"] == "thin":
                A(f'<li><p class="rule-line">{frac}<span class="rule-txt">{esc(x["plain"])} &mdash; '
                  f'<em>{x["n"]} assessed: too few to call</em></span></p></li>'); continue
            detail = []
            # An override sentence counts who states a safeguard or a screen; a
            # disclosure note or a placement would describe something it does not say.
            if x.get("disclosure_varies") and x.get("stance") == "allows" and not x.get("override"):
                if x["axis"] == "publisher_own_use":
                    labels = {"required": ("requires disclosure to authors", "require disclosure to authors"),
                              "encouraged": ("encourages disclosure to authors", "encourage disclosure to authors"),
                              "not_required": ("exempts disclosure to authors", "exempt disclosure to authors"),
                              "not_addressed": ("does not address disclosure to authors", "do not address disclosure to authors")}
                else:
                    labels = {"required": ("requires disclosure", "require disclosure"),
                              "encouraged": ("encourages disclosure", "encourage disclosure"),
                              "not_required": ("exempts this use", "exempt this use"),
                              "not_addressed": ("does not address disclosure", "do not address disclosure")}
                parts = [f'{n} {labels[k][0 if n == 1 else 1]}' for k, n in x["disclosure_counts"].items()]
                joined = ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]
                detail.append(f'Among those allowing it, {esc(joined)}.')
            if x.get("locations") and not x.get("override"):
                detail.append('Most often declared in '
                              + esc(", ".join(x["locations"]).replace("_", " ")) + '.')
            # On a tied row the modal stance is arbitrary, so "dissenters" are
            # arbitrary too. "No majority ... except X" is a contradiction.
            if x.get("tied"):
                pass
            elif x["dissenters"]:
                detail.append(f'<span class="dissent">Except {name_links(x["dissenters"], ids)}.</span>')
            elif x.get("conditions_vary") and not x.get("override"):
                detail.append('Conditions vary.')
            # Silence is not dissent, and is never folded into "except".
            if x.get("silent"):
                detail.append(f'Silent: {name_links(x["silent"], ids)}.')
            line2 = f'<p class="rule-detail">{" ".join(detail)}</p>' if detail else ''
            if not x.get("rule"):
                A(f'<li><p class="rule-line">{frac}<span class="rule-txt">{esc(x["plain"])} &mdash; '
                  '<em>no majority; organisations are evenly divided</em></span></p>'
                  f'{line2}</li>'); continue
            A(f'<li><p class="rule-line">{frac}<span class="rule-txt">{esc(x["rule"])}</span></p>{line2}</li>')
        A('</ul></div>')
    A('</div></section>')

    # 5 ─ grid
    A('<section id="grid" aria-labelledby="h-grid"><div class="sec-head">'
      '<p class="eyebrow">The grid</p>'
      '<h2 id="h-grid">The evidence grid</h2></div>')
    A('<div class="prose-block">'
      '<p class="intro">Rows follow the nine activities in STM&rsquo;s 2025 classification, then the ones it '
      'leaves out (in italics). Each cell carries two values: whether the use is <strong>permitted</strong>, and '
      'whether it <strong>must be declared</strong>. <span class="p silent">silent</span> means we '
      'checked and the organisation publishes nothing. <span class="p none">&mdash;</span> means '
      'something weaker: not yet assessed here. Treating those as the same would let unfinished work '
      'read as a finding.</p>'
      f'<p class="muted small">{esc(guide["silence_note"].strip())}</p></div>')
    A('<div class="legend" role="group" aria-label="Legend">'
      '<span class="p ok">permitted</span><span class="p cond">conditional</span>'
      '<span class="p no">discouraged</span><span class="p no">prohibited</span>'
      '<span class="p silent">silent</span>'
      '<span class="p none">&mdash;</span><span class="sep"></span>'
      '<span class="d d-required">required</span><span class="d d-encouraged">encouraged</span>'
      '<span class="d d-exempt">exempt</span><span class="d d-silent">silent</span></div>')
    A(filter_bar("grid", entities))
    # The visible caption sits outside the scroll box so it never slides away
    # sideways; the table keeps its own <caption> for screen readers, and the
    # visible copy is hidden from them so it is not read twice.
    cap = ('Permission and disclosure by organisation and activity. '
           'Scroll sideways to see all organisations.')
    A(f'<div class="grid-box"><p class="tcap" aria-hidden="true">{cap}</p>'
      '<div class="tw" tabindex="0" role="region" aria-label="Evidence grid, scrollable">'
      '<table class="matrix">')
    A(f'<caption class="vh">{cap}</caption>')
    A('<thead><tr><th class="rowhead" scope="col">Activity</th>')
    for e in entities:
        q = esc(f'{e["name"]} {e["id"]}'.lower())
        A(f'<th class="ent" scope="col" data-g="{group_of(e)}" data-q="{q}">'
          f'<a href="#{esc(e["id"])}">{esc(e["name"])}</a></th>')
    A('</tr></thead><tbody>')
    for k in used:
        meta = axes[k]
        num = (f'<span class="num">{meta["id"]}</span>' if meta["id"]
               else '<span class="num" aria-hidden="true">+</span>')
        cls = "" if meta["group"] == "stm" else " extrow"
        A(f'<tr class="{cls}"><th class="rowhead" scope="row">{num}{esc(meta["title"])}</th>')
        for e in entities:
            p = next((x for x in e.get("policies", []) if x["axis"] == k), None)
            if p is None:
                A('<td class="cell"><span class="p none">&mdash;'
                  '<span class="vh"> not yet assessed</span></span></td>'); continue
            label, klass = PERM[p["permission"]]
            d = DISC[p["disclosure"]]
            needs = p["permission"] != "not_addressed" and not p.get("evidence")
            gap = (' <span class="gap">?<span class="vh"> quote still needed</span></span>'
                   if needs else "")
            bits = [f'{e["name"]}: {meta["title"]}', f'{label}', f'disclosure {d}']
            if p.get("disclosure_location"):
                bits.append("declared in " + ", ".join(p["disclosure_location"]).replace("_", " "))
            if p.get("rationale") and p["rationale"] != "unstated":
                bits.append("ground: " + p["rationale"])
            aria = "; ".join(bits)
            A(f'<td class="cell"><span class="stack" aria-label="{esc(aria)}">'
              f'<span class="p {klass}">{label}</span>'
              f'<span class="d d-{d}">{d}</span>{gap}</span></td>')
        A('</tr>')
    A('</tbody></table></div></div>')
    # A zero counter is hidden: "0 remain" tells a reader nothing she can act on.
    if n_gaps:
        A(f'<p class="muted small">A <span class="gap">?</span> marks a cell whose verdict is recorded but '
          f'whose quote is not yet captured. {n_gaps} remain, published rather than hidden.</p>')
    A('</section>')

    # 6 ─ records
    A('<section id="records" aria-labelledby="h-rec"><div class="sec-head">'
      '<p class="eyebrow">Sources</p><h2 id="h-rec">Organisations, and what to cite</h2></div>')
    A(filter_bar("records", entities))
    for e in entities:
        lv = entity_last_verified(e); f = freshness(age_days(lv))
        A(f'<details class="ent-card" id="{esc(e["id"])}"><summary>')
        A(f'<span class="ent-name">{esc(e["name"])}</span>')
        A(f'<span class="tag">{esc(e["type"].replace("_"," "))}</span>')
        if e.get("coherence"):
            A(f'<span class="tag flagged">{len(e["coherence"])} internal contradiction'
              f'{"s" if len(e["coherence"]) > 1 else ""}</span>')
        A(f'<span class="f {f}">{checked_label(lv)}</span>')
        A('</summary><div class="ent-body">')
        A(verdict_strip(e, len(used)))
        pols = sorted(e.get("policies", []), key=lambda p: rank.get(p["axis"], 99))
        if pols:
            A(rules_table(e, pols, plain))
        if e.get("delegates_to_journal"):
            A('<p class="inline-flag">Individual journals genuinely differ from this policy &mdash; '
              'check your specific journal as well.</p>')
        if e.get("notes"):
            A(f'<p class="note">{esc(e["notes"].strip())}</p>')
        srcs = {s["id"]: s for s in e.get("sources", [])}
        auth = [s for s in e.get("sources", []) if s.get("authoritative")]
        others = [s for s in e.get("sources", []) if not s.get("authoritative")]
        A('<h3>Cite this</h3><ul class="srcs">')
        for s in auth:
            A(src_li(s, True))
        A('</ul>')
        if others:
            pl = len(others) != 1
            A(f'<h3>Other page{"s" if pl else ""} we hold '
              f'<span class="h-note">(cite the {"ones" if len(auth) > 1 else "one"} above)</span></h3>'
              '<ul class="srcs">')
            for s in others:
                A(src_li(s, False))
            A('</ul>')
        if e.get("coherence"):
            A('<h3>Where this organisation contradicts itself</h3>')
            for c in e["coherence"]:
                A(f'<p class="contra">{esc(c["summary"].strip())}</p>')
        if e.get("metadata_inconsistency"):
            A('<h3>Dating and tagging oddities</h3>')
            for c in e["metadata_inconsistency"]:
                A(f'<p class="metanote">{esc(c["summary"].strip())}</p>')
        quoted = [p for p in pols if p.get("evidence")]
        if quoted:
            A('<h3>What it says, word for word</h3><div class="quotes">')
            for p in quoted:
                A(f'<details class="q"><summary><span class="q-act">{esc(plain[p["axis"]])}</span>'
                  f'{verdict_badges(p)}</summary><div class="q-body">')
                for ev in p["evidence"]:
                    prov = ev["quote_provenance"]
                    role = ("" if ev.get("evidence_role", "supports") == "supports"
                            else '<span class="prov absence">what is said instead</span> &middot; ')
                    s = srcs.get(ev["source"])
                    where = source_label(s) if s else ev["source"]
                    A(f'<blockquote>{esc(ev["quote"])}<cite>{role}{esc(where)} &middot; '
                      f'<span class="prov {prov}">{PROV_LABEL[prov]}</span></cite></blockquote>')
                if p.get("conditions"):
                    A(f'<p class="cond-note">{esc(p["conditions"].strip())}</p>')
                A('</div></details>')
            A('</div>')
        A('</div></details>')
    A('</section>')

    # 7 ─ method: three short unboxed columns.
    A('<section id="method" aria-labelledby="h-meth"><div class="sec-head">'
      '<p class="eyebrow">Method</p><h2 id="h-meth">What this does and does not claim</h2></div><div class="cols">')
    A('<div class="col"><h3>Word for word, or not at all</h3>'
      f'<p>Every verdict carries a short quote, its source, and how it was obtained. All {n_quotes} quotes '
      'are checked automatically against the stored copy of the page they came from; the build fails if '
      'any quote cannot be found. An earlier version of this site carried a sentence in quotation marks '
      'that turned out to be a research assistant’s paraphrase. That is what this check exists to prevent.</p>'
      f'<p>{n_src - n_arch - n_browser} of {n_src} sources are fetched directly. {n_arch} '
      + ('retains a dated Internet Archive capture; its current page is checked separately and carries '
         if n_arch == 1 else
         'retain dated Internet Archive captures; their current pages are checked separately and carry ')
      + f'a live-check date. {n_browser} {"uses" if n_browser == 1 else "use"} a saved excerpt '
      'from the rendered browser page, labelled as such. A fixed archive capture does not establish '
      'that the live policy is unchanged. Missing live checks enter the monitoring queue.</p></div>')
    coh = (f'{n_coh} substantive internal contradiction{"s" if n_coh != 1 else ""}' if n_coh
           else 'No substantive internal contradictions')
    meta_txt = (f' and {n_meta} dating or tagging oddit{"ies" if n_meta != 1 else "y"}' if n_meta else '')
    A('<div class="col"><h3>Published policy only</h3>'
      '<p>This records what organisations have published. It cannot see what editors actually do. '
      'Across seventeen cardiovascular journals studied, fifteen ran AI-detection software and one said '
      'so publicly &mdash; the gap between stated and practised is real, and this site does not close it.</p>'
      f'<p>{len(entities)} organisations are recorded here, activity by activity. If your journal, funder or '
      'institution has no entry, it has not been assessed; that says nothing about whether it is silent. '
      f'{coh}{meta_txt} are recorded across them. A stale HTML title tag is not a policy contradiction and '
      'is not counted as one, and differences in audience or product scope are kept separate.'
      + (f' {n_gaps} recorded verdict{"s" if n_gaps != 1 else ""} still await{"s" if n_gaps == 1 else ""} '
         'a quote; they are marked and published, never asserted as verified.' if n_gaps else '')
      + ' Where we could not find wording at all, the activity stays unassessed and is never labelled silent.</p></div>')
    A('<div class="col"><h3>Corrections and right of reply</h3><p>If you work for an organisation '
      'recorded here and think a record is wrong, we want to fix it. Every record names its source and '
      'quotes the wording it relies on, so corrections can be specific. '
      '<a href="https://github.com/MichaLie/journal-ai-policies/issues">Open an issue</a> and we will respond. Corrected records carry '
      'the date they changed, and the change stays in the public history.</p>'
      f'<p class="muted small">This page declares itself unmaintained automatically once its oldest record '
      f'passes {TOMBSTONE_DAYS} days without re-checking. The closest precedent to this project still '
      'serves a live page, with no staleness warning, four years after its last update.</p></div>')
    A('</div></section>')
    # One live region for the filter bars and the copy buttons, so a change is announced once.
    A('<p id="filter-live" class="vh" role="status" aria-live="polite"></p>')
    A('</main>')

    A('<footer><p class="eyebrow">Source and licence</p>'
      '<p>Maintained by <a href="https://github.com/MichaLie">MichaLie</a>. '
      'Records, code and full change history: <a href="https://github.com/MichaLie/journal-ai-policies">github.com/MichaLie/journal-ai-policies</a>. '
      'Corrections via <a href="https://github.com/MichaLie/journal-ai-policies/issues">issues</a>.</p>'
      '<p>Related: <a href="https://michalie.github.io/publishing-under-ai/">Publishing Under AI</a>: how scientific writing and peer review are coping with AI, where researchers disagree, and what is being tried · '
      '<a href="https://michalie.github.io/agent-risk-atlas/">Agent Risk Atlas</a>: how research with AI agents goes wrong, and what protects you.</p>'
      '<p>Data CC0. Code MIT. Quoted policy text still belongs to the publishers, and is reproduced here '
      'as short excerpts for comparison and criticism, with attribution and a link to the source.</p>'
      '<p class="muted">The reassurance and advice on this page are our own wording. Every verdict, '
      'fraction and named organisation is calculated from the records.</p></footer>')
    A('</div>')
    A("<script>" + JS + "</script>")
    A('</body></html>')

    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text("\n".join(P), encoding="utf-8")
    dump = {"generated": today().isoformat(),
            "rights": ("Records CC0. Quoted policy text remains the property of the publishers named and "
                       "is reproduced as short excerpts for comparison and criticism."),
            "consensus": con, "axes": axes_raw,
            "entities": [{k: v for k, v in e.items() if not k.startswith("_")} for e in entities]}
    dump = _clean_tree(dump)
    (DOCS / "data.json").write_text(json.dumps(dump, indent=2, ensure_ascii=False, default=str),
                                    encoding="utf-8")
    print(f"built docs/index.html  ({len(entities)} entities, {len(used)} axes, {n_quotes} quotes, "
          f"{n_coh} contradictions, {n_meta} metadata notes, {n_gaps} gaps)")
    print("built docs/data.json")


def checked_label(iso) -> str:
    """The visible freshness text: the date of the check, never an age. The
    colour class is still computed at build time; the words stay true."""
    return f"checked {esc(iso)}" if iso else "check date unknown"


def rules_table(e: dict, pols: list[dict], plain: dict) -> str:
    """The card's first answer: one row per assessed activity, in plain words.
    The conditions column shows the first sentence of the record's own summary;
    the full text and the verbatim quotes follow below the table. Explicit roles
    keep the table semantics when narrow screens restack the cells."""
    out = [f'<table class="rt" role="table"><caption class="vh">Rules recorded for {esc(e["name"])}</caption>'
           '<thead><tr role="row"><th scope="col" role="columnheader">Activity</th>'
           '<th scope="col" role="columnheader">Verdict</th>'
           '<th scope="col" role="columnheader">Declare it</th>'
           '<th scope="col" role="columnheader">Conditions</th></tr></thead><tbody>']
    for p in pols:
        label, klass = PERM[p["permission"]]
        d = DISC[p["disclosure"]]
        locs = [l for l in (p.get("disclosure_location") or []) if l != "unspecified"]
        where = (f' <span class="rt-where">in {esc(", ".join(locs).replace("_", " "))}</span>'
                 if locs and p["disclosure"] in ("required", "encouraged") else "")
        cond = ""
        if p.get("conditions"):
            head, more = first_sentence(p["conditions"])
            cond = esc(head) + ('<span class="more" aria-hidden="true"> &hellip;</span>' if more else "")
        out.append(f'<tr role="row"><th scope="row" role="rowheader">{esc(plain.get(p["axis"], p["axis"]))}</th>'
                   f'<td role="cell"><span class="p {klass}">{label}</span></td>'
                   + (f'<td role="cell" class="rt-d"><span class="muted">&mdash;</span><span class="vh">nothing to declare</span></td>'
                      if p["permission"] in ("prohibited", "not_addressed") and p["disclosure"] == "not_addressed"
                      else f'<td role="cell" class="rt-d"><span class="d d-{d}">{d}</span>{where}</td>')
                   + f'<td role="cell" class="rt-c">{cond}</td></tr>')
    out.append('</tbody></table>')
    return "".join(out)


def src_li(s: dict, authoritative: bool) -> str:
    """Domain and a short label as the link text, the full address in href and
    title. The provenance line stays, small and muted."""
    lv = s.get("last_verified"); f = freshness(age_days(lv))
    url = s.get("url")
    label = source_label(s)
    if s.get("live_url"):
        link = (f'<a href="{esc(s["live_url"])}" title="{esc(s["live_url"])}">{esc(label)}</a> '
                f'<span class="src-alt">(<a href="{esc(url)}" title="{esc(url)}">archived copy</a>)</span>')
    elif url:
        link = f'<a href="{esc(url)}" title="{esc(url)}">{esc(label)}</a>'
    else:
        link = '<span class="nourl">Web address not yet confirmed</span>'
    head = ['<span class="tag auth">cite this</span>'] if authoritative else []
    if s.get("status") and s["status"] != "current":
        head.append(f'<span class="tag st-{esc(s["status"])}">{esc(s["status"].replace("_", " "))}</span>')
    prov = []
    method = s.get("fetch_method", "http")
    if method == "browser":
        prov.append("browser copy")
    elif method == "archive":
        prov.append("archive copy; live page checked " + esc(s.get("last_live_verified") or "not yet"))
    elif method == "manual":
        prov.append("copied by hand")
    prov.append(f'page dated {esc(s["stated_date"])}' if s.get("stated_date")
                else '<span class="undated">no stated date</span>')
    prov.append(f'<span class="ck {f}">{checked_label(lv)}</span>')
    note = f'<p class="src-note">{esc(s["note"].strip())}</p>' if s.get("note") else ""
    return (f'<li class="{"auth" if authoritative else ""}"><p class="src-link">{"".join(head)}{link}</p>'
            f'<p class="src-prov">{" &middot; ".join(prov)}</p>{note}</li>')
CSS = r"""
/* ── tokens ───────────────────────────────────────────────────────────────
   The site is light-only. prefers-color-scheme is deliberately NOT honoured:
   the OS-driven dark theme was the only switch and there is no toggle, so a
   reader who wanted light could not get it. The [data-theme="dark"] block below
   is kept, complete and in sync, but nothing sets the attribute — it is the
   hook a future toggle would use. If you re-enable dark, define every colour in
   both blocks: a colour defined in only one renders one theme's text on the
   other theme's ground.
   --accent means ONE thing: attention/staleness. Quotes, row numbers and
   required-disclosure each have their own token, because an accent that means
   four things means nothing.                                                */
:root{
  --ground:#FBFCFD; --surface:#FFFFFF; --surface-2:#F2F5F8; --chip:#EAEFF4;
  --ink:#14181E; --ink-2:#333B44; --muted:#4B545E;
  --rule:#9BA5B0; --rule-soft:#D2D9E0;
  --accent:#8A2E14;            /* attention + staleness + focus, nothing else */
  --quote:#A7B0BA;             /* quotation rules */
  --req:#6B4108;               /* "must be declared" */
  --ok:#115438; --cond:#6B5009; --no:#651A27; --live:#16409B;
}
/* Dormant. Nothing sets data-theme; kept in sync for a future toggle. */
:root[data-theme="dark"]{
  --ground:#161B22; --surface:#1F262F; --surface-2:#28323C; --chip:#252E37;
  --ink:#EDF1F5; --ink-2:#CBD4DE; --muted:#A6B2BF;
  --rule:#4E5C6B; --rule-soft:#333D48;
  --accent:#F0916A; --quote:#566372; --req:#E0B673;
  --ok:#68BC94; --cond:#DCB868; --no:#EE8FA1; --live:#9BBBF5;
}

/* ── type scale and measure ───────────────────────────────────────────────
   Eight steps, no others. Label floor .72rem: below about 11px, uppercase
   letterspaced mono stops being scannable and becomes texture. Monospace
   capitals are for tiny labels only (eyebrows, badges), never for sentences
   or lists. One reading measure for prose; the grid and the records may run
   wider because they are tables, not text.                                  */
:root{
  --t-label:.72rem; --t-small:.86rem; --t-body:1rem; --t-lead:1.15rem;
  --t-h3:1.06rem; --measure:46rem;
  --mono:"IBM Plex Mono",ui-monospace,monospace;
  --sans:Lexend,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;overflow-x:clip}
body{overflow-x:clip}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:var(--t-body);line-height:1.65;margin:0;-webkit-font-smoothing:antialiased}
.wrap{max-width:74rem;margin:0 auto;padding:3rem 1.5rem 6rem;display:flex;
  flex-direction:column;gap:2.25rem;min-width:0}
main{display:flex;flex-direction:column;gap:5rem;min-width:0}
h1,h2,h3{font-family:var(--sans);text-wrap:balance;margin:0;line-height:1.25;letter-spacing:normal}
h1{font-size:clamp(2.1rem,5vw,3rem);font-weight:700}
h2{font-size:clamp(1.4rem,3vw,1.8rem);font-weight:600}
h3{font-size:var(--t-h3);font-weight:600}
p{margin:0}
a{color:var(--live);text-decoration:underline;text-underline-offset:2px;text-decoration-thickness:1px}
a:focus-visible,summary:focus-visible,.tw:focus-visible,.skip:focus{
  outline:2px solid var(--accent);outline-offset:3px;border-radius:2px}
.vh{position:absolute;width:1px;height:1px;clip-path:inset(50%);overflow:hidden;white-space:nowrap}
.skip{position:absolute;left:-9999px}
.skip:focus{position:fixed;left:1rem;top:1rem;z-index:9;background:var(--surface);
  color:var(--ink);padding:.9rem 1.1rem;min-height:44px;border:2px solid var(--accent);
  border-radius:3px}
[hidden]{display:none!important}

.eyebrow{font-family:var(--mono);font-size:var(--t-label);
  letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.lede{font-size:var(--t-lead);line-height:1.6;color:var(--ink-2);max-width:var(--measure)}
.intro{color:var(--ink-2);max-width:var(--measure)}
.muted{color:var(--muted)}
.small{font-size:var(--t-small)}
.cite{font-size:var(--t-small);color:var(--muted);line-height:1.5;max-width:var(--measure)}
.cite a{color:var(--live)}
strong{font-weight:600;color:var(--ink)}

header{display:flex;flex-direction:column;gap:1rem;padding-bottom:1.6rem;border-bottom:1px solid var(--rule)}
.meta-row{display:flex;flex-wrap:wrap;gap:.3rem 1.4rem;font-size:var(--t-small);color:var(--muted)}
.lookup{max-width:var(--measure);margin-top:-.75rem}
.lq{font:inherit;font-size:var(--t-body);color:var(--ink);width:100%;min-height:44px;
  padding:.55rem .1rem;background:transparent;border:0;border-bottom:1px solid var(--rule);
  border-radius:0;-webkit-appearance:none;appearance:none}
.lq::placeholder{color:var(--muted);opacity:1}
.lq:focus-visible{outline:none;border-bottom:2px solid var(--accent)}
nav.toc{display:flex;flex-wrap:wrap;gap:0 .9rem;border-bottom:1px solid var(--rule-soft)}
nav.toc a{font-family:var(--mono);font-size:var(--t-label);
  letter-spacing:.06em;text-transform:uppercase;text-decoration:none;color:var(--muted);
  padding:.6rem .25rem;min-height:44px;display:flex;align-items:center;
  border-bottom:2px solid transparent}
nav.toc a:hover,nav.toc a:focus-visible{color:var(--ink);border-bottom-color:var(--accent)}

section{display:flex;flex-direction:column;gap:1.4rem;min-width:0}
.sec-head{display:flex;flex-direction:column;gap:.45rem;max-width:var(--measure)}
/* Reading column: sections 1–3 are prose, set to one measure. */
section.prose>*{max-width:var(--measure);width:100%}
.part{display:flex;flex-direction:column;gap:.6rem;padding-top:1.4rem;border-top:1px solid var(--rule-soft)}
.part.first{border-top:none;padding-top:0}
.prose-block{display:flex;flex-direction:column;gap:.6rem;max-width:var(--measure)}
.tombstone{background:var(--no);color:#fff;padding:1.25rem 1.5rem;border-radius:3px}
/* dark palette's --no is light, so white-on-it fails; flip the text instead */
:root[data-theme="dark"] .tombstone{color:#12161B}
.warnbar{background:var(--surface-2);padding:.9rem 1.2rem;border-radius:3px}

/* ── labels: the only monospace capitals on the page ─────────────────── */
.p,.d,.f,.tag,.gap,.w,.loc,.reg-tag,.tmpl-tag{
  font-family:var(--mono);font-size:var(--t-label);
  font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  padding:.14rem .42rem;border-radius:2px;display:inline-block;line-height:1.45}
.p{border:1px solid currentColor;white-space:nowrap}
.p.ok{color:var(--ok)}.p.cond{color:var(--cond)}.p.no{color:var(--no)}
.p.silent{color:var(--muted);border-style:dashed}
.p.none{color:var(--muted);border:1px dotted var(--rule);opacity:.85}
.d{background:var(--chip);color:var(--muted);border:1px solid transparent;white-space:nowrap}
.d-required{color:var(--req);font-weight:600}
.d-encouraged{color:var(--live)}
.d-exempt{color:var(--ok)}
.d-silent{color:var(--muted);opacity:.8}
.gap{color:var(--cond);border:1px solid var(--cond);cursor:help}
.f{border:1px solid currentColor;white-space:nowrap;font-weight:400}
.f.fresh{color:var(--muted);border-color:var(--rule-soft)}.f.aging{color:var(--cond)}.f.stale{color:var(--accent)}
.f.expired,.f.unknown{color:var(--no)}
.tag{background:var(--chip);color:var(--muted);border:1px solid transparent;font-weight:500}
.tag.flagged{color:var(--accent);border-color:var(--accent)}
.tag.auth{color:var(--ok);background:transparent;border-color:var(--ok)}
.tag.st-superseded,.tag.st-stale_but_live{color:var(--accent)}
.tag.st-unconfirmed{color:var(--cond)}
.prov.summariser_relayed{color:var(--cond)}
.prov.unverified{color:var(--no)}
.prov.absence{color:var(--live)}

/* ── soft boxes: only where a box does a job ──────────────────────────── */
.lines{background:var(--surface-2);border-radius:6px;padding:1.15rem 1.35rem;
  display:flex;flex-direction:column;gap:.5rem}
.lines p{color:var(--ink-2)}
.register{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(16rem,100%),1fr));gap:.9rem}
.reg{background:var(--surface);border:1px solid var(--rule-soft);border-radius:4px;
  padding:.95rem 1.15rem;display:flex;flex-direction:column;gap:.45rem}
.reg p{color:var(--ink-2);line-height:1.55}
.reg-tag{padding:0}
.reg-bad .reg-tag{color:var(--no)}.reg-good .reg-tag{color:var(--ok)}
.warn{border:1px solid var(--rule-soft);border-left:3px solid var(--no);border-radius:4px;
  background:var(--surface);padding:1.1rem 1.3rem;display:flex;flex-direction:column;gap:.55rem}
ul.lanes{list-style:none;margin:.2rem 0 0;padding:0;display:flex;flex-direction:column}
ul.lanes li{display:flex;flex-direction:column;gap:.1rem;padding:.55rem 0;border-top:1px solid var(--rule-soft)}
ul.lanes li:first-child{border-top:none}
.lane{font-weight:500}
.lane-who{font-size:var(--t-small);color:var(--muted)}
ul.plain{margin:0;padding-left:1.15rem;display:flex;flex-direction:column;gap:.5rem}
ul.plain li::marker{color:var(--muted)}

/* ── cases ────────────────────────────────────────────────────────────── */
.cases{display:flex;flex-direction:column;gap:.5rem}
details.case,details.ent-card{border:1px solid var(--rule-soft);border-radius:4px;background:var(--surface)}
details.case summary,details.ent-card summary{cursor:pointer;padding:.8rem 1.1rem;
  display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;min-height:2.9rem}
details[open].case summary,details[open].ent-card summary{border-bottom:1px solid var(--rule-soft)}
.case .w{border:1px solid currentColor;white-space:nowrap;font-weight:500}
.case.w-low .w{color:var(--ok)}.case.w-some .w{color:var(--cond)}.case.w-check .w{color:var(--no)}
.case .you{flex:1 1 20rem}
.case-body{padding:1rem 1.2rem 1.1rem;display:flex;flex-direction:column;gap:.75rem;color:var(--ink-2)}
.case-src{font-size:var(--t-small);color:var(--muted)}
.case-src a{display:inline-block;padding-block:.35rem}

/* ── templates: no box inside the case, one rule beside the wording ──── */
.tmpl{display:flex;flex-direction:column;gap:.6rem;padding-top:.75rem;border-top:1px solid var(--rule-soft)}
.tmpl-head{display:flex;flex-wrap:wrap;gap:.3rem .7rem;align-items:center}
.tmpl-tag{color:var(--accent);padding:0}
.tmpl-opt{color:var(--muted);font-size:var(--t-small)}
.copy{margin-left:auto;font:inherit;font-size:var(--t-small);color:var(--live);background:transparent;
  border:1px solid var(--rule-soft);border-radius:3px;padding:.2rem .7rem;min-height:32px;cursor:pointer}
.copy:hover{border-color:var(--live)}
.copy:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
blockquote.tmpl-text{margin:0;padding:.15rem 0 .15rem 1rem;border-left:2px solid var(--accent);
  color:var(--ink);line-height:1.6}
.tmpl-note{font-size:var(--t-small);color:var(--muted)}
.tmpl-none{color:var(--ink-2)}
.places{display:flex;flex-direction:column;gap:.35rem}
.places-lbl{font-size:var(--t-small);color:var(--muted)}
.places ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.3rem}
.places li{display:flex;flex-wrap:wrap;gap:.45rem;align-items:baseline}
.loc{color:var(--live);background:var(--chip)}
.loc-who{font-size:var(--t-small);color:var(--muted)}
.places-none{font-size:var(--t-small);color:var(--muted)}

/* ── consensus: two-line rows, hairlines, no band boxes ───────────────── */
.consensus{display:flex;flex-direction:column;gap:2.6rem;max-width:var(--measure)}
.band{display:flex;flex-direction:column;gap:.4rem}
.band-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.3rem .8rem}
.band-n{font-size:var(--t-small);color:var(--muted)}
.band-blurb{font-size:var(--t-small);color:var(--muted)}
ul.rules{list-style:none;margin:.4rem 0 0;padding:0;display:flex;flex-direction:column}
ul.rules li{padding:.7rem 0;border-top:1px solid var(--rule-soft);display:flex;flex-direction:column;gap:.2rem}
.rule-line{display:flex;align-items:baseline;gap:.75rem}
.frac{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:var(--t-small);
  font-weight:600;color:var(--ink-2);min-width:3.4rem;flex:none}
.frac span{color:var(--muted);font-weight:400}
.rule-detail{font-size:var(--t-small);color:var(--muted);line-height:1.55;padding-left:4.15rem}
.rule-detail a{color:inherit;text-decoration-color:var(--rule)}
.rule-detail a:hover{color:var(--live)}
.dissent{color:var(--ink-2)}

/* ── matrix ───────────────────────────────────────────────────────────── */
/* Bounded in both directions so the header row can stick to the top of the box
   while the activity column sticks to its left edge. Collapsed borders do not
   travel with sticky cells, so the header's bottom rule is an inset shadow. */
.grid-box{display:flex;flex-direction:column;min-width:0}
.tcap{font-size:var(--t-small);color:var(--muted);padding:.6rem .85rem;background:var(--surface);
  border:1px solid var(--rule);border-bottom:none;border-radius:3px 3px 0 0}
.tw{position:relative;overflow:auto;max-height:min(78vh,48rem);min-width:0;max-width:100%;border:1px solid var(--rule);
  border-radius:3px;background:var(--surface)}
.tcap+.tw{border-top-left-radius:0;border-top-right-radius:0}
table.matrix{border-collapse:collapse;width:100%}
.matrix th,.matrix td{border-bottom:1px solid var(--rule-soft);border-right:1px solid var(--rule-soft);
  padding:.5rem .6rem;vertical-align:top;text-align:left}
.matrix thead th{background:var(--surface-2);border-bottom:1px solid var(--rule);
  position:sticky;top:0;z-index:2;box-shadow:inset 0 -1px 0 var(--rule)}
.matrix th.ent{font-family:var(--mono);font-size:var(--t-label);
  letter-spacing:.04em;text-transform:uppercase;color:var(--muted);font-weight:600;min-width:5.5rem}
.matrix th.ent a{color:inherit;text-decoration-color:var(--rule)}
.matrix th.ent a:hover{color:var(--live);text-decoration-color:currentColor}
.matrix th.rowhead{font-family:inherit;font-size:var(--t-small);font-weight:400;line-height:1.35;
  min-width:min(14rem,52vw);max-width:18rem;background:var(--surface);
  position:sticky;left:0;z-index:1;
  border-right:1px solid var(--rule)}
.matrix thead th.rowhead{background:var(--surface-2);z-index:3}
.matrix .num{font-family:var(--mono);font-size:var(--t-label);
  color:var(--muted);font-weight:600;margin-right:.45rem}
.matrix tr.extrow th.rowhead{font-style:italic;color:var(--ink-2)}
.cell{display:table-cell}
.cell .stack{display:flex;flex-direction:column;gap:.22rem;align-items:flex-start}
caption{text-align:left;padding:.6rem .85rem;font-size:var(--t-small);color:var(--muted);
  border-bottom:1px solid var(--rule)}
.legend{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.legend .sep{width:1px;height:1.1rem;background:var(--rule);margin:0 .4rem}

/* ── entity records ───────────────────────────────────────────────────── */
details.ent-card+details.ent-card{margin-top:.5rem}
.ent-name{font-weight:600;margin-right:.3rem}
.ent-body{padding:1.1rem 1.3rem 1.3rem;display:flex;flex-direction:column;gap:1rem;font-size:.96rem}
.ent-body>h3{margin-top:.6rem}
.h-note{font-weight:400;color:var(--muted);font-size:var(--t-small)}
.note,.inline-flag{color:var(--ink-2);max-width:var(--measure)}
.inline-flag{border-left:2px solid var(--accent);padding-left:.8rem}
.vsum{display:flex;flex-wrap:wrap;gap:.35rem;align-items:center}
.vsum-n{font-size:var(--t-small);color:var(--muted);margin-right:.3rem}
.vsum .gap{margin-left:.2rem}
/* The rules table: first thing in an open card. */
table.rt{border-collapse:collapse;width:100%;font-size:var(--t-small)}
.rt caption{padding:0;border:none}
.rt th,.rt td{text-align:left;vertical-align:top;padding:.55rem .7rem .55rem 0;border-top:1px solid var(--rule-soft)}
.rt thead th{border-top:none;border-bottom:1px solid var(--rule);font-weight:500;color:var(--muted);padding-top:0}
.rt tbody th{font-weight:500;color:var(--ink);width:24%}
.rt td:nth-child(2){width:8.5rem}
.rt td.rt-d{width:13rem}
.rt-where{display:block;color:var(--muted);margin-top:.2rem}
.rt-c{color:var(--ink-2)}
.more{color:var(--muted)}
ul.srcs{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.7rem}
ul.srcs li{display:flex;flex-direction:column;gap:.15rem;word-break:break-word}
.src-link{display:flex;flex-wrap:wrap;align-items:baseline;gap:.25rem .55rem}
.src-link a{padding-block:.3rem}
.src-alt{font-size:var(--t-small);color:var(--muted)}
.src-prov{font-size:var(--t-label);color:var(--muted);letter-spacing:.01em}
.src-prov .undated{color:var(--cond)}
.ck.aging{color:var(--cond)}.ck.stale{color:var(--accent)}.ck.expired,.ck.unknown{color:var(--no)}
.src-note{color:var(--muted);font-size:var(--t-small);max-width:var(--measure)}
.nourl{color:var(--cond);font-style:italic}
.contra{border-left:2px solid var(--accent);padding-left:.85rem;color:var(--ink-2);max-width:var(--measure)}
.metanote{color:var(--muted);font-size:var(--t-small);max-width:var(--measure)}
/* Verbatim quotes, one expandable row per activity. */
.quotes{display:flex;flex-direction:column;border-top:1px solid var(--rule-soft)}
details.q{border-bottom:1px solid var(--rule-soft)}
details.q summary{cursor:pointer;padding:.55rem 0;display:flex;flex-wrap:wrap;align-items:center;gap:.35rem .7rem}
.q-act{font-weight:500;flex:1 1 16rem}
.q-body{display:flex;flex-direction:column;gap:.8rem;padding:.3rem 0 1rem 1rem;max-width:52rem}
blockquote{margin:0;padding:.1rem 0 .1rem 1rem;border-left:2px solid var(--quote);
  font-style:normal;color:var(--ink-2)}
cite{display:block;font-style:normal;font-size:var(--t-label);color:var(--muted);margin-top:.3rem}
.cond-note{color:var(--muted);font-size:var(--t-small)}
.verdict{display:inline-flex;flex-wrap:wrap;gap:.3rem;align-items:center}

/* ── method ───────────────────────────────────────────────────────────── */
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(18rem,100%),1fr));gap:1.4rem 2.4rem}
.col{display:flex;flex-direction:column;gap:.6rem;font-size:.96rem;color:var(--ink-2)}

/* ── filter ───────────────────────────────────────────────────────────── */
.filter{display:flex;flex-wrap:wrap;gap:.55rem .8rem;align-items:center}
.fq{font:inherit;font-size:var(--t-body);color:var(--ink);background:var(--surface);-webkit-appearance:none;appearance:none;
  flex:1 1 16rem;max-width:28rem;min-height:44px;padding:.5rem .75rem;
  border:1px solid var(--rule);border-radius:3px}
.fq::placeholder{color:var(--muted);opacity:1}
.fbtns{display:flex;flex-wrap:wrap;gap:.35rem}
.fb{font-family:var(--mono);font-size:var(--t-label);font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;color:var(--muted);background:var(--surface);
  min-height:44px;padding:.4rem .7rem;border:1px solid var(--rule);border-radius:2px;cursor:pointer}
.fb:hover{color:var(--ink);border-color:var(--ink)}
.fb[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.fn{font-weight:400;margin-left:.45rem}
.fq:focus-visible,.fb:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.fstat{flex-basis:100%;font-size:var(--t-small);color:var(--muted)}
/* Names in muted lists keep the list's colour; the underline marks the link. */
.lane-who a,.loc-who a{color:inherit}
footer{border-top:1px solid var(--rule);padding-top:1.4rem;display:flex;flex-direction:column;gap:.5rem;
  font-size:var(--t-small);color:var(--ink-2);max-width:var(--measure)}

@media (max-width:40rem){
  .wrap{padding:2rem 1rem 4rem}
  main{gap:3.75rem}
  .case summary{align-items:flex-start}
  .case .w{order:-1}
  .matrix th.rowhead{min-width:min(11rem,42vw)}
  .rule-detail{padding-left:0}
  /* The rules table restacks: one block per activity. Roles in the markup keep
     it a table for assistive technology. */
  .rt thead{position:absolute;width:1px;height:1px;clip-path:inset(50%);overflow:hidden}
  .rt,.rt tbody,.rt tr,.rt th,.rt td{display:block;width:auto!important}
  .rt tr{padding:.6rem 0;border-top:1px solid var(--rule-soft)}
  .rt th,.rt td{border:none;padding:.1rem 0}
  .rt td:nth-child(2),.rt td.rt-d{display:inline-block;margin-right:.5rem;vertical-align:baseline}
  .rt-where{display:inline;margin-left:.3rem}
  .q-body{padding-left:0}
}

/* ── print ────────────────────────────────────────────────────────────────
   Collapsed <details> print EMPTY. Without these rules a printed copy silently
   loses every entity record, every case and every quote — the most-used part
   of the page. The script also opens every <details> before printing.       */
@media print{
  :root{--ground:#fff;--surface:#fff;--surface-2:#fff;--chip:#fff;
        --ink:#000;--ink-2:#222;--muted:#444;--rule:#999;--rule-soft:#ccc}
  body{font-size:10pt}
  .wrap{max-width:none;padding:0;gap:1.6rem}
  main{gap:2rem}
  nav.toc,.skip,.lookup,.copy{display:none!important}
  details.case,details.ent-card{border:1px solid #ccc}
  details>summary{list-style:none}
  details>*{display:block!important}          /* force open */
  .lines{border:1px solid #ccc}
  .tw{overflow:visible;border:1px solid #999}
  .matrix{font-size:7.5pt}
  .matrix th.rowhead{position:static;min-width:0}
  a::after{content:" (" attr(href) ")";font-size:7pt;word-break:break-all;color:#444}
  nav.toc a::after,.case-src a::after{content:""}
  section,.reg,.warn,details{break-inside:avoid}
  details.ent-card{break-inside:auto}
  .filter{display:none!important}
  .tw{max-height:none}
  .matrix thead th{position:static}
  a[href^="#"]::after{content:""}
}
@media print{details::details-content{content-visibility:visible;display:block}}
"""

# Progressive enhancement: the page is complete without this script. It reveals
# the filter bars and the top lookup, hides grid columns and record cards that do
# not match, opens a record when a link points at it (reversing a filter that hid
# it), adds Copy buttons to example wording, and opens every <details> for print.
JS = r"""
(function () {
  var live = document.getElementById('filter-live');
  function say(msg) { if (live) { live.textContent = ''; setTimeout(function () { live.textContent = msg; }, 50); } }

  // Copy buttons on example wording.
  [].forEach.call(document.querySelectorAll('[data-copy]'), function (btn) {
    var box = btn.closest('.tmpl'), q = box && box.querySelector('.tmpl-text');
    if (!q) return;
    btn.hidden = false;
    btn.addEventListener('click', function () {
      var text = q.textContent.trim();
      function done() {
        btn.textContent = 'Copied'; say('Example wording copied');
        setTimeout(function () { btn.textContent = 'Copy'; }, 2000);
      }
      function fallback() {
        var r = document.createRange(); r.selectNodeContents(q);
        var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
        try { if (document.execCommand('copy')) { done(); return; } } catch (e) {}
        say('Wording selected; press Ctrl+C or Cmd+C to copy');
      }
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
      else fallback();
    });
  });

  // Print opens everything; afterwards the reader's own open/closed state returns.
  var reopened = [];
  window.addEventListener('beforeprint', function () {
    reopened = [].filter.call(document.querySelectorAll('details'), function (d) { return !d.open; });
    reopened.forEach(function (d) { d.open = true; });
  });
  window.addEventListener('afterprint', function () {
    reopened.forEach(function (d) { d.open = false; }); reopened = [];
  });

  var bars = [].slice.call(document.querySelectorAll('[data-filter]'));
  var heads = [].slice.call(document.querySelectorAll('table.matrix th.ent'));
  if (!bars.length || !heads.length) return;
  var rows = [].slice.call(document.querySelectorAll('table.matrix tr'));
  var state = {q: '', g: ''}, timer;
  function card(th) { return document.getElementById(th.querySelector('a').getAttribute('href').slice(1)); }
  function apply(announce) {
    var q = state.q.trim().toLowerCase(), keep = [], shown = 0, total = heads.length;
    heads.forEach(function (th) {
      var ok = (!state.g || th.getAttribute('data-g') === state.g) &&
               (!q || th.getAttribute('data-q').indexOf(q) > -1);
      keep.push(ok); if (ok) shown++;
      var c = card(th); if (c) c.hidden = !ok;
    });
    rows.forEach(function (tr) {
      for (var i = 0; i < keep.length; i++) { var c = tr.cells[i + 1]; if (c) c.hidden = !keep[i]; }
    });
    var msg = shown === total ? 'Showing all ' + total + ' organisations'
      : shown ? 'Showing ' + shown + ' of ' + total + ' organisations'
      : 'No organisation matches. Showing 0 of ' + total;
    bars.forEach(function (b) {
      var inp = b.querySelector('.fq');
      if (inp.value !== state.q) inp.value = state.q;
      [].forEach.call(b.querySelectorAll('.fb'), function (btn) {
        btn.setAttribute('aria-pressed', String(btn.getAttribute('data-g') === state.g));
      });
      b.querySelector('.fstat').textContent = msg;
    });
    if (announce && live) {
      clearTimeout(timer);
      timer = setTimeout(function () { live.textContent = msg; }, 400);
    }
  }
  bars.forEach(function (b) {
    b.hidden = false;
    b.querySelector('.fq').addEventListener('input', function (ev) { state.q = ev.target.value; apply(true); });
    [].forEach.call(b.querySelectorAll('.fb'), function (btn) {
      btn.addEventListener('click', function () { state.g = btn.getAttribute('data-g'); apply(true); });
    });
  });

  // The top lookup hands its query to the records filter: same search, one
  // place. The reader keeps typing in the records box, which now has focus.
  var look = document.querySelector('[data-lookup]');
  var rq = document.getElementById('q-records'), recs = document.getElementById('records');
  if (look && rq && recs) {
    look.hidden = false;
    var lq = look.querySelector('input');
    function handoff() {
      state.q = lq.value; state.g = ''; lq.value = ''; apply(true);
      var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      recs.scrollIntoView({behavior: still ? 'auto' : 'smooth', block: 'start'});
      rq.focus({preventScroll: true});
      try { rq.setSelectionRange(rq.value.length, rq.value.length); } catch (e) {}
    }
    lq.addEventListener('input', function () { if (lq.value) handoff(); });
    look.addEventListener('submit', function (ev) { ev.preventDefault(); handoff(); });
  }

  function reveal(id) {
    var t = id && document.getElementById(id);
    if (!t || !t.classList.contains('ent-card')) return;
    if (t.hidden) { state.q = ''; state.g = ''; apply(true); }
    t.open = true;
  }
  document.addEventListener('click', function (ev) {
    var a = ev.target.closest && ev.target.closest('a[href^="#"]');
    if (a) reveal(a.getAttribute('href').slice(1));
  });
  window.addEventListener('hashchange', function () { reveal(decodeURIComponent(location.hash.slice(1))); });
  reveal(decodeURIComponent(location.hash.slice(1)));
  apply(false);
})();
"""


if __name__ == "__main__":
    build()
