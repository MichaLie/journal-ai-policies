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
import json, html, yaml
from consensus import compute as compute_consensus, MIN_CONFIDENT
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


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def cite_html(guide, key) -> str:
    c = guide["citations"].get(key)
    if not c:
        return ""
    doi = f' <a href="https://doi.org/{esc(c["doi"])}">doi:{esc(c["doi"])}</a>' if c.get("doi") else ""
    pmid = f' · PMID {esc(c["pmid"])}' if c.get("pmid") else ""
    return f'<p class="cite">{esc(c["text"])}{doi}{pmid}</p>'


def where_it_goes(axis: str, entities: list[dict]) -> list[tuple[str, list[str]]]:
    """Who wants this declared where, from the records. Never hand-written:
    Wiley routes by purpose, Elsevier fixes one position, ICMJE wants two at
    once. A single generic instruction would be wrong for most readers."""
    from collections import defaultdict
    m = defaultdict(set)
    for e in entities:
        for p in e.get("policies", []):
            if p["axis"] != axis or p["disclosure"] not in ("required", "encouraged"):
                continue
            for loc in (p.get("disclosure_location") or []):
                if loc != "unspecified":
                    m[loc].add(e["name"])
    return sorted(((k, sorted(v)) for k, v in m.items()), key=lambda x: -len(x[1]))


def build() -> None:
    entities = load_entities()
    axes_raw = load_axes()
    axes = axis_index(axes_raw)
    guide = yaml.safe_load((SCHEMA / "reader-guidance.yml").read_text(encoding="utf-8"))
    con = compute_consensus(entities, axes, axes_raw)
    con_by_axis = {r["axis"]: r for r in con["rows"]}

    ages = [a for a in (age_days(entity_last_verified(e)) for e in entities) if a is not None]
    site_age = max(ages) if ages else 9999
    tomb = site_age > TOMBSTONE_DAYS

    order = [a["key"] for a in axes_raw["activities"]] + [a["key"] for a in axes_raw["extended_axes"]]
    used = [k for k in order if any(p["axis"] == k for e in entities for p in e.get("policies", []))]

    n_quotes = sum(len(p.get("evidence", [])) for e in entities for p in e.get("policies", []))
    n_gaps = sum(1 for e in entities for p in e.get("policies", [])
                 if p["permission"] != "not_addressed" and not p.get("evidence"))
    n_coh = sum(len(e.get("coherence") or []) for e in entities)
    n_meta = sum(len(e.get("metadata_inconsistency") or []) for e in entities)
    n_src = sum(len(e.get("sources", [])) for e in entities)
    n_arch = sum(1 for e in entities for s in e.get("sources", [])
                 if s.get("fetch_method") == "archive")

    P = []
    A = P.append
    A('<!doctype html>')
    A('<html lang="en">')
    A('<meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width, initial-scale=1">')
    A('<title>What Journals Actually Require</title>')
    A('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    A('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,600;0,700;1,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">')
    A("<style>" + CSS + "</style>")
    A('<body>')
    A('<a class="skip" href="#main">Skip to content</a>')
    A('<div class="wrap">')

    A('<header>')
    A('<p class="eyebrow">Generative AI in the natural &amp; life sciences</p>')
    A('<h1>What Journals Actually Require</h1>')
    A('<p class="lede">What publishers and research-ethics organisations have actually written down, '
      'quoted word for word and re-checked on a schedule &mdash; so the answer to &ldquo;am I allowed to '
      'do this?&rdquo; comes from a source rather than a rumour.</p>')
    A(f'<p class="meta-row"><span>{len(entities)} organisations</span>'
      f'<span>{n_quotes} quotes, all checked against the page they came from</span>'
      f'<span>updated {today().isoformat()}</span></p>')
    A('</header>')

    A('<nav class="toc" aria-label="Sections">')
    for sid, label in SECTIONS:
        A(f'<a href="#{sid}">{label}</a>')
    A('</nav>')

    if tomb:
        A('<p class="tombstone"><strong>This page is no longer maintained.</strong> '
          f'Its most recent check is {site_age} days old. Policies here change without announcement, '
          'so treat everything below as historical.</p>')
    elif site_age > STALE_DAYS:
        A(f'<p class="warnbar">Oldest record checked {site_age} days ago. Re-checking is overdue.</p>')

    A('<main id="main">')

    # 1 ─ reassurance
    r = guide["reassurance"]
    A('<section id="fine" aria-labelledby="h-fine"><div class="sec-head">'
      '<p class="eyebrow">Read this first</p>'
      f'<h2 id="h-fine">{esc(r["headline"])}</h2></div>')
    A(f'<p class="lede">{esc(r["body"].strip())}</p>')
    A(cite_html(guide, r.get("body_cite")))
    A(f'<div class="bound"><h3>Where the real lines are</h3><p>{esc(r["bound"].strip())}</p></div>')
    dn = guide["detector_note"]
    A(f'<div class="detector"><h3>{esc(dn["headline"])}</h3><p>{esc(dn["body"].strip())}</p>')
    for k in dn.get("cites", []):
        A(cite_html(guide, k))
    A('</div>')
    nf = guide["not_your_fault"]
    A(f'<p class="lede">{esc(nf["body"].strip())}</p>')
    A('</section>')

    # 2 ─ your case
    b = guide["boundary"]
    A('<section id="cases" aria-labelledby="h-cases"><div class="sec-head">'
      '<p class="eyebrow">The common cases</p><h2 id="h-cases">Find what you did</h2></div>')
    A(f'<div class="boundary"><h3>{esc(b["headline"])}</h3>'
      f'<p>{esc(b["body"].strip())}</p><p class="muted">{esc(b["note"].strip())}</p>'
      f'{cite_html(guide, b.get("body_cite"))}</div>')
    A('<p class="muted">Ordered by how often life scientists actually do these things. Verdicts and '
      'placement come from the records further down; the advice and the example wording are ours.</p>')
    A(f'<p class="silence-note">{esc(guide["templates"]["bracket_contract"].strip())}</p>')
    A('<div class="cases">')
    for c in guide["cases"]:
        label, wcls = WORRY[c["worry"]]
        rr = con_by_axis.get(c["axis"])
        if rr and rr["band"] == "void":
            src = f'none of the {rr["n"]} organisations recorded here states a position'
        elif rr and rr["n"] == 1:
            src = '1 organisation recorded here so far'
        elif rr and rr["n"]:
            src = f'{rr["n"]} of {rr["total"]} organisations recorded here so far'
        else:
            src = 'no organisation recorded here yet'
        ex = c.get("example") or {}
        A(f'<details class="case {wcls}"><summary>'
          f'<span class="you">{esc(c["you_did"])}</span>'
          f'<span class="w">{label}</span></summary>'
          f'<div class="case-body"><p>{esc(c["do_this"].strip())}</p>')
        if ex.get("text"):
            places = where_it_goes(c["axis"], entities)
            A('<div class="tmpl"><div class="tmpl-head"><span class="tmpl-tag">'
              + ('example wording' if ex.get("needed") else 'optional wording') + '</span>'
              + ('' if ex.get("needed") else
                 '<span class="tmpl-opt">you probably need write nothing</span>') + '</div>')
            A(f'<blockquote class="tmpl-text">{esc(ex["text"])}</blockquote>')
            if ex.get("note"):
                A(f'<p class="tmpl-note">{esc(ex["note"].strip())}</p>')
                A(cite_html(guide, ex.get("note_cite")))
            if places:
                A('<div class="places"><span class="places-lbl">Where it goes, according to the '
                  'records here</span><ul>')
                for loc, who in places:
                    A(f'<li><span class="loc">{esc(loc.replace("_"," "))}</span>'
                      f'<span class="loc-who">{esc(", ".join(who))}</span></li>')
                A('</ul></div>')
            else:
                A(f'<p class="places-none">{esc((ex.get("placement_fallback") or "No organisation recorded here states where this belongs. Your methods section is the safest default.").strip())}</p>')
            A(f'<p class="tmpl-note">{esc(guide["templates"]["slot_warning"].strip())}</p>')
            A('</div>')
        elif ex.get("note"):
            A(f'<p class="tmpl-none">{esc(ex["note"].strip())}</p>')
        A(f'<p class="case-src">{src}'
          + (' &middot; <a href="#grid">see the grid</a>' if rr and rr["n"] else '') + '</p>')
        A('</div></details>')
    A('</div>')
    nc = guide["not_covered"]
    A(f'<div class="card"><h3>{esc(nc["headline"])}</h3><ul class="plain">')
    for item in nc["items"]:
        t = esc(item)
        t = t.replace("**", "\x00")
        parts = t.split("\x00")
        t = "".join(f"<strong>{s}</strong>" if i % 2 else s for i, s in enumerate(parts))
        A(f'<li>{t}</li>')
    A('</ul></div>')
    A('</section>')

    # 3 ─ what to do
    risky = []
    for rr in con["rows"]:
        forb = [e["name"] for e in entities for pp in e.get("policies", [])
                if pp["axis"] == rr["axis"] and pp["permission"] in ("prohibited", "discouraged")]
        if forb:
            risky.append((rr["plain"], sorted(set(forb))))
    audit_req = sorted({e["name"] for e in entities for pp in e.get("policies", [])
                        if pp["axis"] == "audit_trail" and pp["disclosure"] == "required"})
    ad, af = guide["already_done"], guide["already_found_problem"]

    A('<section id="do" aria-labelledby="h-do"><div class="sec-head">'
      '<p class="eyebrow">What to actually do</p>'
      '<h2 id="h-do">Keep the record. That is the part you cannot recreate.</h2></div><div class="advice">')
    A('<div class="adv adv-do"><h3>Start a log, even a rough one</h3>'
      '<p>Model and <strong>version</strong>, rough dates, the prompts, and the session records '
      'themselves. Everything else can be sorted out at submission &mdash; a disclosure statement takes '
      'ten minutes to write. A transcript from eight months ago cannot be rebuilt, and model versions '
      'get retired.</p>'
      + (f'<p class="adv-ev">Already required, not hypothetical: {esc(", ".join(audit_req))} '
         'asks for prompts, versions or archived session records today.</p>' if audit_req else '') + '</div>')
    A(f'<div class="adv adv-calm"><h3>{esc(ad["headline"])}</h3><p>{esc(ad["body"].strip())}</p></div>')
    A(f'<div class="adv adv-calm"><h3>{esc(af["headline"])}</h3><p>{esc(af["body"].strip())}</p></div>')
    A('<div class="adv adv-flag"><h3>Save a copy of the policy on the day you follow it</h3>'
      '<p>Policies here change without announcement, date stamp or changelog. One publisher rewrote its '
      'whole framework during 2026 with no public notice of any kind. If a rule changes between your '
      'writing and your submission, the burden of showing what it said falls on you &mdash; and the '
      'publisher keeps no public record.</p>'
      '<p class="adv-ev">It is also why this site stores a hash of every source. The snapshot is the receipt.</p></div>')
    A('<div class="adv adv-warn"><h3>Confirm in advance only for these</h3>'
      '<p>Where a use is prohibited outright, the work cannot be fixed at submission. These are the ones '
      'worth checking first, with the organisations here that forbid them:</p><ul class="lanes">')
    for plain, who in risky:
        A(f'<li><span class="lane">{esc(plain)}</span>'
          f'<span class="lane-who">{esc(", ".join(who))}</span></li>')
    A('</ul></div>')
    A(f'<div class="adv adv-cite"><h3>Then check <em>which</em> page applies</h3>'
      '<p>A publisher can have more than one live policy, and they need not agree: one organisation here '
      'has a books policy that forbids what its journals policy permits, sitting behind a URL that ends '
      '&ldquo;in-the-review-process&rdquo;. Each record below marks the page to cite.</p></div>')
    A('</div></section>')

    # 4 ─ consensus
    rows_by = lambda *b: [x for x in con["rows"] if x["band"] in b]
    BANDS = [("holds", ("universal", "strong"), "Holds everywhere we looked",
              "Every organisation assessed takes the same stance. Differing on conditions is noted, but "
              "it is not disagreeing."),
             ("void", ("void",), "Nobody answers this",
              "Every organisation assessed is silent. Not missing data &mdash; a measured, unanimous absence."),
             ("split", ("split",), "Genuinely contested",
              "Organisations disagree on stance, not merely on conditions. The dissenters are named "
              "because they are the useful part."),
             ("thin", ("thin",), "Too thin to call",
              f"Fewer than {MIN_CONFIDENT} organisations assessed. A rule resting on two records is not a "
              "finding, so no claim is made."),
             ("unassessed", ("unassessed",), "Not yet assessed",
              "No organisation here carries a record on this. Work to do, not a result.")]
    A('<section id="summary" aria-labelledby="h-sum"><div class="sec-head">'
      '<p class="eyebrow">Worked out from the records &mdash; never written by hand</p>'
      '<h2 id="h-sum">What actually applies</h2></div>')
    A('<p class="muted">Each fraction is organisations assessed over organisations in this build. A claim '
      'resting on three records is not the same as one resting on thirty, so the denominator is never '
      'hidden. Rows move between groups on their own as records are added.</p>')
    A('<div class="consensus">')
    for key, bands, title, blurb in BANDS:
        rs = rows_by(*bands)
        if not rs:
            continue
        A(f'<div class="band band-{key}"><div class="band-head"><h3>{title}</h3>'
          f'<span class="band-n">{len(rs)} of {len(con["rows"])}</span></div>'
          f'<p class="band-blurb">{blurb}</p><ul class="rules">')
        for x in sorted(rs, key=lambda z: -z["n"]):
            frac = (f'<span class="frac">{x["n"]}<span>/{x["total"]}</span>'
                    f'<span class="vh"> organisations assessed</span></span>')
            if x["band"] == "unassessed":
                A(f'<li>{frac}<span class="rule-txt muted">{esc(x["plain"])}</span></li>'); continue
            if x["band"] == "void":
                A(f'<li>{frac}<span class="rule-txt">{esc(x["plain"])} &mdash; '
                  '<em>no organisation states a position</em></span></li>'); continue
            # On a tied row the modal stance is arbitrary, so "dissenters" are
            # arbitrary too. "No majority ... except X" is a contradiction.
            if x.get("tied"):
                extra = ""
            elif x["dissenters"]:
                extra = f'<span class="dissent">except {esc(", ".join(x["dissenters"]))}</span>'
            elif x.get("conditions_vary"):
                extra = '<span class="varies">conditions vary</span>'
            else:
                extra = ""
            locs = (f'<span class="where">{esc(", ".join(x["locations"]).replace("_"," "))}</span>'
                    if x.get("locations") else "")
            if not x.get("rule"):
                A(f'<li>{frac}<span class="rule-txt">{esc(x["plain"])} &mdash; '
                  '<em>no majority; organisations are evenly divided</em></span>'
                  f'{extra}</li>'); continue
            A(f'<li>{frac}<span class="rule-txt">{esc(x["rule"])}</span>{locs}{extra}</li>')
        A('</ul></div>')
    A('</div></section>')

    # 5 ─ grid
    A('<section id="grid" aria-labelledby="h-grid"><div class="sec-head">'
      '<p class="eyebrow">Nine activities from STM\'s 2025 classification, then the ones it leaves out</p>'
      '<h2 id="h-grid">The evidence grid</h2></div>')
    A(f'<p class="silence-note">{esc(guide["silence_note"].strip())}</p>')
    A('<div class="legend" role="group" aria-label="Legend">'
      '<span class="p ok">permitted</span><span class="p cond">conditional</span>'
      '<span class="p no">prohibited</span><span class="p silent">silent</span>'
      '<span class="p none">&mdash;</span><span class="sep"></span>'
      '<span class="d d-required">required</span><span class="d d-encouraged">encouraged</span>'
      '<span class="d d-exempt">exempt</span><span class="d d-silent">silent</span></div>')
    A('<p class="muted">Each cell carries two values: whether the use is <strong>permitted</strong>, and '
      'whether it <strong>must be declared</strong>. <span class="p silent">silent</span> means we '
      'checked and the organisation publishes nothing. <span class="p none">&mdash;</span> means '
      'something weaker: not yet assessed here. Treating those as the same would let unfinished work '
      'read as a finding.</p>')
    A('<div class="tw" tabindex="0" role="region" aria-label="Evidence grid, scrollable">'
      '<table class="matrix">')
    A('<caption>Permission and disclosure by organisation and activity. '
      'Scroll sideways to see all organisations.</caption>')
    A('<thead><tr><th class="rowhead" scope="col">Activity</th>')
    for e in entities:
        A(f'<th class="ent" scope="col">{esc(e["name"])}</th>')
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
    A('</tbody></table></div>')
    A(f'<p class="muted foot">A <span class="gap">?</span> marks a cell whose verdict is recorded but '
      f'whose quote is not yet captured. {n_gaps} remain, published rather than hidden.</p></section>')

    # 6 ─ records
    A('<section id="records" aria-labelledby="h-rec"><div class="sec-head">'
      '<p class="eyebrow">Sources</p><h2 id="h-rec">Organisations, and what to cite</h2></div>')
    for e in entities:
        d = age_days(entity_last_verified(e)); f = freshness(d)
        A('<details class="ent-card"><summary>')
        A(f'<span class="ent-name">{esc(e["name"])}</span>')
        A(f'<span class="tag">{esc(e["type"].replace("_"," "))}</span>')
        if e.get("policy_architecture"):
            A(f'<span class="tag arch">{esc(e["policy_architecture"].replace("_"," "))}</span>')
        if e.get("coherence"):
            A(f'<span class="tag flagged">{len(e["coherence"])} internal contradiction'
              f'{"s" if len(e["coherence"]) > 1 else ""}</span>')
        A(f'<span class="f {f}">checked {d if d is not None else "?"}d ago</span>')
        A('</summary><div class="ent-body">')
        if e.get("notes"):
            A(f'<p class="note">{esc(e["notes"].strip())}</p>')
        if e.get("delegates_to_journal"):
            A('<p class="inline-flag">Individual journals genuinely differ from this policy &mdash; '
              'check your specific journal as well.</p>')
        auth = [s for s in e.get("sources", []) if s.get("authoritative")]
        others = [s for s in e.get("sources", []) if not s.get("authoritative")]
        A('<h3>Cite this</h3><ul class="srcs">')
        for s in auth:
            A(src_li(s, True))
        A('</ul>')
        if others:
            A('<h3>Also held, but not the one to cite</h3><ul class="srcs">')
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
        quoted = [p for p in e.get("policies", []) if p.get("evidence")]
        if quoted:
            A('<h3>What it says, word for word</h3>')
            for p in quoted:
                A(f'<div class="ev"><p class="ev-axis">{esc(axes[p["axis"]]["title"])}</p>')
                for ev in p["evidence"]:
                    prov = ev["quote_provenance"]
                    plabel = {"raw_bytes": "checked against the page",
                              "summariser_relayed": "relayed, not directly checked",
                              "unverified": "not verified"}[prov]
                    role = ("" if ev.get("evidence_role", "supports") == "supports"
                            else '<span class="prov absence">what is said instead</span> &middot; ')
                    A(f'<blockquote>{esc(ev["quote"])}<cite>{role}{esc(e["name"])} &middot; '
                      f'{esc(ev["source"])} &middot; <span class="prov {prov}">{plabel}</span></cite></blockquote>')
                if p.get("conditions"):
                    A(f'<p class="cond-note">{esc(p["conditions"].strip())}</p>')
                A('</div>')
        A('</div></details>')
    A('</section>')

    # 7 ─ method
    A('<section id="method" aria-labelledby="h-meth"><div class="sec-head">'
      '<p class="eyebrow">Method</p><h2 id="h-meth">What this does and does not claim</h2></div><div class="cols">')
    A(f'<div class="card"><h3>Word for word, or not at all</h3><p>Every verdict carries a short quote, '
      f'its source, and how it was obtained. All {n_quotes} quotes on this page are checked automatically '
      'against the stored copy of the page they came from; the build fails if any quote cannot be found. '
      'An earlier version of this site carried a sentence in quotation marks that turned out to be a '
      'research assistant’s paraphrase. That is what this check exists to prevent.</p></div>')
    A('<div class="card"><h3>Published policy only</h3><p>This records what organisations have published. '
      'It cannot see what editors actually do. Across seventeen cardiovascular journals studied, fifteen '
      'ran AI-detection software and one said so publicly &mdash; the gap between stated and practised is '
      'real, and this site does not close it.</p></div>')
    A(f'<div class="card"><h3>Coverage, stated plainly</h3><p>{len(entities)} organisations, of which nine '
      'are Anglophone and one is not. Journal-level records, funders, preprint servers and content '
      'licensing are not covered yet. If your funder or institution is not here, that means we have not '
      'looked &mdash; not that it is silent.</p></div>')
    A(f'<div class="card"><h3>Where the bytes come from</h3><p>{n_src - n_arch} of {n_src} sources are '
      f'fetched directly. {n_arch} return a block page or a challenge to any automated client, so those '
      'records are checked against dated Internet Archive captures instead, and each says so. Nothing is '
      'recorded from memory.</p></div>')
    A(f'<div class="card"><h3>Contradictions, counted honestly</h3><p>{n_coh} substantive internal '
      f'contradiction{"s" if n_coh != 1 else ""} and {n_meta} dating or tagging '
      f'oddit{"ies" if n_meta != 1 else "y"} across {len(entities)} organisations. A stale HTML title tag '
      'is not a policy contradiction and is not counted as one. Research notes record more contradictions '
      'among organisations not yet recorded here.</p></div>')
    A(f'<div class="card"><h3>{n_gaps} cells still await a quote</h3><p>Verdicts recorded without captured '
      'wording are marked and published, never asserted as verified. Where we could not find wording at '
      'all, the cell was changed to &ldquo;silent&rdquo; rather than left as a claim.</p></div>')
    A('</div>')
    A(f'<p class="muted foot">This page declares itself unmaintained automatically once its oldest record '
      f'passes {TOMBSTONE_DAYS} days without re-checking. The closest precedent to this project still '
      'serves a live page, with no staleness warning, four years after its last update.</p>')
    A('<div class="card"><h3>Corrections and right of reply</h3><p>If you work for an organisation '
      'recorded here and think a record is wrong, we want to fix it. Every record names its source and '
      'quotes the wording it relies on, so corrections can be specific. '
      '<a href="https://github.com/MichaLie/journal-ai-policies/issues">Open an issue</a> and we will respond. Corrected records carry '
      'the date they changed, and the change stays in the public history.</p></div>')
    A('</section>')
    A('</main>')

    A('<footer><p class="eyebrow">Source and licence</p>'
      '<p>Maintained by <a href="https://github.com/MichaLie">MichaLie</a>. '
      'Records, code and full change history: <a href="https://github.com/MichaLie/journal-ai-policies">github.com/MichaLie/journal-ai-policies</a>. '
      'Corrections via <a href="https://github.com/MichaLie/journal-ai-policies/issues">issues</a>.</p>'
      '<p>Data CC0. Code MIT. Quoted policy text still belongs to the publishers, and is reproduced here '
      'as short excerpts for comparison and criticism, with attribution and a link to the source.</p>'
      '<p class="muted">The reassurance and advice on this page are our own wording. Every verdict, '
      'fraction and named organisation is worked out from the records.</p></footer>')
    A('</div></body></html>')

    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text("\n".join(P), encoding="utf-8")
    dump = {"generated": today().isoformat(),
            "rights": ("Records CC0. Quoted policy text remains the property of the publishers named and "
                       "is reproduced as short excerpts for comparison and criticism."),
            "consensus": con, "axes": axes_raw,
            "entities": [{k: v for k, v in e.items() if not k.startswith("_")} for e in entities]}
    (DOCS / "data.json").write_text(json.dumps(dump, indent=2, ensure_ascii=False, default=str),
                                    encoding="utf-8")
    print(f"built docs/index.html  ({len(entities)} entities, {len(used)} axes, {n_quotes} quotes, "
          f"{n_coh} contradictions, {n_meta} metadata notes, {n_gaps} gaps)")
    print("built docs/data.json")


def src_li(s: dict, authoritative: bool) -> str:
    d = age_days(s.get("last_verified")); f = freshness(d)
    url = s.get("url")
    link = (f'<a href="{esc(url)}">{esc(url)}</a>' if url
            else '<span class="nourl">URL not yet confirmed</span>')
    bits = [f'<span class="tag">{esc(s.get("audience", "all"))}</span>',
            f'<span class="tag st-{esc(s["status"])}">{esc(s["status"].replace("_", " "))}</span>',
            f'<span class="tag">{esc(s.get("fetch_method", "http"))}</span>']
    if authoritative:
        bits.insert(0, '<span class="tag auth">cite this</span>')
    bits.append(f'<span class="tag">states {esc(s["stated_date"])}</span>' if s.get("stated_date")
                else '<span class="tag undated">undated</span>')
    note = f'<p class="src-note">{esc(s["note"].strip())}</p>' if s.get("note") else ""
    return (f'<li class="{"auth" if authoritative else ""}">{link}{note}'
            f'<div class="src-tags">{"".join(bits)}'
            f'<span class="f {f}">checked {d if d is not None else "?"}d ago</span></div></li>')
CSS = r"""
/* ── tokens ───────────────────────────────────────────────────────────────
   Every colour is defined here, in the bare :root, and redefined in BOTH the
   prefers-color-scheme block and the [data-theme] block. A colour defined only
   inside a theme block renders one theme's text on the other theme's ground.
   --accent means ONE thing: attention/staleness. Quotes, row numbers and
   required-disclosure each have their own token, because an accent that means
   four things means nothing.                                                */
:root{
  --ground:#F6F7F8; --surface:#FFFFFF; --surface-2:#EDF0F3; --chip:#E7EBEF;
  --ink:#161B21; --ink-2:#39424B; --muted:#57626D;
  --rule:#D3D9DF; --rule-soft:#E5E9ED;
  --accent:#8F3116;            /* attention + staleness + focus, nothing else */
  --quote:#B0B7BF;             /* quotation rules */
  --req:#7A4A0E;               /* "must be declared" */
  --ok:#175C40; --cond:#7A5A11; --no:#6E1F2C; --live:#1B47A0;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#10141A; --surface:#171C23; --surface-2:#1E252D; --chip:#232B34;
  --ink:#E8ECF0; --ink-2:#C2CAD3; --muted:#96A1AD;
  --rule:#2C343D; --rule-soft:#232A32;
  --accent:#E4805A; --quote:#4A545F; --req:#D6A860;
  --ok:#56AB84; --cond:#D0AC5C; --no:#E07E92; --live:#89ADEC;
}}
:root[data-theme="dark"]{
  --ground:#10141A; --surface:#171C23; --surface-2:#1E252D; --chip:#232B34;
  --ink:#E8ECF0; --ink-2:#C2CAD3; --muted:#96A1AD;
  --rule:#2C343D; --rule-soft:#232A32;
  --accent:#E4805A; --quote:#4A545F; --req:#D6A860;
  --ok:#56AB84; --cond:#D0AC5C; --no:#E07E92; --live:#89ADEC;
}

/* ── type scale ───────────────────────────────────────────────────────────
   Eight steps, no others. The previous stylesheet had 24 distinct sizes, five
   of them spanning 0.8px, and 413 elements at or below 10px against 63 at 16.
   Label floor raised to .72rem: below about 11px, uppercase letterspaced mono
   stops being scannable and becomes texture.                                */
:root{
  --t-label:.72rem; --t-small:.86rem; --t-body:1rem; --t-lead:1.15rem;
  --t-h3:1.06rem; --pad-card:1.05rem 1.25rem; --track:minmax(min(18rem,100%),1fr);
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;overflow-x:clip}
body{overflow-x:clip}
body{background:var(--ground);color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:var(--t-body);line-height:1.62;margin:0;-webkit-font-smoothing:antialiased}
.wrap{max-width:74rem;margin:0 auto;padding:3rem 1.5rem 6rem;display:flex;
  flex-direction:column;gap:3.25rem;min-width:0}
h1,h2,h3{font-family:Spectral,Georgia,serif;text-wrap:balance;margin:0;line-height:1.2}
h1{font-size:clamp(2.1rem,5vw,3rem);font-weight:700;letter-spacing:-.015em}
h2{font-size:clamp(1.4rem,3vw,1.8rem);font-weight:600}
h3{font-size:var(--t-h3);font-weight:600}
p{margin:0}
a{color:var(--live);text-decoration:underline;text-underline-offset:2px}
a:focus-visible,summary:focus-visible,.tw:focus-visible,.skip:focus{
  outline:2px solid var(--accent);outline-offset:3px;border-radius:2px}
.vh{position:absolute;width:1px;height:1px;clip-path:inset(50%);overflow:hidden;white-space:nowrap}
.skip{position:absolute;left:-9999px}
.skip:focus{position:fixed;left:1rem;top:1rem;z-index:9;background:var(--surface);
  color:var(--ink);padding:.9rem 1.1rem;min-height:44px;border:2px solid var(--accent);
  border-radius:3px}

.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.lede{font-family:Spectral,Georgia,serif;font-size:var(--t-lead);line-height:1.55;
  color:var(--ink-2);max-width:46rem}
.muted{color:var(--muted)}
.foot{font-size:var(--t-small)}
.cite{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  color:var(--muted);line-height:1.5}
.cite a{color:var(--live)}

header{display:flex;flex-direction:column;gap:1rem;padding-bottom:2rem;border-bottom:2px solid var(--ink)}
.meta-row{display:flex;flex-wrap:wrap;gap:.4rem 1.3rem;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:var(--t-label);letter-spacing:.05em;color:var(--muted);text-transform:uppercase}
nav.toc{display:flex;flex-wrap:wrap;gap:.4rem .9rem;padding:.7rem 0;border-bottom:1px solid var(--rule)}
nav.toc a{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  letter-spacing:.06em;text-transform:uppercase;text-decoration:none;color:var(--muted);
  padding:.85rem .25rem;min-height:44px;display:flex;align-items:center;
  border-bottom:2px solid transparent}
nav.toc a:hover,nav.toc a:focus-visible{color:var(--ink);border-bottom-color:var(--accent)}

section{display:flex;flex-direction:column;gap:1.25rem;min-width:0}
.sec-head{display:flex;flex-direction:column;gap:.4rem;padding-bottom:.6rem;border-bottom:1px solid var(--rule)}
.tombstone{background:var(--no);color:#fff;padding:1.25rem 1.5rem;border-radius:3px}
/* dark palette's --no is light, so white-on-it fails; flip the text instead */
:root[data-theme="dark"] .tombstone{color:#12161B}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .tombstone{color:#12161B}}
.warnbar{background:var(--surface-2);border-left:3px solid var(--cond);padding:.9rem 1.2rem;border-radius:3px}

/* ── one label system ─────────────────────────────────────────────────── */
.lbl,.p,.d,.f,.tag,.gap,.prov,.w,.dissent,.varies,.where,.lane-who,.loc,
.reg-tag,.tmpl-tag,.band-n,.tmpl-opt{
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  padding:.16rem .42rem;border-radius:2px;display:inline-block}
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
.f{border:1px solid currentColor;white-space:nowrap}
.f.fresh{color:var(--ok)}.f.aging{color:var(--cond)}.f.stale{color:var(--accent)}
.f.expired,.f.unknown{color:var(--no)}
.tag{background:var(--chip);color:var(--muted);border:1px solid transparent}
.tag.arch{color:var(--live)}.tag.flagged{color:var(--accent);border-color:var(--accent)}
.tag.undated{color:var(--cond)}.tag.auth{color:var(--ok);border-color:var(--ok)}
.tag.st-current{color:var(--ok)}
.tag.st-superseded,.tag.st-stale_but_live{color:var(--accent)}
.tag.st-unconfirmed{color:var(--cond)}
.prov{padding:0 .3rem}
.prov.raw_bytes{color:var(--ok)}.prov.summariser_relayed{color:var(--cond)}
.prov.unverified{color:var(--no)}
.prov.absence{color:var(--live)}

/* ── matrix ───────────────────────────────────────────────────────────── */
.tw{overflow-x:auto;min-width:0;max-width:100%;border:1px solid var(--rule);
  border-radius:3px;background:var(--surface)}
table.matrix{border-collapse:collapse;width:100%}
.matrix th,.matrix td{border-bottom:1px solid var(--rule-soft);border-right:1px solid var(--rule-soft);
  padding:.5rem .6rem;vertical-align:top;text-align:left}
.matrix thead th{background:var(--surface-2);border-bottom:1px solid var(--rule)}
.matrix th.ent{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  letter-spacing:.04em;text-transform:uppercase;color:var(--muted);font-weight:600;min-width:5.5rem}
.matrix th.rowhead{font-family:inherit;font-size:var(--t-small);font-weight:400;line-height:1.35;
  min-width:min(14rem,52vw);max-width:18rem;background:var(--surface);
  position:sticky;left:0;z-index:1;
  border-right:1px solid var(--rule)}
.matrix thead th.rowhead{background:var(--surface-2);z-index:2}
.matrix .num{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  color:var(--muted);font-weight:600;margin-right:.45rem}
.matrix tr.extrow th.rowhead{font-style:italic;color:var(--ink-2)}
.cell{display:table-cell}
.cell .stack{display:flex;flex-direction:column;gap:.22rem;align-items:flex-start}
caption{text-align:left;padding:.6rem .85rem;font-size:var(--t-small);color:var(--muted);
  border-bottom:1px solid var(--rule)}
.legend{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.legend .sep{width:1px;height:1.1rem;background:var(--rule);margin:0 .4rem}

/* ── cards & blocks ───────────────────────────────────────────────────── */
.cols,.advice,.register{display:grid;grid-template-columns:repeat(auto-fit,var(--track));gap:1rem}
.card,.adv,.band,.reg,.bound{background:var(--surface);border:1px solid var(--rule-soft);
  border-left:3px solid var(--rule);padding:var(--pad-card);border-radius:3px;
  display:flex;flex-direction:column;gap:.55rem;font-size:var(--t-body)}
.card,.adv,.reg{font-size:.96rem}
.adv-do{border-left-color:var(--accent);grid-column:1/-1}
.adv-calm{border-left-color:var(--ok)}
.adv-warn{border-left-color:var(--no)}
.adv-flag{border-left-color:var(--cond)}
.adv-cite{border-left-color:var(--live)}
.adv-ev{font-size:var(--t-small);color:var(--muted)}
.bound{border-left-color:var(--no);max-width:46rem}
.reg-bad{border-left-color:var(--no)}
.reg-good{border-left-color:var(--ok)}
.reg p{font-family:Spectral,Georgia,serif;font-style:italic;color:var(--ink-2);line-height:1.5}
.reg-tag{padding:0}
.reg-bad .reg-tag{color:var(--no)}.reg-good .reg-tag{color:var(--ok)}
.silence-note{background:var(--surface-2);border-left:3px solid var(--ok);
  padding:.85rem 1.15rem;border-radius:3px;max-width:52rem}
.detector{background:var(--surface);border:1px solid var(--rule-soft);
  border-left:3px solid var(--live);padding:var(--pad-card);border-radius:3px;
  display:flex;flex-direction:column;gap:.55rem;max-width:52rem}
.boundary{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--accent);
  padding:1.2rem 1.4rem;border-radius:3px;display:flex;flex-direction:column;gap:.6rem}

/* ── consensus bands ──────────────────────────────────────────────────── */
.consensus{display:flex;flex-direction:column;gap:1rem}
.band-holds{border-left-color:var(--ok)}
.band-void{border-left-color:var(--accent)}
.band-split{border-left-color:var(--cond)}
.band-thin,.band-unassessed{border-left-color:var(--rule)}
.band-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.7rem;justify-content:space-between}
.band-n{background:var(--chip);color:var(--muted);font-weight:400}
.band-blurb{font-size:var(--t-small);color:var(--muted);max-width:52rem}
ul.rules{list-style:none;margin:.15rem 0 0;padding:0;display:flex;flex-direction:column;gap:.45rem}
ul.rules li{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem;padding:.4rem 0;
  border-top:1px solid var(--rule-soft);font-size:.96rem}
ul.rules li:first-child{border-top:none}
.frac{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums;
  font-size:var(--t-small);font-weight:600;color:var(--ink-2);min-width:3.2rem}
.frac span{color:var(--muted);font-weight:400}
.rule-txt{flex:1 1 22rem}
.dissent{color:var(--cond);border:1px solid currentColor;white-space:normal}
.varies{color:var(--muted);border:1px dashed currentColor}
.where{color:var(--live);background:var(--chip)}

/* ── cases ────────────────────────────────────────────────────────────── */
.cases{display:flex;flex-direction:column;gap:.5rem}
details.case,details.ent-card{border:1px solid var(--rule-soft);border-left:3px solid var(--rule);
  border-radius:3px;background:var(--surface)}
details.case.w-low{border-left-color:var(--ok)}
details.case.w-some{border-left-color:var(--cond)}
details.case.w-check{border-left-color:var(--no)}
details.case summary,details.ent-card summary{cursor:pointer;padding:.8rem 1.1rem;
  display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;min-height:2.9rem}
details[open].case summary,details[open].ent-card summary{border-bottom:1px solid var(--rule-soft)}
.case .w{border:1px solid currentColor;white-space:nowrap}
.case.w-low .w{color:var(--ok)}.case.w-some .w{color:var(--cond)}.case.w-check .w{color:var(--no)}
.case .you{flex:1 1 20rem;font-size:var(--t-body)}
.case-body{padding:.9rem 1.1rem;display:flex;flex-direction:column;gap:.6rem;
  font-size:.96rem;color:var(--ink-2)}
.case-src{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.case-src a,ul.srcs li a{display:inline-block;padding-block:.55rem}

/* ── templates ────────────────────────────────────────────────────────── */
.tmpl{border:1px solid var(--rule);border-radius:3px;background:var(--surface-2);
  padding:.85rem 1rem;display:flex;flex-direction:column;gap:.6rem}
.tmpl-head{display:flex;flex-wrap:wrap;gap:.5rem;align-items:baseline}
.tmpl-tag{color:var(--accent);padding:0}
.tmpl-opt{color:var(--ok);padding:0;font-weight:400}
blockquote.tmpl-text{margin:0;font-family:"IBM Plex Mono",ui-monospace,monospace;font-style:normal;
  font-size:var(--t-small);line-height:1.7;border-left:2px solid var(--accent);background:var(--surface);
  padding:.75rem .9rem;border-radius:2px;color:var(--ink);user-select:all}
.tmpl-note{font-size:var(--t-small);color:var(--muted)}
.tmpl-none{border-left:3px solid var(--no);padding-left:.9rem;color:var(--ink-2);font-size:.96rem}
.places{display:flex;flex-direction:column;gap:.35rem}
.places-lbl{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.places ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.3rem}
.places li{display:flex;flex-wrap:wrap;gap:.45rem;align-items:baseline}
.loc{color:var(--live);background:var(--chip)}
.loc-who{font-size:var(--t-small);color:var(--muted)}
.places-none{font-size:var(--t-small);color:var(--muted)}
ul.lanes{list-style:none;margin:.2rem 0 0;padding:0;display:flex;flex-direction:column;gap:.4rem}
ul.lanes li{display:flex;flex-wrap:wrap;gap:.4rem;align-items:baseline;padding:.35rem 0;
  border-top:1px solid var(--rule-soft)}
ul.lanes li:first-child{border-top:none}
.lane{flex:1 1 12rem;font-size:.96rem}
.lane-who{color:var(--no);border:1px solid currentColor;white-space:normal}

/* ── entity records ───────────────────────────────────────────────────── */
details.ent-card+details.ent-card{margin-top:.55rem}
.ent-name{font-family:Spectral,Georgia,serif;font-size:var(--t-body);font-weight:600;margin-right:.3rem}
.ent-body{padding:1.05rem 1.25rem;display:flex;flex-direction:column;gap:.9rem;font-size:.96rem}
.note{color:var(--ink-2)}
.inline-flag{border-left:3px solid var(--accent);padding-left:.8rem;color:var(--ink-2)}
ul.srcs{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.55rem}
ul.srcs li{padding:.55rem .7rem;border:1px solid var(--rule-soft);border-radius:3px;
  word-break:break-word;font-size:var(--t-small)}
ul.srcs li.auth{border-left:3px solid var(--ok)}
.src-tags{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.4rem}
.src-note{color:var(--muted);font-size:var(--t-small);margin-top:.35rem}
.nourl{color:var(--cond);font-style:italic}
.contra{border-left:3px solid var(--accent);padding-left:.85rem;color:var(--ink-2)}
.metanote{border-left:3px solid var(--rule);padding-left:.85rem;color:var(--muted);font-size:var(--t-small)}
.ev{display:flex;flex-direction:column;gap:.5rem;padding:.7rem 0;border-top:1px solid var(--rule-soft)}
.ev-axis{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:var(--t-label);
  letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
blockquote{margin:0;padding:.1rem 0 .1rem 1rem;border-left:2px solid var(--quote);
  font-family:Spectral,Georgia,serif;font-style:italic;color:var(--ink-2)}
cite{display:block;font-family:"IBM Plex Mono",ui-monospace,monospace;font-style:normal;
  font-size:var(--t-label);letter-spacing:.03em;color:var(--muted);margin-top:.35rem;text-transform:uppercase}
.cond-note{color:var(--muted);font-size:var(--t-small)}
ul.plain{margin:0;padding-left:1.15rem;display:flex;flex-direction:column;gap:.5rem}
ul.plain li::marker{color:var(--muted)}
strong{font-weight:600;color:var(--ink)}
footer{border-top:2px solid var(--ink);padding-top:1.4rem;display:flex;flex-direction:column;gap:.5rem}

@media (max-width:40rem){
  .case summary{align-items:flex-start}
  .case .w{order:-1;flex-basis:100%}
}

/* ── print ────────────────────────────────────────────────────────────────
   Collapsed <details> print EMPTY. Without this rule a printed copy silently
   loses every entity record and every case — the most-used part of the page. */
@media print{
  :root{--ground:#fff;--surface:#fff;--surface-2:#fff;--chip:#fff;
        --ink:#000;--ink-2:#222;--muted:#444;--rule:#999;--rule-soft:#ccc}
  body{font-size:10pt}
  .wrap{max-width:none;padding:0;gap:1.6rem}
  nav.toc,.skip{display:none}
  details{border:1px solid #ccc}
  details>summary{list-style:none}
  details>*{display:block!important}          /* force open */
  .tw{overflow:visible;border:1px solid #999}
  .matrix{font-size:7.5pt}
  .matrix th.rowhead{position:static;min-width:0}
  a::after{content:" (" attr(href) ")";font-size:7pt;word-break:break-all;color:#444}
  nav.toc a::after,.case-src a::after{content:""}
  section,.card,.adv,.band,.reg,.ev,details{break-inside:avoid}
}
"""


if __name__ == "__main__":
    build()
